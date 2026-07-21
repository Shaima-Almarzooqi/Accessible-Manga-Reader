"""The "Ask about this page" dialog.

The reader types a question about the current page (or a small range),
and the AI answers by looking at the raw page images again, with the
existing script and character notes as context. Follow-up questions in
the same session include the earlier exchanges. The conversation is not
saved; Copy answer puts the latest answer on the clipboard.

The question appears in the conversation the moment it is sent, with a
progress note under its Answer heading, so the window is never blank
while the AI works. Ask becomes Stop for the duration: stopping takes
effect at once, and the reply is discarded if it arrives afterwards.
"""

import threading

import wx

try:
    import wx.html2
except ImportError:
    wx.html2 = None

from core import ask, api_client

from . import keys as keyhelp


class AskDialog(wx.Dialog):
    def __init__(self, parent, book, settings, current_page):
        title = "Ask about this page - %s" % (book.title or "Book")
        super().__init__(parent, title=title, size=(640, 560),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.book = book
        self.settings = settings
        self.current_page = current_page
        # Completed exchanges, which double as the context sent with the
        # next question. `pending` holds the question being asked now (or
        # the last stopped or failed one): it is shown in the
        # conversation but never sent as context, having no real answer.
        self.history = []
        self.pending = None
        self._busy = False
        self._cancel = threading.Event()
        # Bumped for every request, and again when one is abandoned, so a
        # reply that arrives after Stop is recognised and discarded.
        self._request_id = 0
        self._focus_after_load = False

        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(
            self, label="&Question (the AI answers by looking at the "
            "page images again; each question uses your AI service like "
            "processing does):"), 0, wx.ALL, 6)
        self.question = wx.TextCtrl(self, style=wx.TE_MULTILINE,
                                    size=(-1, 70))
        sizer.Add(self.question, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

        self.scope = wx.RadioBox(
            self, label="Pages to look at",
            choices=["This page (page %d)" % current_page,
                     "This page plus the previous and next",
                     "A page range (at most %d pages)" % ask.MAX_ASK_PAGES],
            majorDimension=1, style=wx.RA_SPECIFY_COLS)
        sizer.Add(self.scope, 0, wx.EXPAND | wx.ALL, 6)
        self.scope.Bind(wx.EVT_RADIOBOX, self._on_scope)

        range_row = wx.BoxSizer(wx.HORIZONTAL)
        range_row.Add(wx.StaticText(self, label="&From page:"), 0,
                      wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.range_from = wx.SpinCtrl(
            self, min=1, max=book.page_count, initial=current_page)
        range_row.Add(self.range_from, 0, wx.RIGHT, 10)
        range_row.Add(wx.StaticText(self, label="&To page:"), 0,
                      wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.range_to = wx.SpinCtrl(
            self, min=1, max=book.page_count, initial=current_page)
        range_row.Add(self.range_to, 0)
        sizer.Add(range_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        self.range_from.Enable(False)
        self.range_to.Enable(False)

        # One button for both actions: it never leaves the tab order, and
        # its label doubles as a status ("Stop" means a question is in
        # flight). Disabling it would hide it from keyboard users.
        self.ask_button = wx.Button(self, label="&Ask")
        self.ask_button.Bind(wx.EVT_BUTTON, self.on_ask_or_stop)
        self.ask_button.SetDefault()
        sizer.Add(self.ask_button, 0, wx.LEFT | wx.BOTTOM, 6)

        sizer.Add(wx.StaticText(self, label="A&nswers:"), 0,
                  wx.LEFT | wx.RIGHT, 6)
        # The conversation renders as an HTML document: each question is
        # a heading, so browse mode moves between exchanges with H, and
        # the AI's structure reads cleanly instead of as symbols. Falls
        # back to a plain text control if no web view is available.
        self.answers_text = None
        self.answers_view = None
        if wx.html2 is not None:
            try:
                self.answers_view = wx.html2.WebView.New(self)
                self.answers_view.SetName("Answers")
            except Exception:
                self.answers_view = None
        if self.answers_view is not None:
            self.answers_view.Bind(wx.html2.EVT_WEBVIEW_LOADED,
                                   self._on_view_loaded)
            sizer.Add(self.answers_view, 1,
                      wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        else:
            self.answers_text = wx.TextCtrl(
                self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
            sizer.Add(self.answers_text, 1,
                      wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        copy_button = wx.Button(self, label="&Copy answer")
        copy_button.Bind(wx.EVT_BUTTON, self.on_copy)
        buttons.Add(copy_button, 0, wx.RIGHT, 6)
        close_button = wx.Button(self, wx.ID_CANCEL, "Cl&ose")
        close_button.Bind(wx.EVT_BUTTON, self.on_close_button)
        buttons.Add(close_button, 0)
        sizer.Add(buttons, 0, wx.ALL, 6)

        self.SetSizer(sizer)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.question.SetFocus()
        # Give the view a document straight away. An empty web view is
        # announced by its underlying window class rather than a document
        # title, and it would show nothing until the first answer landed.
        wx.CallAfter(self._render)

    # ----- display ---------------------------------------------------------

    def _exchanges(self):
        exchanges = list(self.history)
        if self.pending is not None:
            exchanges.append(self.pending)
        return exchanges

    def _render(self, focus_answers=False):
        if not self:
            return
        if self.answers_view is not None:
            self._focus_after_load = focus_answers
            self.answers_view.SetPage(
                ask.conversation_html(self.book.title or "Book",
                                      self.history, self.pending), "")
            return
        exchanges = self._exchanges()
        if not exchanges:
            self.answers_text.SetValue(ask.EMPTY_TEXT)
            return
        text = ""
        last_offset = 0
        for index, (question, answer) in enumerate(exchanges, start=1):
            last_offset = len(text)
            text += "Question %d: %s\nAnswer: %s\n\n" % (
                index, question, answer)
        self.answers_text.SetValue(text)
        if focus_answers:
            self.answers_text.SetFocus()
            self.answers_text.SetInsertionPoint(last_offset)

    def _on_view_loaded(self, event):
        # Focus only once the document exists, so the screen reader
        # announces the document instead of an empty control.
        if self._focus_after_load:
            self._focus_after_load = False
            self.answers_view.SetFocus()

    # ----- asking ----------------------------------------------------------

    def _on_scope(self, event):
        custom = self.scope.GetSelection() == 2
        self.range_from.Enable(custom)
        self.range_to.Enable(custom)

    def _on_char_hook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._abandon_request()
            self.EndModal(wx.ID_CANCEL)
            return
        if keyhelp.consume_arrow_navigation(event, wx.Window.FindFocus()):
            return
        event.Skip()

    def _pages_for_scope(self):
        selection = self.scope.GetSelection()
        if selection == 0:
            return [self.current_page]
        if selection == 1:
            pages = [self.current_page - 1, self.current_page,
                     self.current_page + 1]
            return [p for p in pages if 1 <= p <= self.book.page_count]
        start = self.range_from.GetValue()
        end = self.range_to.GetValue()
        if end < start:
            start, end = end, start
        pages = list(range(start, end + 1))
        return pages[:ask.MAX_ASK_PAGES]

    def _abandon_request(self):
        """Stop caring about the request in flight, if there is one."""
        if not self._busy:
            return
        self._cancel.set()
        self._request_id += 1  # its reply is no longer ours
        self._busy = False

    def on_ask_or_stop(self, event):
        if self._busy:
            self.on_stop()
            return
        question = self.question.GetValue().strip()
        if not question:
            self.question.SetFocus()
            return
        pages = self._pages_for_scope()

        self._busy = True
        self._cancel = threading.Event()
        self._request_id += 1
        request_id = self._request_id
        cancel = self._cancel
        # A copy: the real list keeps changing on the main thread while
        # the worker runs.
        history = list(self.history)

        self.pending = (question, ask.WAITING_TEXT)
        self._render()
        self.ask_button.SetLabel("&Stop")

        def worker():
            try:
                answer = ask.ask_question(
                    self.book, self.settings, question, pages,
                    history=history, cancel_check=cancel.is_set)
            except api_client.ApiError as error:
                wx.CallAfter(self._show_result, request_id, question,
                             None, str(error))
            except Exception as error:
                wx.CallAfter(self._show_result, request_id, question,
                             None, "Unexpected error: %s" % error)
            else:
                wx.CallAfter(self._show_result, request_id, question,
                             answer, None)

        threading.Thread(target=worker, daemon=True).start()

    def on_stop(self):
        if not self._busy:
            return
        self._abandon_request()
        self.ask_button.SetLabel("&Ask")
        if self.pending is not None:
            self.pending = (self.pending[0], ask.STOPPED_TEXT)
        self._render()
        self.question.SetFocus()

    def _show_result(self, request_id, question, answer, error):
        if not self:
            return
        if request_id != self._request_id:
            return  # stopped or superseded: this reply is no longer wanted
        self._busy = False
        self.ask_button.SetLabel("&Ask")
        if error:
            self.pending = (question, "This question could not be "
                                      "answered. %s" % error)
            self._render()
            wx.MessageBox(error, "Ask about this page",
                          wx.OK | wx.ICON_ERROR, self)
            return
        self.history.append((question, answer))
        self.pending = None
        self.question.SetValue("")
        self._render(focus_answers=True)

    # ----- closing ---------------------------------------------------------

    def on_copy(self, event):
        if not self.history:
            return
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(
                wx.TextDataObject(self.history[-1][1]))
            wx.TheClipboard.Close()

    def on_close_button(self, event):
        self._abandon_request()
        self.EndModal(wx.ID_CANCEL)
