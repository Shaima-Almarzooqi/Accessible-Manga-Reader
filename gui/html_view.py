"""Internal HTML view window.

Displays the book's HTML document in an embedded web view. Screen
readers treat the content as a web document, so browse mode heading
navigation works: H for the next heading, 2 for the next page, 3 for
the next panel.

If no web view backend is available on the system, show_html_view
returns False and the caller falls back to the default browser.
"""

import ctypes

import wx

from . import keys as keyhelp

try:
    import wx.html2
except ImportError:
    wx.html2 = None


def make_web_view(parent, accessible_name):
    """Create the web view used for every HTML display in the app.

    Returns None if this system has no web view backend, so callers can
    fall back to the browser or a text control.
    """
    if wx.html2 is None:
        return None
    try:
        # Default arguments on purpose: passing an explicit backend
        # together with a custom name= was found to leave the control
        # blank on the Windows backend.
        view = wx.html2.WebView.New(parent)
    except Exception:
        return None
    view.SetName(accessible_name)
    # The window's own text, which is what a screen reader reads as the
    # control's name; wx leaves it set to the class name.
    try:
        ctypes.windll.user32.SetWindowTextW(
            view.GetHandle(), accessible_name)
    except Exception:
        pass
    return view


def show_html_view(parent, title, html, default_filename):
    """Open the internal HTML view. Returns True on success, False if
    no web view backend is available on this system."""
    if wx.html2 is None:
        return False
    try:
        frame = HtmlViewFrame(parent, title, html, default_filename)
    except Exception:
        return False
    frame.Show()
    return True


class HtmlViewFrame(wx.Frame):
    def __init__(self, parent, title, html, default_filename):
        super().__init__(parent, title=title, size=(900, 700))
        self.html = html
        self.default_filename = default_filename

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.view = make_web_view(panel, title)
        if self.view is None:
            raise RuntimeError("no web view backend")
        sizer.Add(self.view, 1, wx.EXPAND)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        save_button = wx.Button(panel, label="&Save as HTML...")
        save_button.Bind(wx.EVT_BUTTON, self.on_save)
        buttons.Add(save_button, 0, wx.RIGHT, 6)
        close_button = wx.Button(panel, label="&Close")
        close_button.Bind(wx.EVT_BUTTON, lambda event: self.Close())
        buttons.Add(close_button, 0)
        sizer.Add(buttons, 0, wx.ALL, 6)

        panel.SetSizer(sizer)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.view.SetPage(html, "")
        self.view.SetFocus()

    def _on_char_hook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.Close()
            return
        # Tab moves between the web view and the buttons; arrow keys stay
        # with whichever control has focus. Inside the web view the
        # arrows scroll and navigate the content as normal; on the
        # buttons they do nothing (Tab moves instead).
        if keyhelp.consume_arrow_navigation(event, wx.Window.FindFocus()):
            return
        event.Skip()

    def on_save(self, event):
        dialog = wx.FileDialog(
            self, "Save as HTML file", defaultFile=self.default_filename,
            wildcard="HTML files (*.html)|*.html",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if dialog.ShowModal() == wx.ID_OK:
            try:
                with open(dialog.GetPath(), "w", encoding="utf-8") as f:
                    f.write(self.html)
                wx.MessageBox("Saved successfully.", "Save as HTML",
                              wx.OK | wx.ICON_INFORMATION, self)
            except OSError as error:
                wx.MessageBox("Saving failed: %s" % error, "Save as HTML",
                              wx.OK | wx.ICON_ERROR, self)
        dialog.Destroy()
