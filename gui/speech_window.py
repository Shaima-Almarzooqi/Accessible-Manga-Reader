"""Saving a book as audio.

Speaking a whole volume takes hours and a large amount of a service's
allowance, so this is nothing like the other exports: it runs on a
worker thread in its own window, reports where it has got to, and can
be cancelled at any point. The window is a frame rather than a dialog
for the same reason the processing window is -- so it has its own
Alt+Tab entry and the rest of the app stays usable.

Nothing is written until every piece has been spoken, so cancelling
leaves no half-finished file behind.
"""

import threading

import wx

from core import tts

from . import keys as keyhelp


def start_audio_export(parent, book, settings, path):
    """Begin speaking `book` into `path`, in its own window."""
    window = AudioExportWindow(parent, book, settings, path)
    window.Show()
    return True


class AudioExportWindow(wx.Frame):
    def __init__(self, parent, book, settings, path):
        super().__init__(parent,
                         title="Saving %s as audio" % (book.title or "book"),
                         size=(560, 380),
                         style=wx.DEFAULT_FRAME_STYLE)
        self.book = book
        self.settings = settings
        self.path = path
        self._cancel = threading.Event()
        self._closed = False
        self._finished = False

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        intro = wx.StaticText(panel, label=(
            "Reading this book aloud can take a long time and uses a large "
            "part of your Gemini allowance. You can carry on using the app "
            "while it works, and stop it at any point."))
        intro.Wrap(510)
        sizer.Add(intro, 0, wx.ALL, 8)

        log_label = wx.StaticText(panel, label="&Progress:")
        sizer.Add(log_label, 0, wx.LEFT, 8)
        self.log = wx.TextCtrl(
            panel, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(510, 180))
        sizer.Add(self.log, 1, wx.EXPAND | wx.ALL, 8)

        self.gauge = wx.Gauge(panel, range=100)
        sizer.Add(self.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        self.cancel_button = wx.Button(panel, wx.ID_CANCEL, "&Cancel")
        self.cancel_button.Bind(wx.EVT_BUTTON, self.on_cancel)
        sizer.Add(self.cancel_button, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        panel.SetSizer(sizer)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(outer)
        self.log.SetFocus()

        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ----- worker ---------------------------------------------------------

    def _run(self):
        def on_progress(message, done, total):
            self._post(self._append, message, done, total)

        try:
            seconds = tts.write_mp3(
                self.book, self.path, self.settings,
                on_progress=on_progress,
                cancel_check=self._cancel.is_set)
        except Exception as error:
            self._post(self._done, None, str(error))
            return
        self._post(self._done, seconds, None)

    def _post(self, fn, *args):
        def safe():
            if self._closed:
                return
            try:
                fn(*args)
            except RuntimeError:
                pass
        wx.CallAfter(safe)

    # ----- UI thread ------------------------------------------------------

    def _append(self, message, done, total):
        self.log.AppendText(message + "\n")
        if total:
            percent = int(done * 100 / total)
            self.gauge.SetValue(percent)
            self.SetTitle("Saving %s as audio - %d percent"
                          % (self.book.title or "book", percent))

    def _done(self, seconds, error):
        self._finished = True
        if error:
            self.log.AppendText("Stopped: %s\n" % error)
        elif seconds is None:
            self.log.AppendText(
                "Cancelled. Nothing was saved.\n")
        else:
            minutes = int(seconds // 60)
            self.log.AppendText(
                "Finished. Saved about %d minute%s of audio to %s\n"
                % (minutes, "" if minutes == 1 else "s", self.path))
        self.cancel_button.SetLabel("&Close")
        self.cancel_button.SetDefault()
        self.cancel_button.SetFocus()

    # ----- closing --------------------------------------------------------

    def on_cancel(self, event):
        if self._finished or not self._thread.is_alive():
            self._shut()
            return
        self._cancel.set()
        self.log.AppendText(
            "Stopping. Nothing will be saved; you can close this window.\n")
        self.cancel_button.SetLabel("&Close now")

    def on_close(self, event):
        if self._finished or not self._thread.is_alive():
            self._shut()
            return
        answer = wx.MessageBox(
            "Still reading this book aloud. Stop and close? Nothing will "
            "be saved.",
            "Stop saving audio", wx.YES_NO | wx.ICON_QUESTION, self)
        if answer != wx.YES:
            return
        self._cancel.set()
        self._shut()

    def _shut(self):
        self._closed = True
        self.Destroy()

    def _on_char_hook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.on_cancel(event)
        elif keyhelp.consume_arrow_navigation(event, wx.Window.FindFocus()):
            return
        else:
            event.Skip()
