"""Editing a series' character bank.

Two dialogs, opened from the Character bank tab in Settings and from
the Book menu: the characters a series holds, and the pictures held
for one of them.

Screen-reader shape: each level is a plain list with buttons beside
it, the same arrangement as the API key list, because a list plus
buttons is reachable by Tab and read out one entry at a time. Nothing
is nested inside anything else on a page.

Every picture is listed by its description rather than its file name.
A reader who cannot see the picture has only that line to judge it by,
so a picture filed under the wrong character can be found and removed.
A file name would tell them nothing.
"""

import os
import shutil

import wx

from core import series

from . import keys as keyhelp


def _describe_character(character):
    """One list line: the name, and how much is known about them."""
    name = character.get("name", "").strip() or "Unnamed"
    pictures = len(character.get("pictures") or [])
    described = bool((character.get("description") or "").strip())
    parts = []
    if described:
        parts.append("described")
    parts.append("%d picture%s" % (pictures, "" if pictures == 1 else "s"))
    return "%s, %s" % (name, ", ".join(parts))


class PicturesDialog(wx.Dialog):
    """The pictures held for one character."""

    def __init__(self, parent, record, character_name):
        super().__init__(parent,
                         title="Pictures of %s" % character_name)
        self.record = record
        self.character_name = character_name

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(
            panel,
            label="&Pictures of %s. The first one is the one sent to "
                  "the AI:" % character_name), 0, wx.ALL, 8)
        self.pictures = wx.ListBox(panel, size=(460, 150),
                                   style=wx.LB_SINGLE)
        sizer.Add(self.pictures, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        for label, handler in (("&Add a picture...", self.on_add),
                               ("Move &up", self.on_up),
                               ("&Remove the selected picture",
                                self.on_remove)):
            button = wx.Button(panel, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            sizer.Add(button, 0, wx.LEFT | wx.TOP, 8)

        buttons = self.CreateStdDialogButtonSizer(wx.OK)
        sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        panel.SetSizer(sizer)
        sizer.SetSizeHints(self)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        self._show(0)

    def _entries(self):
        character = series.find_character(self.record, self.character_name)
        return (character.get("pictures") or []) if character else []

    def _show(self, select=None):
        entries = self._entries()
        self.pictures.Set([series.describe_picture(p) for p in entries])
        if entries and select is not None:
            self.pictures.SetSelection(max(0, min(select, len(entries) - 1)))

    def _selected(self):
        index = self.pictures.GetSelection()
        entries = self._entries()
        if index == wx.NOT_FOUND or index >= len(entries):
            wx.MessageBox("Choose a picture from the list first.",
                          "Pictures", wx.OK | wx.ICON_INFORMATION, self)
            self.pictures.SetFocus()
            return None
        return index

    def on_add(self, event):
        dialog = wx.FileDialog(
            self, "Choose a picture", wildcard="Pictures|*.png;*.jpg;*.jpeg",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            self.pictures.SetFocus()
            return
        chosen = dialog.GetPath()
        dialog.Destroy()

        described = wx.TextEntryDialog(
            self, "Describe this picture in a few words:", "Add a picture")
        pressed = described.ShowModal()
        description = described.GetValue().strip()
        described.Destroy()
        if pressed != wx.ID_OK:
            self.pictures.SetFocus()
            return

        folder = series.pictures_dir(self.record.get("name", ""))
        name = os.path.basename(chosen)
        target = os.path.join(folder, name)
        count = 1
        stem, extension = os.path.splitext(name)
        while os.path.exists(target):
            name = "%s-%d%s" % (stem, count, extension)
            target = os.path.join(folder, name)
            count += 1
        try:
            shutil.copyfile(chosen, target)
        except OSError as error:
            wx.MessageBox("Could not copy that picture: %s" % error,
                          "Pictures", wx.OK | wx.ICON_ERROR, self)
            return
        series.add_picture(self.record, self.character_name, name,
                           description, "added by hand")
        self._show(len(self._entries()) - 1)
        self.pictures.SetFocus()

    def on_up(self, event):
        index = self._selected()
        if index is None:
            return
        entries = self._entries()
        series.promote_picture(self.record, self.character_name,
                               entries[index].get("file"))
        self._show(0)
        self.pictures.SetFocus()

    def on_remove(self, event):
        index = self._selected()
        if index is None:
            return
        entries = self._entries()
        picture = entries[index]
        if wx.MessageBox("Remove %s?" % series.describe_picture(picture),
                         "Remove a picture",
                         wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            self.pictures.SetFocus()
            return
        series.remove_picture(self.record, self.character_name,
                              picture.get("file"))
        self._show(index)
        self.pictures.SetFocus()

    def on_char_hook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_OK)
            return
        if keyhelp.consume_arrow_navigation(event, wx.Window.FindFocus()):
            return
        event.Skip()


class CharactersDialog(wx.Dialog):
    """The characters one series holds."""

    def __init__(self, parent, series_name):
        super().__init__(parent, title="Character bank: %s" % series_name)
        self.record = series.load_series(series_name)

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(
            panel,
            label="&Characters in %s. These are sent to the AI so it "
                  "can tell them apart:" % series_name), 0, wx.ALL, 8)
        self.characters = wx.ListBox(panel, size=(460, 170),
                                     style=wx.LB_SINGLE)
        sizer.Add(self.characters, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        for label, handler in (
                ("&Add a character...", self.on_add),
                ("&Edit the selected character...", self.on_edit),
                ("&Pictures of the selected character...", self.on_pictures),
                ("&Remove the selected character", self.on_remove)):
            button = wx.Button(panel, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            sizer.Add(button, 0, wx.LEFT | wx.TOP, 8)

        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        panel.SetSizer(sizer)
        sizer.SetSizeHints(self)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self._show(0)

    def _show(self, select=None):
        entries = self.record.get("characters", [])
        self.characters.Set([_describe_character(c) for c in entries])
        if entries and select is not None:
            self.characters.SetSelection(
                max(0, min(select, len(entries) - 1)))

    def _selected(self):
        index = self.characters.GetSelection()
        entries = self.record.get("characters", [])
        if index == wx.NOT_FOUND or index >= len(entries):
            wx.MessageBox("Choose a character from the list first.",
                          "Character bank", wx.OK | wx.ICON_INFORMATION,
                          self)
            self.characters.SetFocus()
            return None
        return index

    def _ask(self, title, name="", description=""):
        """Name and description in one dialog."""
        dialog = wx.TextEntryDialog(self, "Name:", title, name)
        pressed = dialog.ShowModal()
        got_name = dialog.GetValue().strip()
        dialog.Destroy()
        if pressed != wx.ID_OK or not got_name:
            return None, None
        dialog = wx.TextEntryDialog(
            self, "Describe %s in a few words (optional):" % got_name,
            title, description)
        pressed = dialog.ShowModal()
        got_description = dialog.GetValue().strip()
        dialog.Destroy()
        if pressed != wx.ID_OK:
            return None, None
        return got_name, got_description

    def on_add(self, event):
        name, description = self._ask("Add a character")
        if not name:
            self.characters.SetFocus()
            return
        if series.find_character(self.record, name) is not None:
            wx.MessageBox("%s is already in this series." % name,
                          "Character bank", wx.OK | wx.ICON_INFORMATION,
                          self)
            self.characters.SetFocus()
            return
        series.set_character(self.record, name, description,
                             chosen_by_reader=True)
        self._show(len(self.record["characters"]) - 1)
        self.characters.SetFocus()

    def on_edit(self, event):
        index = self._selected()
        if index is None:
            return
        character = self.record["characters"][index]
        name, description = self._ask(
            "Edit a character", character.get("name", ""),
            character.get("description", ""))
        if not name:
            self.characters.SetFocus()
            return
        character["name"] = name
        character["description"] = description
        # A name somebody typed is how every later volume will read,
        # so a future book mentioning a fuller one must not undo it.
        character["chosen_by_reader"] = True
        self._show(index)
        self.characters.SetFocus()

    def on_pictures(self, event):
        index = self._selected()
        if index is None:
            return
        name = self.record["characters"][index].get("name", "")
        dialog = PicturesDialog(self, self.record, name)
        dialog.ShowModal()
        dialog.Destroy()
        self._show(index)
        self.characters.SetFocus()

    def on_remove(self, event):
        index = self._selected()
        if index is None:
            return
        character = self.record["characters"][index]
        name = character.get("name", "")
        if wx.MessageBox("Remove %s from this series?" % name,
                         "Remove a character",
                         wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            self.characters.SetFocus()
            return
        series.remove_character(self.record, name)
        self._show(index)
        self.characters.SetFocus()

    def on_ok(self, event):
        try:
            series.save_series(self.record)
        except (OSError, ValueError) as error:
            wx.MessageBox("Could not save: %s" % error, "Character bank",
                          wx.OK | wx.ICON_ERROR, self)
            return
        self.EndModal(wx.ID_OK)

    def on_char_hook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        if keyhelp.consume_arrow_navigation(event, wx.Window.FindFocus()):
            return
        event.Skip()


class SaveToBankDialog(wx.Dialog):
    """Offered when a book finishes: keep its characters for the series.

    One dialog does both confirmations the reader owes -- which series
    this book belongs to, and whether its characters are worth
    keeping -- because two separate prompts after a long run would be
    two interruptions for one decision.
    """

    def __init__(self, parent, book, suggested, found):
        super().__init__(parent, title="Character bank")
        self.book = book
        self.found = found
        self.series_name = suggested

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(
            panel,
            label="Keep these characters for every book in this series:"),
            0, wx.ALL, 8)

        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(panel, label="&Series:"), 0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.name = wx.TextCtrl(panel, value=suggested, size=(280, -1))
        row.Add(self.name, 1, wx.EXPAND)
        sizer.Add(row, 0, wx.EXPAND | wx.ALL, 8)

        sizer.Add(wx.StaticText(panel, label="&Characters:"), 0,
                  wx.LEFT | wx.TOP, 8)
        self.characters = wx.ListBox(
            panel, size=(400, 140), style=wx.LB_SINGLE,
            choices=["%s: %s" % (name, description) if description
                     else name for name, description in found])
        sizer.Add(self.characters, 1, wx.EXPAND | wx.ALL, 8)

        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        panel.SetSizer(sizer)
        sizer.SetSizeHints(self)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        self.name.SetFocus()

    def on_ok(self, event):
        name = self.name.GetValue().strip()
        if not name:
            wx.MessageBox("Enter a series name.", "Character bank",
                          wx.OK | wx.ICON_INFORMATION, self)
            self.name.SetFocus()
            return
        self.series_name = name
        self.EndModal(wx.ID_OK)

    def on_char_hook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        if keyhelp.consume_arrow_navigation(event, wx.Window.FindFocus()):
            return
        event.Skip()


def offer_to_save(parent, book):
    """Ask whether this book's characters should join its series bank.

    Returns True when something was saved. Silent when the book
    learned no characters, since an empty offer is just an
    interruption.
    """
    found = series.notes_from_text(book.character_notes)
    if not found:
        return False
    suggested = (getattr(book, "series", "")
                 or series.series_name_from_title(book.title))
    dialog = SaveToBankDialog(parent, book, suggested, found)
    try:
        if dialog.ShowModal() != wx.ID_OK:
            return False
        name = dialog.series_name
    finally:
        dialog.Destroy()

    record = series.load_series(name)
    record["name"] = name
    series.merge_notes(record, book.character_notes)
    try:
        series.save_series(record)
    except (OSError, ValueError) as error:
        wx.MessageBox("Could not save: %s" % error, "Character bank",
                      wx.OK | wx.ICON_ERROR, parent)
        return False
    if getattr(book, "series", "") != name:
        book.series = name
        book.save()
    return True
