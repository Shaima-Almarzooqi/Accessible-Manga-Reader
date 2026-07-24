"""Reader window with three display modes:

  book:  the entire processed book as one continuous document (caret
         position remembered between sessions).
  page:  one page at a time.
  panel: one panel at a time -- the finest-grained way to read, matching
         the pacing of sighted panel-by-panel reading.

In page and panel modes the first line of the text area is a position
header ("Page 3 of 20" or "Page 3 of 20, panel 2 of 6"), the caret
lands on it after every move so reading continues naturally, and
PageDown / PageUp move to the next / previous unit. Reader controls
(Previous, Next, Go to page, Save as text, Close) sit below the text
for point-and-click or Tab access, and everything is also in the menus.

Keyboard reference (these belong to this window; the library's own
Alt+R and Alt+P do not reach in here):
  PageDown / PageUp             next / previous page or panel (page and
                                panel modes)
  Ctrl+PageDown / Ctrl+PageUp   next / previous page (all modes)
  Alt+P / Alt+N                 previous / next (the reader's buttons)
  Alt+G or Ctrl+G               go to a specific page
  Ctrl+F                        find text (book mode)
  Ctrl+L                        show or hide panel labels
  Ctrl+E                        save the whole book as a .txt file
  Ctrl+H                        open the HTML view window
  Ctrl+Shift+E                  save as an HTML file
  Alt+C or Escape               close the reader (position remembered)
"""

import os
import re
import webbrowser

import wx

from core import config, html_export, prompts

from .ask_dialog import AskDialog
from .html_view import show_html_view
from .processing_dialog import ProcessingDialog
from .reprocess_dialog import ReprocessDialog, SCOPE_WHOLE_BOOK

from . import keys as keyhelp

PAGE_MARKER_RE = re.compile(r"^=== Page (\d+) of \d+ ===", re.MULTILINE)

VIEW_BOOK = "book"
VIEW_PAGE = "page"
VIEW_PANEL = "panel"


class ReaderFrame(wx.Frame):
    def __init__(self, parent, book, settings):
        super().__init__(
            parent,
            title="%s - %s" % (book.title or "Book", config.APP_NAME),
            size=(900, 700))
        self.book = book
        self.settings = settings
        self.view = settings.get("reader_view", VIEW_BOOK)
        if self.view not in (VIEW_BOOK, VIEW_PAGE, VIEW_PANEL):
            self.view = VIEW_BOOK
        self.show_labels = bool(settings.get("show_panel_labels", True))
        self.raw_full_text = book.full_text()

        # Panel units per page, computed once.
        self.page_panels = {
            n: prompts.split_panels(book.scripts.get(n, "")) or
               ["(This page has not been processed yet.)"]
            for n in range(1, book.page_count + 1)
        }
        self.current_page = min(max(1, book.last_page),
                                max(1, book.page_count))
        self.current_panel = 0

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.text = wx.TextCtrl(
            panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        sizer.Add(self.text, 1, wx.EXPAND)

        controls = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in [
                ("&Previous", self.on_previous),
                ("&Next", self.on_next),
                ("&Go to page...", self.on_go_to_page),
                # No Alt mnemonic here on purpose: Ctrl+E (in the Book
                # menu) is the single shortcut for saving.
                ("Save as text...", self.on_export),
                ("&Ask...", self.on_ask_page),
                ("&HTML view", self.on_html_view),
                ("&Close", lambda e: self.Close())]:
            button = wx.Button(panel, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            controls.Add(button, 0, wx.RIGHT, 6)
        sizer.Add(controls, 0, wx.ALL, 6)

        panel.SetSizer(sizer)

        self._rebuild_display_text()

        self._build_menu()
        self.text.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.Bind(wx.EVT_CLOSE, self.on_close)

        self._render(initial=True)
        self.text.SetFocus()

    # ----- menu ---------------------------------------------------------

    def _build_menu(self):
        menubar = wx.MenuBar()
        nav = wx.Menu()
        self.Bind(wx.EVT_MENU, self.on_next,
                  nav.Append(wx.ID_ANY, "&Next\tCtrl+PageDown"))
        self.Bind(wx.EVT_MENU, self.on_previous,
                  nav.Append(wx.ID_ANY, "&Previous\tCtrl+PageUp"))
        self.Bind(wx.EVT_MENU, self.on_go_to_page,
                  nav.Append(wx.ID_ANY, "&Go to page...\tCtrl+G"))
        self.Bind(wx.EVT_MENU, self.on_find,
                  nav.Append(wx.ID_ANY, "&Find...\tCtrl+F"))
        menubar.Append(nav, "&Navigate")

        view = wx.Menu()
        self.view_items = {}
        for mode, label in [
                (VIEW_BOOK, "Entire &book"),
                (VIEW_PAGE, "One &page at a time"),
                (VIEW_PANEL, "One pa&nel at a time")]:
            item = view.AppendRadioItem(wx.ID_ANY, label)
            self.view_items[mode] = item
            self.Bind(wx.EVT_MENU,
                      lambda e, m=mode: self.set_view(m), item)
        self.view_items[self.view].Check()
        view.AppendSeparator()
        self.labels_item = view.AppendCheckItem(
            wx.ID_ANY, "Show panel &labels\tCtrl+L",
            "Show Panel N and position markers in the text; off reads "
            "as a continuous narrative")
        self.labels_item.Check(self.show_labels)
        self.Bind(wx.EVT_MENU, self.on_toggle_labels, self.labels_item)
        self.Bind(wx.EVT_MENU, self.on_ask_page, view.Append(
            wx.ID_ANY, "Ask about this &page...\tCtrl+Q",
            "Ask the AI a question about the current page; it looks at "
            "the page image again to answer"))
        self.Bind(wx.EVT_MENU, self.on_html_view, view.Append(
            wx.ID_ANY, "Open &HTML view\tCtrl+H",
            "Open the book in an HTML window with pages and panels as "
            "headings, for browse-mode navigation"))
        menubar.Append(view, "&View")

        book_menu = wx.Menu()
        self.Bind(wx.EVT_MENU, self.on_reprocess_pages, book_menu.Append(
            wx.ID_ANY, "&Reprocess pages...\tCtrl+R",
            "Send this page, a range of pages, or the whole book to the "
            "AI again to replace the script"))
        book_menu.AppendSeparator()
        self.Bind(wx.EVT_MENU, self.on_export,
                  book_menu.Append(wx.ID_ANY, "&Save as text file...\tCtrl+E"))
        self.Bind(wx.EVT_MENU, self.on_save_html, book_menu.Append(
            wx.ID_ANY, "Save as &HTML file...\tCtrl+Shift+E"))
        self.Bind(wx.EVT_MENU, lambda e: self.Close(),
                  book_menu.Append(wx.ID_ANY, "&Close reader\tEscape"))
        menubar.Append(book_menu, "&Book")
        self.SetMenuBar(menubar)

    # ----- rendering ---------------------------------------------------------

    def _rebuild_display_text(self):
        text = self.raw_full_text
        if not self.show_labels:
            text = prompts.strip_panel_labels(text)
        self.full_text = text
        self.page_offsets = {}
        for match in PAGE_MARKER_RE.finditer(text):
            self.page_offsets[int(match.group(1))] = match.start()

    def _panel_body(self, panel):
        return panel if self.show_labels else prompts.strip_panel_labels(panel)

    def on_toggle_labels(self, event):
        # Reached from the menu item and from Ctrl+L. The accelerator
        # does not reliably toggle a check item's state on all
        # platforms, so flip our own flag and push it back to the item;
        # this is a no-op difference for ordinary menu clicks.
        self.show_labels = not self.show_labels
        self.labels_item.Check(self.show_labels)
        self.settings["show_panel_labels"] = self.show_labels
        config.save_settings(self.settings)
        if self.view == VIEW_BOOK:
            self.current_page = self._page_at_caret()
        self._rebuild_display_text()
        self._render()
        self.text.SetFocus()

    def _panel_count(self, page):
        return len(self.page_panels.get(page, [])) or 1

    def _position_header(self):
        if self.view == VIEW_PAGE:
            return "Page %d of %d" % (self.current_page, self.book.page_count)
        panels = self.page_panels[self.current_page]
        header = "Page %d of %d, panel %d of %d" % (
            self.current_page, self.book.page_count,
            self.current_panel + 1, self._panel_count(self.current_page))
        position = prompts.panel_position(panels[self.current_panel])
        if position:
            header += ", " + position
        return header

    def _render(self, initial=False):
        if self.view == VIEW_BOOK:
            self.text.SetValue(self.full_text)
            offset = self.page_offsets.get(self.current_page, 0)
            if initial:
                offset = min(self.book.last_position, len(self.full_text))
            self.text.SetInsertionPoint(offset)
            self.text.ShowPosition(offset)
            self.SetTitle("%s - %s"
                          % (self.book.title or "Book", config.APP_NAME))
            return
        panels = self.page_panels[self.current_page]
        self.current_panel = min(self.current_panel, len(panels) - 1)
        if self.view == VIEW_PAGE:
            body = "\n".join(self._panel_body(p) for p in panels)
        else:
            body = self._panel_body(panels[self.current_panel])
        header = self._position_header()
        self.text.SetValue(header + "\n\n" + body)
        self.text.SetInsertionPoint(0)
        self.SetTitle("%s (%s) - %s"
                      % (self.book.title or "Book", header,
                         config.APP_NAME))

    def set_view(self, mode):
        if mode == self.view:
            return
        if self.view == VIEW_BOOK:
            # Carry the page under the caret into the new mode.
            self.current_page = self._page_at_caret()
        self.view = mode
        self.current_panel = 0
        self.view_items[mode].Check()
        self.settings["reader_view"] = mode
        self._render()
        self.text.SetFocus()

    # ----- navigation ------------------------------------------------------

    def _page_at_caret(self):
        position = self.text.GetInsertionPoint()
        current = 1
        for number in sorted(self.page_offsets):
            if self.page_offsets[number] <= position:
                current = number
            else:
                break
        return current

    def _go_page(self, number, panel_index=0):
        if not 1 <= number <= self.book.page_count:
            wx.Bell()
            return
        self.current_page = number
        self.current_panel = panel_index
        self._render()

    def on_next(self, event):
        if self.view == VIEW_PANEL:
            if self.current_panel + 1 < self._panel_count(self.current_page):
                self.current_panel += 1
                self._render()
            else:
                self._go_page(self.current_page + 1)
        elif self.view == VIEW_PAGE:
            self._go_page(self.current_page + 1)
        else:
            self._go_page(self._page_at_caret() + 1)

    def on_previous(self, event):
        if self.view == VIEW_PANEL:
            if self.current_panel > 0:
                self.current_panel -= 1
                self._render()
            elif self.current_page > 1:
                previous = self.current_page - 1
                self._go_page(previous, self._panel_count(previous) - 1)
            else:
                wx.Bell()
        elif self.view == VIEW_PAGE:
            self._go_page(self.current_page - 1)
        else:
            current = self._page_at_caret()
            position = self.text.GetInsertionPoint()
            if position <= self.page_offsets.get(current, 0) and current > 1:
                self._go_page(current - 1)
            else:
                self._go_page(current)

    def _on_char_hook(self, event):
        # The text area needs arrows for reading; buttons must not
        # navigate with them (Tab does that).
        if keyhelp.consume_arrow_navigation(event, wx.Window.FindFocus()):
            return
        event.Skip()

    def _on_key(self, event):
        code = event.GetKeyCode()
        if code == wx.WXK_ESCAPE:
            self.Close()
        elif (code == wx.WXK_PAGEDOWN and self.view != VIEW_BOOK
              and not event.ControlDown()):
            self.on_next(event)
        elif (code == wx.WXK_PAGEUP and self.view != VIEW_BOOK
              and not event.ControlDown()):
            self.on_previous(event)
        else:
            event.Skip()

    def on_go_to_page(self, event):
        dialog = wx.TextEntryDialog(
            self, "Page number (1 to %d):" % self.book.page_count,
            "Go to page")
        if dialog.ShowModal() == wx.ID_OK:
            try:
                number = int(dialog.GetValue().strip())
            except ValueError:
                number = 0
            if 1 <= number <= self.book.page_count:
                if self.view == VIEW_BOOK:
                    offset = self.page_offsets.get(number, 0)
                    self.text.SetInsertionPoint(offset)
                    self.text.ShowPosition(offset)
                else:
                    self._go_page(number)
                self.text.SetFocus()
            else:
                wx.MessageBox("There is no page %s." % dialog.GetValue(),
                              "Go to page", wx.OK | wx.ICON_INFORMATION, self)
        dialog.Destroy()

    def on_find(self, event):
        if self.view != VIEW_BOOK:
            wx.MessageBox(
                "Find searches the whole book, so switch the View menu to "
                "Entire book first.", "Find",
                wx.OK | wx.ICON_INFORMATION, self)
            return
        dialog = wx.TextEntryDialog(self, "Find text:", "Find")
        if dialog.ShowModal() == wx.ID_OK:
            needle = dialog.GetValue()
            if needle:
                start = self.text.GetInsertionPoint() + 1
                index = self.full_text.lower().find(needle.lower(), start)
                if index < 0:
                    index = self.full_text.lower().find(needle.lower())
                if index >= 0:
                    self.text.SetInsertionPoint(index)
                    self.text.ShowPosition(index)
                    self.text.SetSelection(index, index + len(needle))
                else:
                    wx.MessageBox("'%s' was not found." % needle, "Find",
                                  wx.OK | wx.ICON_INFORMATION, self)
        dialog.Destroy()

    # ----- export and close ---------------------------------------------------

    def on_export(self, event):
        default_name = (self.book.title or "book") + ".txt"
        dialog = wx.FileDialog(
            self, "Save the whole book as a text file",
            defaultFile=default_name,
            wildcard="Text files (*.txt)|*.txt",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if dialog.ShowModal() == wx.ID_OK:
            try:
                with open(dialog.GetPath(), "w", encoding="utf-8") as f:
                    f.write(self.full_text)
                wx.MessageBox("Saved successfully.", "Save as text",
                              wx.OK | wx.ICON_INFORMATION, self)
            except OSError as error:
                wx.MessageBox("Saving failed: %s" % error, "Save as text",
                              wx.OK | wx.ICON_ERROR, self)
        dialog.Destroy()

    def on_ask_page(self, event):
        if not self.book.has_page_images():
            wx.MessageBox(
                "Asking needs the original page images, and this book's "
                "images were removed to free space. Delete the book and "
                "import the original file to use Ask.",
                "Ask about this page", wx.OK | wx.ICON_INFORMATION, self)
            return
        if self.view == VIEW_BOOK:
            self.current_page = self._page_at_caret()
        dialog = AskDialog(self, self.book, self.settings,
                           self.current_page)
        dialog.ShowModal()
        dialog.Destroy()
        self.text.SetFocus()

    def on_reprocess_pages(self, event):
        """Send pages to the AI again from inside the reader.

        Offers the page being read, since noticing a bad page while
        reading is the usual reason to want this.
        """
        if not self.book.has_page_images():
            wx.MessageBox(
                "Reprocessing needs the original page images, and this "
                "book's images were removed to free space. Delete the "
                "book and import the original file to reprocess it.",
                "Reprocess pages", wx.OK | wx.ICON_INFORMATION, self)
            return
        if self.view == VIEW_BOOK:
            self.current_page = self._page_at_caret()
        dialog = ReprocessDialog(self, self.book,
                                 current_page=self.current_page)
        proceed = dialog.ShowModal() == wx.ID_OK
        scope, pages = dialog.scope, list(dialog.pages)
        dialog.Destroy()
        if not proceed:
            return
        if scope == SCOPE_WHOLE_BOOK:
            self.book.scripts = {}
            self.book.character_notes = ""
            pages_to_do = None
        else:
            cleared = self.book.clear_pages(pages)
            if not cleared:
                wx.MessageBox(
                    "Those pages have not been processed yet, so there "
                    "is nothing to replace.",
                    "Reprocess pages", wx.OK | wx.ICON_INFORMATION, self)
                return
            pages_to_do = cleared
        self.book.save()
        dialog = ProcessingDialog(self, self.book, self.settings,
                                  pages=pages_to_do)
        dialog.ShowModal()
        dialog.Destroy()
        # The script the reader is showing is now out of date, so
        # rebuild it and put the reader back where it was.
        self._reload_after_reprocess()

    def _reload_after_reprocess(self):
        """Redraw the reader from the book's new scripts, keeping the
        reading position where it was.

        Both the full text and the per-page panel lists are computed
        once when the reader opens, so they have to be rebuilt here or
        the reader would keep showing the old script.
        """
        page = self.current_page
        self.raw_full_text = self.book.full_text()
        self.page_panels = {
            n: prompts.split_panels(self.book.scripts.get(n, "")) or
               ["(This page has not been processed yet.)"]
            for n in range(1, self.book.page_count + 1)
        }
        self._rebuild_display_text()
        if page and 1 <= page <= self.book.page_count:
            self._go_page(page)
        else:
            self._render()
        self.text.SetFocus()

    def _build_html(self):
        return html_export.build_html(
            self.book, show_panel_labels=self.show_labels)

    def on_html_view(self, event):
        html = self._build_html()
        title = "%s - HTML view" % (self.book.title or "Book")
        default_name = (self.book.title or "book") + ".html"
        if show_html_view(self, title, html, default_name):
            return
        # No web view backend on this system: open in the browser.
        path = os.path.join(self.book.workspace, "view.html")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
        except OSError as error:
            wx.MessageBox("Could not create the HTML view: %s" % error,
                          "HTML view", wx.OK | wx.ICON_ERROR, self)
            return
        webbrowser.open("file:///" + path.replace(os.sep, "/"))
        wx.MessageBox(
            "The built-in HTML view is not available on this system, so "
            "the document was opened in your web browser instead.",
            "HTML view", wx.OK | wx.ICON_INFORMATION, self)

    def on_save_html(self, event):
        default_name = (self.book.title or "book") + ".html"
        dialog = wx.FileDialog(
            self, "Save as HTML file", defaultFile=default_name,
            wildcard="HTML files (*.html)|*.html",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if dialog.ShowModal() == wx.ID_OK:
            try:
                with open(dialog.GetPath(), "w", encoding="utf-8") as f:
                    f.write(self._build_html())
                wx.MessageBox("Saved successfully.", "Save as HTML",
                              wx.OK | wx.ICON_INFORMATION, self)
            except OSError as error:
                wx.MessageBox("Saving failed: %s" % error, "Save as HTML",
                              wx.OK | wx.ICON_ERROR, self)
        dialog.Destroy()

    def on_close(self, event):
        if self.view == VIEW_BOOK:
            self.book.last_position = self.text.GetInsertionPoint()
            self.book.last_page = self._page_at_caret()
        else:
            self.book.last_page = self.current_page
            self.book.last_panel = self.current_panel
        self.book.save()
        event.Skip()
