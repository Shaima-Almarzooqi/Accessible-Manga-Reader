"""Installing an update over the running copy.

The app reaches people in three shapes, and each has to be updated
differently:

  installed  Set up by the installer, under the user's own AppData.
             The new installer is run and does the work itself.
  folder     The zip, extracted wherever the reader chose. Windows
             locks a running program, so the swap happens after the app
             exits, from a helper that then starts it again.
  single     The one-file exe, which unpacks itself into a temporary
             folder to run. It cannot replace itself sensibly, so the
             new file is downloaded and the reader is shown where it
             is.

Everything that decides *what* to do lives here as plain functions with
no side effects, so it can be tested. The part that actually moves
files is deliberately small, and keeps the old copy until the new one
is in place.
"""

import os
import sys

INSTALLED = "installed"
FOLDER = "folder"
SINGLE = "single"
SOURCE = "source"

# Where the installer puts things: Program Files, the conventional
# place, shared by every account on the computer. Writing there needs
# administrator permission, which is why installing an update raises an
# elevation prompt.
INSTALL_DIR_NAME = "Accessible Manga Reader"


def install_dirs():
    """Every place an installed copy might be, newest first.

    Both Program Files variants are checked because a 32-bit installer
    on a 64-bit machine lands in the (x86) one, and the app should
    still recognise itself as installed.
    """
    found = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        base = os.environ.get(variable)
        if base:
            candidate = os.path.join(base, INSTALL_DIR_NAME)
            if candidate not in found:
                found.append(candidate)
    return found


def install_dir():
    """The main install location, or None off Windows."""
    places = install_dirs()
    return places[0] if places else None


def install_kind(executable=None, meipass=None, frozen=None, installed=None):
    """Which of the three shapes this copy is.

    The arguments exist for testing; left alone they describe the
    running program.
    """
    if frozen is None:
        frozen = getattr(sys, "frozen", False)
    if not frozen:
        return SOURCE
    if executable is None:
        executable = sys.executable
    if meipass is None:
        meipass = getattr(sys, "_MEIPASS", "")
    here = os.path.dirname(os.path.abspath(executable))
    places = [installed] if installed else install_dirs()
    if any(place and _within(here, place) for place in places):
        return INSTALLED
    # A one-file build unpacks itself somewhere else entirely to run;
    # a folder build keeps its parts beside the exe.
    if meipass and not _within(os.path.abspath(meipass), here):
        return SINGLE
    return FOLDER


def _within(path, parent):
    try:
        return os.path.commonpath([os.path.abspath(path),
                                   os.path.abspath(parent)]) == \
            os.path.abspath(parent)
    except ValueError:
        return False  # different drives


def architecture():
    """"x64" or "arm64", matching how the downloads are named."""
    machine = (os.environ.get("PROCESSOR_ARCHITECTURE") or "").lower()
    if "arm" in machine:
        return "arm64"
    return "x64"


def choose_asset(assets, kind, arch=None):
    """The download that suits this copy, or None if there isn't one.

    An installed copy wants the installer; a folder wants the zip; a
    one-file exe wants the exe. Picking the wrong architecture would
    hand somebody a program their machine cannot run, so the name has
    to match on both counts.
    """
    arch = arch or architecture()
    if kind == INSTALLED:
        wanted, extension = "setup", ".exe"
    elif kind == FOLDER:
        wanted, extension = None, ".zip"
    elif kind == SINGLE:
        wanted, extension = None, ".exe"
    else:
        return None
    for asset in assets or []:
        name = asset.name.lower()
        if not name.endswith(extension):
            continue
        if arch not in name:
            continue
        is_setup = "setup" in name
        if wanted == "setup" and not is_setup:
            continue
        if wanted is None and is_setup:
            continue
        return asset
    return None


def can_update_here(kind, folder=None):
    """Why an update cannot be applied automatically, or None if it can.

    Two situations are worth catching before anything is downloaded: a
    copy somewhere the reader cannot write, and a one-file exe, which
    has no sane way to replace itself while running.
    """
    if kind == SOURCE:
        return ("This copy is running from the source code, so it "
                "updates with git rather than from here.")
    if kind == SINGLE:
        return ("The single file version cannot replace itself while "
                "it is running. The new version can be downloaded and "
                "you can put it wherever you keep this one.")
    if kind == INSTALLED:
        # Nothing to refuse: the installer asks Windows for permission
        # itself, so this only needs to warn, which the dialog does.
        return None
    if kind == FOLDER:
        folder = folder or os.path.dirname(os.path.abspath(sys.executable))
        if not os.access(folder, os.W_OK):
            return ("This copy is in a folder that cannot be written "
                    "to, so it cannot update itself. Moving it "
                    "somewhere like your Documents folder would fix "
                    "that.")
    return None


def download(url, destination, expected_size=0, on_progress=None,
             cancel_check=None):
    """Fetch an update to `destination`.

    Written to a neighbouring part-file and only renamed once it is
    complete, so a half-finished download can never be mistaken for an
    installer and run.
    """
    import requests

    partial = destination + ".part"
    received = 0
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        total = int(response.headers.get("Content-Length") or expected_size)
        with open(partial, "wb") as handle:
            for block in response.iter_content(chunk_size=256 * 1024):
                if cancel_check and cancel_check():
                    handle.close()
                    _remove(partial)
                    return None
                handle.write(block)
                received += len(block)
                if on_progress and total:
                    on_progress(min(100, received * 100 // total))
    if expected_size and received != expected_size:
        _remove(partial)
        raise OSError(
            "The download did not arrive in one piece, so it was "
            "discarded rather than installed.")
    _remove(destination)
    os.replace(partial, destination)
    return destination


def _remove(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def swap_script(folder, unpacked, executable, backup):
    """The commands that replace a folder copy once the app has exited.

    Written as a batch file because it has to outlive the program it is
    replacing. The old folder is moved aside rather than deleted, and
    put back if anything goes wrong, so a failed update leaves a
    working app rather than an empty directory.
    """
    return "\r\n".join([
        "@echo off",
        "rem Wait for the app to close its own files.",
        'ping -n 4 127.0.0.1 >nul',
        'if exist "%s" rmdir /s /q "%s"' % (backup, backup),
        'move "%s" "%s" >nul' % (folder, backup),
        'if errorlevel 1 goto :failed',
        'move "%s" "%s" >nul' % (unpacked, folder),
        'if errorlevel 1 goto :restore',
        'rmdir /s /q "%s"' % backup,
        'start "" "%s"' % executable,
        'goto :done',
        ':restore',
        'move "%s" "%s" >nul' % (backup, folder),
        ':failed',
        'start "" "%s"' % executable,
        ':done',
        # Removes the script itself once it has finished.
        'del "%~f0"',
        "",
    ])


def staging_dir():
    """A scratch folder for downloads, beside the app's own data."""
    from . import config
    path = os.path.join(config.data_dir(), "updates")
    os.makedirs(path, exist_ok=True)
    return path


def apply_installer(setup_path):
    """Run a downloaded installer and tell the caller to close the app.

    Started without waiting, because the installer needs this program
    gone before it can replace it. Windows raises its own permission
    prompt: the installer writes to Program Files, so the reader is
    asked to allow it before anything happens.
    """
    import subprocess
    subprocess.Popen([setup_path, "/SILENT", "/NORESTART"], close_fds=True)


def apply_folder_update(zip_path, folder=None, executable=None):
    """Unpack an update beside the app and schedule the swap.

    The new copy is unpacked in full first, so a bad download is found
    before anything is moved. The swap itself happens after this
    program exits, from a script that keeps the old folder until the
    new one is in place.
    """
    import subprocess
    import zipfile

    folder = os.path.abspath(
        folder or os.path.dirname(os.path.abspath(sys.executable)))
    executable = executable or os.path.abspath(sys.executable)
    unpacked = folder + ".new"
    backup = folder + ".old"

    if os.path.exists(unpacked):
        import shutil
        shutil.rmtree(unpacked, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(unpacked)
    if not os.path.isdir(unpacked) or not os.listdir(unpacked):
        raise OSError("The update did not unpack, so nothing was changed.")

    script = os.path.join(staging_dir(), "finish-update.bat")
    with open(script, "w", encoding="utf-8") as handle:
        handle.write(swap_script(folder, unpacked, executable, backup))
    subprocess.Popen(["cmd", "/c", script], close_fds=True,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return script
