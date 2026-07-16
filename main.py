"""Accessible Manga Reader entry point.

Run from source with:  python main.py
Dependencies:          pip install -r requirements.txt
"""

import sys
import os

# Ensure the project root is importable regardless of working directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wx  # noqa: E402

from gui.main_frame import MainFrame  # noqa: E402


def main():
    app = wx.App()
    frame = MainFrame()
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
