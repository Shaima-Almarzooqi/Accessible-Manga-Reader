"""Main window: the library.

A list of imported books with their processing status, plus commands to
import new content (CBZ/ZIP archive, PDF, folder of images, or a
hand-picked batch of image files), process/resume, read, and delete.
"""

import os
import threading
import webbrowser

import wx

from core import config, extract, library, updates
from .html_view import show_html_view
from .processing_dialog import ProcessingDialog
from .reader_frame import ReaderFrame
from .settings_dialog import SettingsDialog
from . import keys as keyhelp
from . import manual

PROJECT_URL = "https://github.com/Shaima-Almarzooqi/Accessible-Manga-Reader"
ISSUES_URL = PROJECT_URL + "/issues"
CONTACT_EMAIL = "sshaima004@gmail.com"


class MainFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title=config.APP_NAME, size=(760, 520))
        self.settings = config.load_settings()
        self.books = []

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        list_label = wx.StaticText(panel, label="&Library:")
        sizer.Add(list_label, 0, wx.LEFT | wx.TOP, 8)
        self.book_list = wx.ListBox(panel, style=wx.LB_EXTENDED)
        self.book_list.Bind(wx.EVT_LISTBOX_DCLICK, self.on_read)
        self.book_list.Bind(wx.EVT_KEY_DOWN, self._on_list_key)
        # Enter on a ListBox is often swallowed by the frame's default
        # button handling before EVT_KEY_DOWN sees it, so also catch it
        # at the frame level via a char hook (which runs first) and act
        # only when the list has focus.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.book_list.Bind(wx.EVT_CONTEXT_MENU, self.on_context_menu)
        sizer.Add(self.book_list, 1, wx.EXPAND | wx.ALL, 8)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in [
                ("&Read", self.on_read),
                ("&Process", self.on_process)]:
            button = wx.Button(panel, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            buttons.Add(button, 0, wx.RIGHT, 6)
        sizer.Add(buttons, 0, wx.LEFT | wx.BOTTOM, 8)

        panel.SetSizer(sizer)
        self._build_menu()
        self.refresh_books()
        self.book_list.SetFocus()

        if not self._active_api_keys():
            wx.CallAfter(self._first_run_notice)

        if self.settings.get("check_updates_on_start", True):
            threading.Thread(target=self._check_updates_worker,
                             daemon=True).start()

    # ----- menu ------------------------------------------------------------

    def _build_menu(self):
        menubar = wx.MenuBar()

        file_menu = wx.Menu()
        self.Bind(wx.EVT_MENU, self.on_import_archive, file_menu.Append(
            wx.ID_ANY, "Import &archive or PDF...\tCtrl+O",
            "Import a CBZ, ZIP, or PDF file"))
        self.Bind(wx.EVT_MENU, self.on_import_images, file_menu.Append(
            wx.ID_ANY, "Import &image files...\tCtrl+I",
            "Import a batch of image files as one book"))
        self.Bind(wx.EVT_MENU, self.on_import_folder, file_menu.Append(
            wx.ID_ANY, "Import &folder of images...\tCtrl+Shift+I",
            "Import all images inside a folder as one book"))
        file_menu.AppendSeparator()
        self.Bind(wx.EVT_MENU, self.on_settings, file_menu.Append(
            wx.ID_ANY, "&Settings...\tAlt+S"))
        file_menu.AppendSeparator()
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), file_menu.Append(
            wx.ID_EXIT, "E&xit\tAlt+F4"))
        menubar.Append(file_menu, "&File")

        book_menu = wx.Menu()
        self.Bind(wx.EVT_MENU, self.on_read, book_menu.Append(
            wx.ID_ANY, "&Read\tAlt+R"))
        self.Bind(wx.EVT_MENU, self.on_process, book_menu.Append(
            wx.ID_ANY, "&Process or resume\tAlt+P"))
        self.Bind(wx.EVT_MENU, self.on_instructions, book_menu.Append(
            wx.ID_ANY, "AI &instructions for this book...\tCtrl+T",
            "Give the AI extra guidance, like character names and "
            "descriptions"))
        self.Bind(wx.EVT_MENU, self.on_reprocess, book_menu.Append(
            wx.ID_ANY, "Reprocess entire boo&k...",
            "Clear the processed pages and process the whole book again, "
            "for example after changing AI instructions or verbosity"))
        self.Bind(wx.EVT_MENU, self.on_free_space, book_menu.Append(
            wx.ID_ANY, "&Free up space (remove page images)...",
            "Delete the stored page images of a fully processed book; "
            "reading is unaffected"))
        self.Bind(wx.EVT_MENU, self.on_rename, book_menu.Append(
            wx.ID_ANY, "Re&name...\tF2"))
        self.Bind(wx.EVT_MENU, self.on_delete, book_menu.Append(
            wx.ID_ANY, "&Delete...\tDelete"))
        menubar.Append(book_menu, "&Book")

        help_menu = wx.Menu()
        self.Bind(wx.EVT_MENU, self.on_manual, help_menu.Append(
            wx.ID_ANY, "&User manual\tF1",
            "A step-by-step guide to setting up and using the app"))
        self.Bind(wx.EVT_MENU, self.on_visit_project, help_menu.Append(
            wx.ID_ANY, "&Visit project page on GitHub",
            "Open the project's page in your web browser"))
        self.Bind(wx.EVT_MENU, self.on_report_problem, help_menu.Append(
            wx.ID_ANY, "&Report a problem",
            "Open the page for reporting an issue or suggestion"))
        self.Bind(wx.EVT_MENU, self.on_contact, help_menu.Append(
            wx.ID_ANY, "&Contact developer by email...",
            "Show the developer's email address"))
        help_menu.AppendSeparator()
        self.Bind(wx.EVT_MENU, self.on_about, help_menu.Append(
            wx.ID_ABOUT, "&About %s" % config.APP_NAME))
        menubar.Append(help_menu, "&Help")

        self.SetMenuBar(menubar)

    def _active_api_keys(self):
        provider = self.settings["provider"]
        keys = self.settings.get("%s_api_keys" % provider, [])
        if (not keys and provider == "custom"
                and config.is_local_endpoint(
                    self.settings.get("custom_base_url"))):
            return ["local"]  # local servers need no key
        return keys

    def _first_run_notice(self):
        wx.MessageBox(
            "Welcome to Accessible Manga Reader. Before processing a "
            "book, open "
            "Settings from the File menu and enter an API key. Gemini is "
            "the default provider: you can get a free Gemini API key at "
            "aistudio.google.com with no credit card required.",
            "Welcome", wx.OK | wx.ICON_INFORMATION, self)

    # ----- library list ------------------------------------------------------

    def refresh_books(self, select_book=None):
        self.books = library.list_books()
        items = []
        for book in self.books:
            done = book.processed_count()
            if book.page_count == 0:
                status = "no pages"
            elif book.is_complete():
                status = "ready to read, %d pages" % book.page_count
            else:
                status = "%d of %d pages processed" % (done, book.page_count)
            items.append("%s (%s)" % (book.title or "Untitled", status))
        self.book_list.Set(items)
        if self.books:
            index = 0
            if select_book:
                for i, book in enumerate(self.books):
                    if book.workspace == select_book.workspace:
                        index = i
                        break
            self.book_list.SetSelection(index)

    def _selected_books(self):
        return [self.books[i] for i in self.book_list.GetSelections()
                if i < len(self.books)]

    def _selected_book(self):
        """Exactly one selected book, or None with an explanation."""
        selected = self._selected_books()
        if not selected:
            wx.MessageBox("Select a book in the library first.",
                          config.APP_NAME, wx.OK | wx.ICON_INFORMATION, self)
            return None
        if len(selected) > 1:
            wx.MessageBox(
                "Several items are selected. Select a single one for "
                "this action.", config.APP_NAME,
                wx.OK | wx.ICON_INFORMATION, self)
            return None
        return selected[0]

    def _on_char_hook(self, event):
        focus = wx.Window.FindFocus()
        code = event.GetKeyCode()

        # Char hook events propagate up the window hierarchy, and the
        # reader and the dialogs are children of this frame, so their
        # key presses arrive here too. These shortcuts belong to the
        # main window alone: if the key came from another top-level
        # window, pass it straight back so that window's own shortcuts
        # (Alt+P for Previous in the reader, for instance) still work.
        if wx.GetTopLevelParent(focus) is not self:
            event.Skip()
            return

        # Window-wide command shortcuts for the library. These are
        # handled here rather than left to the buttons' Alt mnemonics so
        # that they work wherever focus happens to be in this window,
        # not only on the button itself.
        if event.AltDown() and not (event.ControlDown() or event.ShiftDown()):
            if code == ord("R"):
                self.on_read(event)
                return
            if code == ord("P"):
                self.on_process(event)
                return
        if (code == ord("P") and event.ControlDown()
                and not (event.AltDown() or event.ShiftDown())):
            self.on_process(event)
            return

        if (code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
                and focus is self.book_list
                and self.book_list.GetSelections()):
            self.on_read(event)
            return
        if focus is self.book_list:
            # Up and Down move within the list and stop at the ends;
            # Left and Right do nothing.
            if keyhelp.consume_list_arrow(event, self.book_list):
                return
            event.Skip()
            return
        if keyhelp.consume_arrow_navigation(event, focus):
            return  # Tab moves between controls; arrows do not
        event.Skip()

    def _on_list_key(self, event):
        code = event.GetKeyCode()
        if code == ord("A") and event.ControlDown():
            for i in range(self.book_list.GetCount()):
                self.book_list.SetSelection(i)
        elif code == wx.WXK_DELETE:
            self.on_delete(event)
        elif code == wx.WXK_F2:
            self.on_rename(event)
        else:
            event.Skip()

    # ----- importing -----------------------------------------------------------

    def on_import_archive(self, event):
        dialog = wx.FileDialog(
            self, "Import archive or PDF",
            wildcard=("Manga files (*.cbz;*.zip;*.pdf)|*.cbz;*.zip;*.pdf|"
                      "All files (*.*)|*.*"),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dialog.ShowModal() == wx.ID_OK:
            path = dialog.GetPath()
            title = os.path.splitext(os.path.basename(path))[0]
            kind = "pdf" if path.lower().endswith(".pdf") else "book"
            self._import(path, path, title, kind)
        dialog.Destroy()

    def on_import_images(self, event):
        dialog = wx.FileDialog(
            self, "Import image files (select all pages of the book)",
            wildcard=("Images (*.jpg;*.jpeg;*.png;*.webp;*.bmp;*.gif)|"
                      "*.jpg;*.jpeg;*.png;*.webp;*.bmp;*.gif|"
                      "All files (*.*)|*.*"),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE)
        if dialog.ShowModal() == wx.ID_OK:
            paths = dialog.GetPaths()
            if paths:
                folder = os.path.dirname(paths[0])
                title = os.path.basename(folder) or "Image batch"
                source_description = "|".join(sorted(paths))
                self._import(paths, source_description, title, "images")
        dialog.Destroy()

    def on_import_folder(self, event):
        dialog = wx.DirDialog(self, "Import a folder of images")
        if dialog.ShowModal() == wx.ID_OK:
            path = dialog.GetPath()
            title = os.path.basename(path.rstrip("\\/")) or "Folder"
            self._import(path, path, title, "folder")
        dialog.Destroy()

    def _import(self, source, source_description, title, kind="book"):
        book_id = extract.book_id_for_source(source_description)
        book = library.create_book(book_id, title, source_description, kind)
        if book.detect_page_count() > 0:
            book.save()
            self.refresh_books(select_book=book)
            wx.MessageBox(
                "This book is already in your library, so the existing "
                "copy was selected.", "Already imported",
                wx.OK | wx.ICON_INFORMATION, self)
            return

        progress = wx.ProgressDialog(
            "Importing", "Importing pages...", maximum=100, parent=self,
            style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE)
        done_event = threading.Event()
        state = {"error": "", "count": 0, "done": 0, "total": 1}

        def on_page(done, total):
            state["done"], state["total"] = done, total

        def worker():
            try:
                state["count"] = extract.extract_source(
                    source, book.workspace,
                    max_dim=int(self.settings["image_max_dimension"]),
                    quality=int(self.settings["image_jpeg_quality"]),
                    progress=on_page)
            except Exception as error:
                state["error"] = str(error)
            done_event.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        while not done_event.is_set():
            wx.MilliSleep(100)
            total = max(1, state["total"])
            progress.Update(
                min(99, int(state["done"] * 100 / total)),
                "Importing page %d of %d..." % (state["done"], total))
            wx.GetApp().Yield()
        progress.Update(100)
        progress.Destroy()

        if state["error"]:
            wx.MessageBox("Import failed: %s" % state["error"],
                          "Import", wx.OK | wx.ICON_ERROR, self)
            return

        book.detect_page_count()
        book.save()
        self.refresh_books(select_book=book)
        answer = wx.MessageBox(
            "Imported %d pages. Process the book now? You will be able "
            "to give the AI optional instructions first, like character "
            "names. Processing may take a while; you can cancel and "
            "resume at any point." % state["count"],
            "Import complete", wx.YES_NO | wx.ICON_QUESTION, self)
        if answer == wx.YES:
            self.on_process(None)

    # ----- book actions ---------------------------------------------------------

    def on_process(self, event):
        book = self._selected_book()
        if not book:
            return
        if not self._active_api_keys():
            wx.MessageBox(
                "Enter an API key in Settings first (File menu, then "
                "Settings, or Alt+S). Gemini keys are free at "
                "aistudio.google.com.",
                "API key required", wx.OK | wx.ICON_INFORMATION, self)
            return
        if book.is_complete():
            wx.MessageBox(
                "This book is already fully processed. To apply new AI "
                "instructions or a new verbosity level to it, use "
                "Reprocess entire book in the Book menu.",
                config.APP_NAME, wx.OK | wx.ICON_INFORMATION, self)
            return
        if not book.has_page_images():
            wx.MessageBox(
                "'%s' has unprocessed pages but its page images were "
                "removed to free space. Delete the book and import the "
                "original file to continue." % book.title,
                config.APP_NAME, wx.OK | wx.ICON_INFORMATION, self)
            return
        if (book.processed_count() == 0
                and self.settings.get(
                    "ask_instructions_before_processing", True)):
            # Fresh run: instructions only take effect during processing,
            # so this is the moment to collect them. OK (even with an
            # empty box) starts processing; Cancel aborts. The dialog can
            # be turned off in Settings; instructions then remain
            # reachable from the Book menu.
            instructions = InstructionsDialog(self, book, before_processing=True)
            proceed = instructions.ShowModal() == wx.ID_OK
            if proceed:
                book.user_instructions = instructions.instructions
                book.save()
            instructions.Destroy()
            if not proceed:
                return
        dialog = ProcessingDialog(self, book, self.settings)
        dialog.ShowModal()
        dialog.Destroy()
        self.refresh_books(select_book=book)

    def on_free_space(self, event):
        book = self._selected_book()
        if not book:
            return
        if not book.has_page_images():
            wx.MessageBox(
                "This book's page images have already been removed.",
                "Free up space", wx.OK | wx.ICON_INFORMATION, self)
            return
        if not book.is_complete():
            wx.MessageBox(
                "'%s' is not fully processed yet. The page images are "
                "needed to finish processing, so finish (or delete the "
                "book) before removing them." % book.title,
                "Free up space", wx.OK | wx.ICON_INFORMATION, self)
            return
        size_mb = book.page_images_size() / (1024.0 * 1024.0)
        answer = wx.MessageBox(
            "Remove the stored page images of '%s' to free about %.1f "
            "MB? Reading is unaffected -- the text is kept. Processing "
            "it again later (for example Reprocess after changing "
            "settings) would require importing the original file again."
            % (book.title, size_mb),
            "Free up space", wx.YES_NO | wx.ICON_QUESTION, self)
        if answer == wx.YES:
            book.delete_page_images()
            wx.MessageBox("Removed %.1f MB." % size_mb, "Free up space",
                          wx.OK | wx.ICON_INFORMATION, self)

    def on_reprocess(self, event):
        book = self._selected_book()
        if not book:
            return
        if not book.has_page_images():
            wx.MessageBox(
                "'%s' has no stored page images (they were removed to "
                "free space), so it cannot be processed again. Delete "
                "the book and import the original file to reprocess."
                % book.title,
                "Reprocess entire book", wx.OK | wx.ICON_INFORMATION, self)
            return
        if book.processed_count() == 0:
            self.on_process(event)
            return
        answer = wx.MessageBox(
            "Reprocess '%s' from the beginning? This clears all %d "
            "processed pages and the AI's character memory for this "
            "book, then processes every page again -- useful after "
            "changing AI instructions or verbosity. The pages will be "
            "sent to the AI again, which uses your API quota. Continue?"
            % (book.title, book.processed_count()),
            "Reprocess entire book", wx.YES_NO | wx.ICON_WARNING, self)
        if answer != wx.YES:
            return
        book.scripts = {}
        book.character_notes = ""
        book.save()
        self.refresh_books(select_book=book)
        self.on_process(event)

    def on_read(self, event):
        book = self._selected_book()
        if not book:
            return
        done = book.processed_count()
        if done == 0:
            answer = wx.MessageBox(
                "'%s' has not been processed yet, so there is nothing "
                "to read. Process it now?" % book.title,
                "Not processed yet", wx.YES_NO | wx.ICON_QUESTION, self)
            if answer == wx.YES:
                self.on_process(event)
            return
        if not book.is_complete():
            answer = wx.MessageBox(
                "'%s' has %d of %d pages processed. Read it now? Choose "
                "No to resume processing first, or Cancel to do "
                "nothing." % (book.title, done, book.page_count),
                "Partially processed",
                wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION, self)
            if answer == wx.NO:
                self.on_process(event)
                return
            if answer != wx.YES:
                return
        reader = ReaderFrame(self, book, self.settings)
        reader.Show()

    def on_instructions(self, event):
        # Returns wx.ID_OK for Save, wx.ID_APPLY for Save and reprocess.
        book = self._selected_book()
        if not book:
            return
        dialog = InstructionsDialog(self, book)
        result = dialog.ShowModal()
        if result in (wx.ID_OK, wx.ID_APPLY):
            book.user_instructions = dialog.instructions
            book.save()
        dialog.Destroy()
        if result == wx.ID_APPLY:
            self.on_reprocess(event)

    def on_rename(self, event):
        book = self._selected_book()
        if not book:
            return
        dialog = wx.TextEntryDialog(self, "New title:", "Rename book",
                                    value=book.title)
        if dialog.ShowModal() == wx.ID_OK:
            title = dialog.GetValue().strip()
            if title:
                book.title = title
                book.save()
                self.refresh_books(select_book=book)
        dialog.Destroy()

    def on_delete(self, event):
        selected = self._selected_books()
        if not selected:
            wx.MessageBox("Select at least one item to remove.",
                          config.APP_NAME, wx.OK | wx.ICON_INFORMATION, self)
            return
        if len(selected) > 1:
            answer = wx.MessageBox(
                "Remove these %d items and all their processed pages "
                "from the library? The original files on disk are not "
                "affected." % len(selected),
                "Remove from library", wx.YES_NO | wx.ICON_WARNING, self)
            if answer == wx.YES:
                for book in selected:
                    library.delete_book(book)
                self.refresh_books()
            return
        book = selected[0]
        kind_text = {
            "images": ("Remove the imported images '%s' and their "
                       "processed pages from the library? The original "
                       "image files on disk are not affected."),
            "folder": ("Remove the imported folder '%s' and its processed "
                       "pages from the library? The original folder on "
                       "disk is not affected."),
        }.get(book.source_kind,
              "Delete the book '%s' and all its processed pages from the "
              "library? The original file on disk is not affected.")
        answer = wx.MessageBox(
            kind_text % book.title,
            "Remove from library", wx.YES_NO | wx.ICON_WARNING, self)
        if answer == wx.YES:
            library.delete_book(book)
            self.refresh_books()

    def on_settings(self, event):
        dialog = SettingsDialog(self, self.settings)
        if dialog.ShowModal() == wx.ID_OK:
            self.settings = dialog.settings
            config.save_settings(self.settings)
        dialog.Destroy()

    def on_about(self, event):
        wx.MessageBox(
            "%s\nVersion %s\n\n"
            "A manga and comic reader for blind readers. Pages are "
            "described panel by panel by an AI vision model, following "
            "proper manga reading order, with speaker-attributed "
            "dialogue, sound effects, and silent-panel descriptions.\n\n"
            "Processed books are cached on this computer, so each book "
            "only needs to be processed once.\n\n"
            "Free software under the GNU General Public License, "
            "version 3 or later."
            % (config.APP_NAME, config.APP_VERSION),
            "About %s" % config.APP_NAME, wx.OK | wx.ICON_INFORMATION,
            self)

    # ----- help menu ---------------------------------------------------------

    def on_manual(self, event):
        html = manual.manual_html()
        title = "%s - User Manual" % config.APP_NAME
        if show_html_view(self, title, html, "manual.html"):
            return
        # No web view backend on this system: open in the browser.
        path = os.path.join(config.data_dir(), "manual.html")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
        except OSError as error:
            wx.MessageBox("Could not open the manual: %s" % error,
                          "User manual", wx.OK | wx.ICON_ERROR, self)
            return
        webbrowser.open("file:///" + path.replace(os.sep, "/"))
        wx.MessageBox(
            "The built-in view is not available on this system, so the "
            "manual was opened in your web browser instead.",
            "User manual", wx.OK | wx.ICON_INFORMATION, self)

    def on_visit_project(self, event):
        webbrowser.open(PROJECT_URL)

    def on_report_problem(self, event):
        webbrowser.open(ISSUES_URL)

    def on_contact(self, event):
        dialog = ContactDialog(self)
        dialog.ShowModal()
        dialog.Destroy()

    # ----- update notifications ---------------------------------------------

    def _check_updates_worker(self):
        """Runs on a background thread; must never raise."""
        update = updates.check_for_update(
            config.APP_VERSION,
            include_betas=bool(
                self.settings.get("include_beta_updates", True)))
        if update is None:
            return
        if update.version == self.settings.get(
                "dismissed_update_version", ""):
            return
        wx.CallAfter(self._offer_update, update)

    def _offer_update(self, update):
        dialog = UpdateDialog(self, update)
        answer = dialog.ShowModal()
        if dialog.dismissed():
            self.settings["dismissed_update_version"] = update.version
            config.save_settings(self.settings)
        if answer == wx.ID_YES:
            webbrowser.open(update.url)
        dialog.Destroy()


    def on_context_menu(self, event):
        selected = self._selected_books()
        if not selected:
            return
        menu = wx.Menu()
        if len(selected) == 1:
            book = selected[0]
            read_item = menu.Append(wx.ID_ANY, "&Read")
            self.Bind(wx.EVT_MENU, self.on_read, read_item)
            read_item.Enable(book.processed_count() > 0)
            if not book.is_complete():
                label = ("&Resume processing"
                         if book.processed_count() > 0 else "&Process")
                self.Bind(wx.EVT_MENU, self.on_process,
                          menu.Append(wx.ID_ANY, label))
            self.Bind(wx.EVT_MENU, self.on_instructions,
                      menu.Append(wx.ID_ANY, "AI &instructions..."))
            self.Bind(wx.EVT_MENU, self.on_reprocess,
                      menu.Append(wx.ID_ANY, "Reprocess entire boo&k..."))
            self.Bind(wx.EVT_MENU, self.on_rename,
                      menu.Append(wx.ID_ANY, "Re&name..."))
            self.Bind(wx.EVT_MENU, self.on_delete,
                      menu.Append(wx.ID_ANY, "&Delete..."))
        else:
            self.Bind(wx.EVT_MENU, self.on_delete, menu.Append(
                wx.ID_ANY, "&Delete these %d items..." % len(selected)))
        self.book_list.PopupMenu(menu)
        menu.Destroy()


class ContactDialog(wx.Dialog):
    """Shows the developer's email address as selectable text with a
    button to copy it and a button to open the default email program.
    Focus starts on the address so a screen reader reads it immediately;
    Escape closes.
    """

    def __init__(self, parent):
        super().__init__(parent, title="Contact developer by email")
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.address = wx.TextCtrl(
            self, value="Email: %s" % CONTACT_EMAIL,
            style=wx.TE_READONLY)
        sizer.Add(self.address, 0, wx.EXPAND | wx.ALL, 8)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        copy_button = wx.Button(self, label="&Copy email address")
        copy_button.Bind(wx.EVT_BUTTON, self.on_copy)
        buttons.Add(copy_button, 0, wx.RIGHT, 6)
        mail_button = wx.Button(self, label="&Open in email program")
        mail_button.Bind(wx.EVT_BUTTON, self.on_mail)
        buttons.Add(mail_button, 0, wx.RIGHT, 6)
        close_button = wx.Button(self, wx.ID_CANCEL, "Close")
        buttons.Add(close_button, 0)
        sizer.Add(buttons, 0, wx.ALL, 8)

        self.SetEscapeId(wx.ID_CANCEL)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        self.SetSizerAndFit(sizer)
        self.address.SetFocus()

    def on_char_hook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        if keyhelp.consume_arrow_navigation(event, wx.Window.FindFocus()):
            return
        event.Skip()

    def on_copy(self, event):
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(CONTACT_EMAIL))
            wx.TheClipboard.Close()
            wx.MessageBox("Email address copied.", "Contact developer",
                          wx.OK | wx.ICON_INFORMATION, self)
        else:
            wx.MessageBox("Could not access the clipboard.",
                          "Contact developer", wx.OK | wx.ICON_ERROR, self)

    def on_mail(self, event):
        webbrowser.open("mailto:%s" % CONTACT_EMAIL)


class UpdateDialog(wx.Dialog):
    """Tells the reader a newer version exists and offers the download
    page. Standard modal dialog: Escape closes it (as No), and the
    release notes are in a read-only text area so they can be read and
    reviewed with a screen reader.
    """

    def __init__(self, parent, update):
        super().__init__(parent, title="Update available",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        sizer = wx.BoxSizer(wx.VERTICAL)

        intro = wx.StaticText(self, label=(
            "Version %s of %s is available. You are using version %s."
            % (update.version, config.APP_NAME, config.APP_VERSION)))
        intro.Wrap(520)
        sizer.Add(intro, 0, wx.ALL, 8)

        notes_label = wx.StaticText(self, label="What changed:")
        sizer.Add(notes_label, 0, wx.LEFT, 8)
        self.notes = wx.TextCtrl(
            self, value=update.notes or "(No release notes.)",
            style=wx.TE_MULTILINE | wx.TE_READONLY, size=(540, 200))
        sizer.Add(self.notes, 1, wx.EXPAND | wx.ALL, 8)

        question = wx.StaticText(
            self, label="Open the download page in your web browser?")
        sizer.Add(question, 0, wx.LEFT | wx.BOTTOM, 8)

        self.dismiss_box = wx.CheckBox(
            self, label="&Do not remind me about this version again")
        sizer.Add(self.dismiss_box, 0, wx.LEFT | wx.BOTTOM, 8)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        yes_button = wx.Button(self, wx.ID_YES, "&Yes")
        yes_button.Bind(wx.EVT_BUTTON,
                        lambda e: self.EndModal(wx.ID_YES))
        no_button = wx.Button(self, wx.ID_NO, "&No")
        no_button.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_NO))
        buttons.AddStretchSpacer()
        buttons.Add(yes_button, 0, wx.RIGHT, 6)
        buttons.Add(no_button, 0)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 8)

        yes_button.SetDefault()
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        self.SetSizerAndFit(sizer)
        yes_button.SetFocus()

    def dismissed(self):
        return self.dismiss_box.GetValue()

    def on_char_hook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_NO)
            return
        if keyhelp.consume_arrow_navigation(event, wx.Window.FindFocus()):
            return
        event.Skip()


class InstructionsDialog(wx.Dialog):
    """Reader-provided guidance the AI receives with every batch of this
    book: character names and descriptions, name spellings, tone notes,
    or anything else. Standard multiline editing: Enter inserts a new
    line; Tab to OK (or Alt+O) to save; Escape cancels.
    """

    EXPLANATION = (
        "These instructions are sent to the AI with every batch of "
        "pages for this book. Most useful: character names with brief "
        "descriptions, for example: 'Aiko: short dark hair, school "
        "uniform, the class representative. Kenta: messy hair, always "
        "late.' The AI will use these names from the very first page "
        "instead of guessing. Note: instructions only affect pages "
        "processed from now on. To apply them to an already processed "
        "book, use Save and reprocess (also available as Reprocess "
        "entire book in the Book menu).")

    def __init__(self, parent, book, before_processing=False):
        title = ("AI instructions before processing %s"
                 if before_processing else "AI instructions for %s")
        super().__init__(
            parent,
            title=title % (book.title or "this book"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.instructions = book.user_instructions

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        explanation = wx.StaticText(self, label=self.EXPLANATION)
        explanation.Wrap(520)
        main_sizer.Add(explanation, 0, wx.ALL, 8)

        label = wx.StaticText(self, label="&Instructions for the AI:")
        main_sizer.Add(label, 0, wx.LEFT, 8)
        self.text = wx.TextCtrl(
            self, value=self.instructions,
            style=wx.TE_MULTILINE, size=(540, 200))
        main_sizer.Add(self.text, 1, wx.EXPAND | wx.ALL, 8)

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        ok_label = ("Save and &process" if before_processing else "&Save")
        cancel_label = ("Cancel processing" if before_processing
                        else "Cancel")
        ok_button = wx.Button(self, wx.ID_OK, ok_label)
        cancel_button = wx.Button(self, wx.ID_CANCEL, cancel_label)
        button_sizer.AddStretchSpacer()
        button_sizer.Add(ok_button, 0, wx.RIGHT, 6)
        if not before_processing:
            # Apply the instructions right away: save, then run the
            # normal Reprocess entire book flow with its confirmation.
            reprocess_button = wx.Button(
                self, wx.ID_APPLY, "Save and &reprocess...")
            reprocess_button.Bind(wx.EVT_BUTTON, self.on_reprocess_clicked)
            button_sizer.Add(reprocess_button, 0, wx.RIGHT, 6)
        button_sizer.Add(cancel_button, 0)
        main_sizer.Add(button_sizer, 0, wx.EXPAND | wx.ALL, 8)

        self.SetAffirmativeId(wx.ID_OK)
        self.SetEscapeId(wx.ID_CANCEL)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)

        self.SetSizerAndFit(main_sizer)
        self.text.SetFocus()

    def on_char_hook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        if keyhelp.consume_arrow_navigation(event, wx.Window.FindFocus()):
            return
        event.Skip()

    def on_ok(self, event):
        self.instructions = self.text.GetValue().strip()
        self.EndModal(wx.ID_OK)

    def on_reprocess_clicked(self, event):
        self.instructions = self.text.GetValue().strip()
        self.EndModal(wx.ID_APPLY)
