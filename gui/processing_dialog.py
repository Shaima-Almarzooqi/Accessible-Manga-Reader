"""Processing dialog.

Runs processor.process_book on a worker thread and shows progress in a
read-only log control plus a gauge (which feeds NVDA's progress bar
output) and a live percentage in the window title (so NVDA+T always
answers "how far along?").

Cancelling: the first press of Cancel tells the processor to stop and
immediately relabels the button "Close now" -- the window can be closed
right away without waiting for the in-flight network request, whose
result is simply discarded when it arrives. All completed batches are
already saved to disk, so nothing is ever lost.
"""

import threading

import wx

from core import processor

from . import keys as keyhelp


class ProcessingDialog(wx.Dialog):
    def __init__(self, parent, book, settings):
        super().__init__(parent, title="Processing " + (book.title or "book"),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.book = book
        self.settings = settings
        self._cancel = threading.Event()
        self._closed = False
        self._finished_flag = False
        self.result = None

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        log_label = wx.StaticText(panel, label="Progress &log:")
        sizer.Add(log_label, 0, wx.LEFT | wx.TOP, 8)
        self.log = wx.TextCtrl(
            panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
            size=(560, 220))
        sizer.Add(self.log, 1, wx.EXPAND | wx.ALL, 8)

        self.gauge = wx.Gauge(panel, range=100)
        sizer.Add(self.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        self.cancel_button = wx.Button(panel, wx.ID_CANCEL, "&Cancel")
        self.cancel_button.Bind(wx.EVT_BUTTON, self.on_cancel)
        sizer.Add(self.cancel_button, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        panel.SetSizer(sizer)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizerAndFit(outer)
        self.log.SetFocus()

        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ----- worker thread --------------------------------------------------

    def _run(self):
        def on_progress(message, done, total):
            self._post(self._append, message, done, total)

        try:
            result = processor.process_book(
                self.book, self.settings,
                on_progress=on_progress,
                cancel_check=self._cancel.is_set)
        except Exception as error:
            # The dialog must always be told the run is over, or it
            # would wait for a worker that is no longer running.
            result = processor.ProcessResult()
            result.error = "Unexpected error: %s" % error
        self._post(self._finished, result)

    def _post(self, fn, *args):
        """Marshal a callback to the UI thread, silently dropping it if
        the dialog has already been closed (the worker may outlive it
        when the user chooses Close now)."""
        def safe():
            if self._closed:
                return
            try:
                fn(*args)
            except RuntimeError:
                pass  # underlying window already destroyed
        wx.CallAfter(safe)

    # ----- UI thread ---------------------------------------------------------

    def _append(self, message, done, total):
        self.log.AppendText(message + "\n")
        if total:
            percent = int(done * 100 / total)
            self.gauge.SetValue(percent)
            self.SetTitle("Processing %s - %d percent"
                          % (self.book.title or "book", percent))

    def _finished(self, result):
        self.result = result
        self._finished_flag = True
        if result.error:
            self.log.AppendText("Stopped: %s\n" % result.error)
        elif result.cancelled:
            self.log.AppendText(
                "Cancelled. %d pages were saved and processing can be "
                "resumed at any time.\n" % result.pages_done)
        else:
            self.log.AppendText(
                "Finished. %d pages processed.\n" % result.pages_done)
            if result.pages_failed:
                self.log.AppendText(
                    "%d pages failed and will be retried if you choose "
                    "Process again.\n" % len(result.pages_failed))
        self.cancel_button.SetLabel("&Close")
        self.cancel_button.SetDefault()
        self.cancel_button.SetFocus()

    # ----- cancel / close ------------------------------------------------------

    def _close_now(self):
        self._closed = True
        self.EndModal(wx.ID_CLOSE)

    def on_cancel(self, event):
        if self._finished_flag or not self._thread.is_alive():
            self._close_now()
            return
        if not self._cancel.is_set():
            self._cancel.set()
            self.log.AppendText(
                "Cancelling. Progress so far is saved; the request "
                "currently in flight will be discarded. You can close "
                "this window now.\n")
            self.cancel_button.SetLabel("Close &now")
            self.cancel_button.SetFocus()
        else:
            self._close_now()

    def _on_char_hook(self, event):
        code = event.GetKeyCode()
        if code == wx.WXK_ESCAPE:
            self.on_cancel(event)
        elif (code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
              and self._finished_flag):
            self._close_now()
        elif keyhelp.consume_arrow_navigation(event, wx.Window.FindFocus()):
            return
        else:
            event.Skip()

    def on_close(self, event):
        if self._finished_flag or not self._thread.is_alive():
            self._close_now()
        elif not self._cancel.is_set():
            self.on_cancel(event)
            event.Veto()
        else:
            self._close_now()
