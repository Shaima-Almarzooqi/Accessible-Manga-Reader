"""The Export menu, shared by the reader and the library.

Both windows offer the same formats, so the menu is built once here
rather than twice. Callers pass functions for the book and settings
because the two windows hold them differently: the reader always has one
book open, the library has whichever is selected at the moment the menu
is used.
"""

import os

import wx

from core import export, tts


# Accelerators kept from when these were separate Book menu items, so
# they still work for anyone used to them.
_SHORTCUTS = {".txt": "\tCtrl+E", ".html": "\tCtrl+Shift+E"}

# Mnemonics chosen to be unique within the menu.
_MNEMONICS = {
    ".txt": "&Text file",
    ".html": "&HTML",
    ".epub": "&EPUB book",
    ".docx": "Word &document",
    ".pdf": "&PDF",
}


def save_book_as(parent, book, settings, extension, wildcard, writer, label):
    """Ask where to save, then write the book in one format."""
    if book is None:
        return
    if book.processed_count() == 0:
        wx.MessageBox(
            "This book has no processed pages yet, so there is nothing to "
            "save. Process it first.",
            "Export", wx.OK | wx.ICON_INFORMATION, parent)
        return
    dialog = wx.FileDialog(
        parent, "Save as %s" % label.lower(),
        defaultFile=(book.title or "book") + extension,
        wildcard=wildcard,
        style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
    if dialog.ShowModal() != wx.ID_OK:
        dialog.Destroy()
        return
    path = dialog.GetPath()
    dialog.Destroy()
    if not path.lower().endswith(extension):
        path += extension
    try:
        writer(book, path,
               show_panel_labels=bool(settings.get("show_panel_labels", True)),
               # The book's own language when known: the setting may
               # have changed since it was processed.
               language=(getattr(book, "output_language", "")
                         or settings.get("output_language", "English")))
    except ImportError:
        wx.MessageBox(
            "Saving as %s is not available in this build." % label,
            "Export", wx.OK | wx.ICON_ERROR, parent)
        return
    except Exception as error:
        wx.MessageBox("Could not save: %s" % error,
                      "Export", wx.OK | wx.ICON_ERROR, parent)
        return
    wx.MessageBox("Saved to %s" % os.path.basename(path),
                  "Export", wx.OK | wx.ICON_INFORMATION, parent)


def build_export_menu(frame, get_book, get_settings):
    """A menu with one entry per format, ready to be added as a submenu.

    get_book and get_settings are called when an item is chosen, not
    when the menu is built, so the library always exports whichever book
    is selected at that moment.
    """
    menu = wx.Menu()
    audio_item = None
    for label, extension, wildcard, writer in export.FORMATS:
        text = _MNEMONICS.get(extension, label) + "..."
        text += _SHORTCUTS.get(extension, "")
        item = menu.Append(wx.ID_ANY, text, "Save this book as %s" % label)
        frame.Bind(
            wx.EVT_MENU,
            lambda event, w=writer, e=extension, wc=wildcard, lb=label:
            save_book_as(frame, get_book(), get_settings(), e, wc, w, lb),
            item)
    audio_item = menu.Append(
        wx.ID_ANY, "&Audio (MP3)...",
        "Read this book aloud and save it as an MP3")
    frame.Bind(wx.EVT_MENU,
               lambda event: save_book_as_audio(
                   frame, get_book(), get_settings()),
               audio_item)
    return menu


def save_book_as_audio(parent, book, settings):
    """Ask where to save, then read the book aloud in its own window.

    Unlike the other formats this takes hours, so it never runs inline:
    the window reports progress and can be stopped.
    """
    from . import speech_window
    if book is None:
        return
    if book.processed_count() == 0:
        wx.MessageBox(
            "This book has no processed pages yet, so there is nothing to "
            "read aloud. Process it first.",
            "Save as audio", wx.OK | wx.ICON_INFORMATION, parent)
        return
    from . import audio_dialog
    chooser = audio_dialog.AudioOptionsDialog(parent, book, settings)
    proceed = chooser.ShowModal() == wx.ID_OK
    voice = chooser.chosen_voice()
    engine = chooser.chosen_engine()
    language = chooser.chosen_language()
    model = chooser.chosen_model()
    pages = chooser.chosen_pages()
    say_pages = chooser.says_page_numbers()
    suffix = chooser.range_label()
    chooser.Destroy()
    if not proceed:
        return
    if (engine == tts.ENGINE_GEMINI
            and not [key for key in settings.get("gemini_api_keys", [])
                     if key.strip()]):
        wx.MessageBox(
            "Gemini requires a Gemini API key in Settings before it can "
            "generate audio.",
            "Save as audio", wx.OK | wx.ICON_INFORMATION, parent)
        return
    # Remembered so the next book starts from the same choice.
    settings["tts_engine"] = engine
    settings["say_page_numbers"] = say_pages
    if engine == tts.ENGINE_KOKORO:
        settings["kokoro_language"] = language
        settings["kokoro_voice"] = voice
        remembered = dict(settings.get("kokoro_voice_by_language", {}))
        remembered[language] = voice
        settings["kokoro_voice_by_language"] = remembered
    else:
        settings["tts_voice"] = voice
        settings["tts_model"] = model
    from core import config
    config.save_settings(settings)

    dialog = wx.FileDialog(
        parent, "Save as audio",
        defaultFile=(book.title or "book") + suffix + ".mp3",
        wildcard="MP3 files (*.mp3)|*.mp3",
        style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
    if dialog.ShowModal() != wx.ID_OK:
        dialog.Destroy()
        return
    path = dialog.GetPath()
    dialog.Destroy()
    if not path.lower().endswith(".mp3"):
        path += ".mp3"
    speech_window.start_audio_export(parent, book, settings, path,
                                     pages=pages)
