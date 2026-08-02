"""Saving a book as audio.

Speaking a whole volume can take a while, so this is nothing like the
other exports: it runs on a worker thread in its own window, reports
where it has got to, and can be cancelled at any point. The window is
a frame rather than a dialog for the same reason the processing window
is -- so it has its own Alt+Tab entry and the rest of the app stays
usable.

Completed consecutive pieces can be saved when the user stops. Ordinary
failures and a stop-without-saving leave the destination untouched.
"""

import threading
import time

import wx

from core import tts

from . import keys as keyhelp


def _describe(seconds):
    """A rough duration a person can act on, not a stopwatch."""
    if seconds < 90:
        return "a minute"
    minutes = int(round(seconds / 60.0))
    if minutes < 60:
        return "%d minutes" % minutes
    hours = minutes / 60.0
    return "%.1f hours" % hours


def start_audio_export(parent, book, settings, path, pages=None):
    """Begin speaking `book` into `path`, in its own window.

    `pages` limits it to a range, which is how the cost of a long
    book is kept down."""
    window = AudioExportWindow(parent, book, settings, path, pages)
    window.Show()
    return True


class AudioExportWindow(wx.Frame):
    def __init__(self, parent, book, settings, path, pages=None):
        super().__init__(parent,
                         title="Saving %s as audio" % (book.title or "book"),
                         size=(560, 380),
                         style=wx.DEFAULT_FRAME_STYLE)
        self.book = book
        self.settings = settings
        self.path = path
        self.pages = pages
        self._cancel = threading.Event()
        self._save_partial = threading.Event()
        self._closed = False
        self._finished = False
        self._started = time.time()

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        if settings.get("tts_engine") == tts.ENGINE_KOKORO:
            intro_text = (
                "Kokoro is generating the audio on this computer. You can "
                "carry on using the app while it works, and stop it at any "
                "point. When you stop, you can save the parts completed in "
                "order.")
        else:
            intro_text = (
                "Gemini is generating the audio through the API. You can "
                "carry on using the app while it works, and stop it at any "
                "point. When you stop, you can save the parts completed in "
                "order.")
        intro = wx.StaticText(panel, label=intro_text)
        intro.Wrap(510)
        sizer.Add(intro, 0, wx.ALL, 8)

        log_label = wx.StaticText(panel, label="&Progress:")
        sizer.Add(log_label, 0, wx.LEFT, 8)
        self.log = wx.TextCtrl(
            panel, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(510, 180))
        sizer.Add(self.log, 1, wx.EXPAND | wx.ALL, 8)

        self.gauge = wx.Gauge(panel, range=100)
        sizer.Add(self.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        self.cancel_button = wx.Button(panel, wx.ID_CANCEL, "&Stop")
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
                cancel_check=self._cancel.is_set,
                pages=self.pages,
                save_partial_check=self._save_partial.is_set)
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
        # Reading a book aloud is slow enough that "how much
        # longer?" is the real question, and a percentage alone
        # does not answer it. The estimate goes on the end of the
        # progress line rather than into a label of its own: a
        # label that changes quietly is never read out, so it
        # would not exist for the people this is written for.
        # Only once a part has finished, since an estimate from
        # nothing is a guess.
        if total and 0 < done < total:
            elapsed = time.time() - self._started
            message += "  About %s left." % _describe(
                elapsed / done * (total - done))
        self.log.AppendText(message + "\n")
        if not total:
            return
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
                "Stopped. No completed audio was saved.\n")
        elif self._cancel.is_set():
            self.log.AppendText(
                "Stopped. Saved %s of completed audio to %s\n"
                % (self._duration_label(seconds), self.path))
        else:
            self.log.AppendText(
                "Finished. Saved %s of audio to %s\n"
                % (self._duration_label(seconds), self.path))
        self.cancel_button.SetLabel("&Close")
        self.cancel_button.Enable(True)
        self.cancel_button.SetDefault()
        self.cancel_button.SetFocus()

    @staticmethod
    def _duration_label(seconds):
        if seconds < 60:
            rounded = max(1, int(round(seconds)))
            return "about %d second%s" % (
                rounded, "" if rounded == 1 else "s")
        minutes = max(1, int(round(seconds / 60.0)))
        return "about %d minute%s" % (
            minutes, "" if minutes == 1 else "s")

    # ----- closing --------------------------------------------------------

    def on_cancel(self, event):
        if self._finished or not self._thread.is_alive():
            self._shut()
            return
        if self._cancel.is_set():
            return
        self._ask_to_stop()

    def _ask_to_stop(self):
        dialog = wx.MessageDialog(
            self,
            "Save the audio parts that have finished in their original "
            "order?\n\nSaving keeps the completed beginning of the chosen "
            "book or page range. Stopping without saving leaves the "
            "destination unchanged.",
            "Stop saving audio",
            wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION)
        set_labels = getattr(dialog, "SetYesNoCancelLabels", None)
        if set_labels:
            set_labels("&Save completed audio", "Stop &without saving",
                       "&Keep generating")
        answer = dialog.ShowModal()
        dialog.Destroy()
        if answer == wx.ID_CANCEL:
            return False
        if answer == wx.ID_YES:
            self._save_partial.set()
            self.log.AppendText(
                "Stopping. Completed audio will be saved.\n")
        else:
            self.log.AppendText(
                "Stopping without saving completed audio.\n")
        self._cancel.set()
        self.cancel_button.SetLabel("Stopping...")
        self.cancel_button.Enable(False)
        return True

    def on_close(self, event):
        if self._finished or not self._thread.is_alive():
            self._shut()
            return
        if self._cancel.is_set():
            answer = wx.MessageBox(
                "Audio is still being stopped. Close this window while it "
                "finishes?",
                "Close audio progress", wx.YES_NO | wx.ICON_QUESTION, self)
            if answer == wx.YES:
                self._shut()
            return
        self._ask_to_stop()

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
