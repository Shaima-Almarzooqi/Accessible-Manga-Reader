"""The application icon, for every window with a title bar."""

import os
import sys

import wx

NAME = "AccessibleMangaReader.ico"


def icon_path():
    base = getattr(sys, "_MEIPASS", "") or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", NAME)


def apply_to(frame):
    """Give `frame` the app icon, or leave it alone if the file is
    missing -- a window must still open either way."""
    path = icon_path()
    if not os.path.exists(path):
        return
    try:
        frame.SetIcon(wx.Icon(path, wx.BITMAP_TYPE_ICO))
    except Exception:
        pass

