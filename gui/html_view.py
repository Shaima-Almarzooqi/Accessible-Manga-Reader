"""Internal HTML view window.

Displays the book's HTML document in an embedded web view. Screen
readers treat the content as a web document, so browse mode heading
navigation works: H for the next heading, 2 for the next page, 3 for
the next panel.

If no web view backend is available on the system, show_html_view
returns False and the caller falls back to the default browser.
"""

import wx

try:
    import wx.html2
except ImportError:
    wx.html2 = None


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

        # The legacy MSHTML backend is preferred: it ships with Windows
        # and needs no extra DLLs bundled into the executable.
        backend = wx.html2.WebViewBackendDefault
        if wx.html2.WebView.IsBackendAvailable(wx.html2.WebViewBackendIE):
            backend = wx.html2.WebViewBackendIE
        # The control's default name is a toolkit word that screen
        # readers may announce; give it the window's own title instead.
        self.view = wx.html2.WebView.New(panel, backend=backend, name=title)
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
        else:
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
