"""Tracks the processing job that is currently running.

Processing used to happen in a modal dialog, which blocked the whole
app: you could not read one book while another was being processed.
The dialog is now modeless, so the library and readers stay usable --
but that means the app has to know what is in flight, so it can refuse
actions that would pull the ground out from under a running job.

Exactly one job may run at a time. That is deliberate: several at once
would multiply API quota use unpredictably (most people are on a free
tier) and multiply the ways things can go wrong, for very little gain.

This module holds no wx and no threads of its own, so it can be tested
directly.
"""

import threading


class JobRegistry:
    """Which book, if any, is being processed right now."""

    def __init__(self):
        self._lock = threading.Lock()
        self._workspace = None
        self._title = ""

    # ----- state ---------------------------------------------------------

    def is_busy(self):
        with self._lock:
            return self._workspace is not None

    def current_title(self):
        """Title of the book being processed, or "" when idle."""
        with self._lock:
            return self._title

    def is_processing(self, book):
        """True when this exact book is the one being processed."""
        if book is None:
            return False
        with self._lock:
            return (self._workspace is not None
                    and self._workspace == book.workspace)

    # ----- transitions ---------------------------------------------------

    def start(self, book):
        """Claim the slot for `book`. Returns True on success, False when
        another job already holds it. Claiming for the same book twice
        also fails: a second run would fight the first over the same
        files."""
        with self._lock:
            if self._workspace is not None:
                return False
            self._workspace = book.workspace
            self._title = book.title or "book"
            return True

    def finish(self, book=None):
        """Release the slot. Passing the book guards against a late
        finish from an older job clearing a newer one."""
        with self._lock:
            if book is not None and self._workspace != book.workspace:
                return False
            self._workspace = None
            self._title = ""
            return True

    # ----- guards --------------------------------------------------------

    def blocked_reason(self, book):
        """Plain-language reason this book cannot be acted on right now,
        or None when it is free to use.

        Kept as a message rather than a boolean so every caller phrases
        the refusal the same way.
        """
        if self.is_processing(book):
            return ("'%s' is being processed right now. Wait for it to "
                    "finish, or cancel it in the processing window, "
                    "before changing it." % (book.title or "This book"))
        return None

    def busy_reason(self):
        """Reason a NEW job cannot start, or None when one may start."""
        with self._lock:
            if self._workspace is None:
                return None
            return ("'%s' is still being processed. Only one book is "
                    "processed at a time, so wait for it to finish or "
                    "cancel it first." % (self._title or "A book"))


# The app uses one shared registry.
registry = JobRegistry()
