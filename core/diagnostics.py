"""A detailed log, for when something goes wrong and nobody can see it.

The app tells a reader what failed in a sentence, which is right for
reading but useless for working out why. Until now the answer has been
to write a throwaway script and reproduce the problem, which only
works for problems that can be reproduced on the developer's own
machine.

So: an off-by-default log that records what each part of the app did,
in enough detail to diagnose a failure from the file alone. It is off
by default because it writes to disk on every request and most readers
will never need it.

Two rules shape everything here.

API keys are never written. Not the key, not a prefix of it, not
enough to reconstruct one. A log is a file a reader may well send to
somebody else for help, and a key that leaks that way is a key that
has to be replaced. Keys are referred to by their position in the
list, which is what the rest of the app already reports.

Nothing here may break what it is watching. Every call is wrapped so
that a full disk, a locked file or a bad value makes the log stop
rather than the export, the processing run or the reader.
"""

import os
import re
import threading
import time
import traceback

from . import config

MAX_FILES = 5
MAX_BYTES = 2 * 1024 * 1024

_lock = threading.Lock()
_enabled = False
_path = None

# Anything that looks like a credential, whatever field it arrived in.
# Keys are matched by shape rather than by name, because a value only
# has to be written once to be worth replacing.
# Named fields first, so a whole "x-goog-api-key: AIza..." goes in one
# piece. Running the key-shaped patterns first would leave the field
# name behind for the next pattern to chew on, which produced output
# like "[key removed] removed]".
_SECRETS = [
    re.compile(r"(?i)\b(api[_-]?key|authorization|x-goog-api-key|"
               r"x-api-key)\s*[:=]\s*(bearer\s+)?\S+"),
    re.compile(r"(?i)\bbearer\s+[0-9A-Za-z_\-.]{10,}"),
    re.compile(r"sk-ant-[0-9A-Za-z_\-]{10,}"),         # Anthropic
    re.compile(r"sk-or-[0-9A-Za-z_\-]{10,}"),          # OpenRouter
    re.compile(r"AIza[0-9A-Za-z_\-]{10,}"),            # Google
    re.compile(r"sk-[0-9A-Za-z_\-]{10,}"),             # OpenAI
]
_REPEATED = re.compile(r"(\[key removed\][\s\]]*)+")

MARKER = "[key removed]"


def redact(text):
    """Remove anything that looks like a key from a line of log text.

    Matched by shape as well as by field name: a key only has to be
    written once to be worth replacing, and a log is a file a reader
    may well send to somebody else for help.
    """
    out = str(text)
    for pattern in _SECRETS:
        out = pattern.sub(MARKER, out)
    return _REPEATED.sub(MARKER, out)


def logs_dir():
    """Where the log files live, created on first use."""
    path = os.path.join(config.data_dir(), "logs")
    os.makedirs(path, exist_ok=True)
    return path


def is_on():
    return _enabled


def start(settings):
    """Turn the log on or off to match the setting.

    Called when the app starts and whenever Settings is saved, so a
    reader who turns it on does not have to restart to get a log.
    """
    global _enabled, _path
    wanted = bool((settings or {}).get("detailed_log", False))
    with _lock:
        if wanted and not _enabled:
            try:
                _path = os.path.join(
                    logs_dir(),
                    time.strftime("log-%Y-%m-%d-%H%M%S.txt"))
                _enabled = True
            except Exception:
                _enabled = False
                _path = None
                return
        elif not wanted:
            _enabled = False
            _path = None
            return
    write("log", "started",
          version=getattr(config, "APP_VERSION", "?"),
          provider=(settings or {}).get("provider", "?"))
    _tidy()


def current_path():
    """The file being written, or None when the log is off."""
    return _path


def _tidy():
    """Keep the folder small: oldest files go first."""
    try:
        folder = logs_dir()
        files = sorted(
            (os.path.join(folder, name) for name in os.listdir(folder)
             if name.startswith("log-") and name.endswith(".txt")),
            key=os.path.getmtime)
        for stale in files[:-MAX_FILES]:
            os.remove(stale)
    except Exception:
        pass


def write(area, event, **fields):
    """Record one thing that happened.

    `area` is the part of the app -- processing, audio, export,
    bank -- so a reader looking for one failure can find it. Fields
    are written as name=value, redacted.
    """
    if not _enabled or not _path:
        return
    try:
        parts = []
        for name in sorted(fields):
            value = fields[name]
            if isinstance(value, float):
                value = round(value, 2)
            parts.append("%s=%s" % (name, redact(value)))
        line = "%s  %-10s %-26s %s\n" % (
            time.strftime("%H:%M:%S"), area, event, " ".join(parts))
        with _lock:
            if os.path.exists(_path) and os.path.getsize(_path) > MAX_BYTES:
                return
            with open(_path, "a", encoding="utf-8") as handle:
                handle.write(line)
    except Exception:
        # A log that breaks the thing it is watching is worse than no
        # log at all.
        pass


def failure(area, event, error, **fields):
    """Record an exception with its traceback."""
    if not _enabled:
        return
    write(area, event, error=type(error).__name__,
          detail=str(error)[:300], **fields)
    try:
        with _lock:
            with open(_path, "a", encoding="utf-8") as handle:
                handle.write(redact(traceback.format_exc()))
                handle.write("\n")
    except Exception:
        pass
