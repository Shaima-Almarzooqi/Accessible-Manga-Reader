"""Reprocess scope dialog.

Asks which pages to send to the AI again. Opened from the library (Book
menu) and from the reader, where it additionally offers the page being
read.

Screen-reader shape: a radio box, then two page fields. The fields stay
enabled at all times rather than greying out with the radio selection --
a disabled control is skipped by Tab and its value is not announced, so
a reader tabbing through would silently lose the range they had typed.
Instead, typing in a field selects the range option, which is what the
user meant anyway.
"""

import wx

from . import keys as keyhelp

# ShowModal returns one of these.
SCOPE_CANCEL = 0
SCOPE_WHOLE_BOOK = 1
SCOPE_RANGE = 2


class ReprocessDialog(wx.Dialog):
    def __init__(self, parent, book, current_page=None):
        """current_page: 1-based page to offer as "this page", or None
        when opened somewhere without a current page (the library)."""
        super().__init__(parent, title="Reprocess pages")
        self.book = book
        self.current_page = current_page
        self._scope = SCOPE_CANCEL
        self.pages = []

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        intro = wx.StaticText(
            panel,
            label="Choose which pages of '%s' to send to the AI again. "
                  "'%s' has %d pages."
                  % (book.title or "book", book.title or "This book",
                     book.page_count))
        intro.Wrap(460)
        sizer.Add(intro, 0, wx.ALL, 10)

        choices = []
        self._choice_scopes = []
        if current_page:
            choices.append("&This page (page %d)" % current_page)
            self._choice_scopes.append("current")
        choices.append("A page &range")
        self._choice_scopes.append("range")
        choices.append("The &whole book")
        self._choice_scopes.append("whole")

        self.scope_box = wx.RadioBox(
            panel, label="Pages to reprocess", choices=choices,
            majorDimension=1, style=wx.RA_SPECIFY_COLS)
        self.scope_box.Bind(wx.EVT_RADIOBOX, self.on_scope_changed)
        sizer.Add(self.scope_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        range_row = wx.BoxSizer(wx.HORIZONTAL)
        from_label = wx.StaticText(panel, label="&From page:")
        range_row.Add(from_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.from_ctrl = wx.SpinCtrl(
            panel, min=1, max=max(1, book.page_count),
            initial=current_page or 1)
        self.from_ctrl.Bind(wx.EVT_TEXT, self.on_range_typed)
        self.from_ctrl.Bind(wx.EVT_SPINCTRL, self.on_range_typed)
        range_row.Add(self.from_ctrl, 0, wx.RIGHT, 16)
        to_label = wx.StaticText(panel, label="T&o page:")
        range_row.Add(to_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.to_ctrl = wx.SpinCtrl(
            panel, min=1, max=max(1, book.page_count),
            initial=current_page or book.page_count)
        self.to_ctrl.Bind(wx.EVT_TEXT, self.on_range_typed)
        self.to_ctrl.Bind(wx.EVT_SPINCTRL, self.on_range_typed)
        range_row.Add(self.to_ctrl, 0)
        sizer.Add(range_row, 0, wx.ALL, 10)

        note = wx.StaticText(
            panel,
            label="The pages you choose are replaced; the rest of the "
                  "book is left alone.")
        note.Wrap(460)
        sizer.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        buttons = wx.StdDialogButtonSizer()
        ok = wx.Button(panel, wx.ID_OK, "&Reprocess")
        ok.SetDefault()
        buttons.AddButton(ok)
        buttons.AddButton(wx.Button(panel, wx.ID_CANCEL, "Cancel"))
        buttons.Realize()
        sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        ok.Bind(wx.EVT_BUTTON, self.on_ok)

        panel.SetSizer(sizer)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizerAndFit(outer)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.scope_box.SetFocus()

    # ----- helpers ---------------------------------------------------------

    def _selected_scope(self):
        return self._choice_scopes[self.scope_box.GetSelection()]

    def on_scope_changed(self, event):
        event.Skip()

    def on_range_typed(self, event):
        """Typing a page number means the range option, so select it
        rather than making the user go back to the radio box."""
        if self._selected_scope() != "range":
            self.scope_box.SetSelection(self._choice_scopes.index("range"))
        event.Skip()

    # ----- confirm ---------------------------------------------------------

    def on_ok(self, event):
        scope = self._selected_scope()
        if scope == "current":
            self.pages = [self.current_page]
            self._scope = SCOPE_RANGE
            self.EndModal(wx.ID_OK)
            return
        if scope == "whole":
            answer = wx.MessageBox(
                "Reprocess the whole book? This replaces all %d "
                "processed pages."
                % self.book.processed_count(),
                "Reprocess the whole book", wx.YES_NO | wx.ICON_WARNING,
                self)
            if answer != wx.YES:
                return
            self._scope = SCOPE_WHOLE_BOOK
            self.EndModal(wx.ID_OK)
            return

        first = self.from_ctrl.GetValue()
        last = self.to_ctrl.GetValue()
        if first > last:
            # Far friendlier than an error: the user clearly meant this
            # span of pages, so read it the way round they meant.
            first, last = last, first
        if first > self.book.page_count:
            wx.MessageBox(
                "'%s' only has %d pages, so there is no page %d to "
                "reprocess." % (self.book.title or "This book",
                                self.book.page_count, first),
                "Page range", wx.OK | wx.ICON_INFORMATION, self)
            self.from_ctrl.SetFocus()
            return
        last = min(last, self.book.page_count)
        self.pages = list(range(first, last + 1))
        self._scope = SCOPE_RANGE
        self.EndModal(wx.ID_OK)

    @property
    def scope(self):
        return self._scope

    def _on_char_hook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
        elif keyhelp.consume_arrow_navigation(event, wx.Window.FindFocus()):
            return
        else:
            event.Skip()
