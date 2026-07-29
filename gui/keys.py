"""Shared keyboard behaviour.

Two rules, applied through EVT_CHAR_HOOK in every window:

1. Tab (not arrows) moves between controls. wxPython's TAB_TRAVERSAL
   treats arrow keys as navigation, which is disorienting with a screen
   reader: arrows wander into a list and then cannot leave it. So arrow
   keys are swallowed on controls that have no internal use for them
   (buttons and the like) and left alone on controls that genuinely need
   them (text fields, lists, choices, combo boxes, notebook tabs).

2. In the library list, only Up and Down move, and they stop at the
   ends instead of re-firing on the same item.
"""

import wx

try:
    import wx.html2
except ImportError:
    wx.html2 = None

UP_KEYS = frozenset({wx.WXK_UP, wx.WXK_NUMPAD_UP})
DOWN_KEYS = frozenset({wx.WXK_DOWN, wx.WXK_NUMPAD_DOWN})
HORIZONTAL_KEYS = frozenset({
    wx.WXK_LEFT, wx.WXK_RIGHT, wx.WXK_NUMPAD_LEFT, wx.WXK_NUMPAD_RIGHT})
ARROW_KEYS = UP_KEYS | DOWN_KEYS | HORIZONTAL_KEYS

# Controls with a legitimate internal use for arrow keys: never swallow
# arrows while one of these has focus.
ARROW_USING_CONTROLS = (
    wx.TextCtrl, wx.ComboBox, wx.Choice, wx.ListBox, wx.CheckListBox,
    wx.Notebook, wx.SpinCtrl, wx.SpinCtrlDouble, wx.Slider, wx.RadioBox,
) + ((wx.html2.WebView,) if wx.html2 is not None else ())


# Controls that Windows builds out of several native windows, so the
# window reported as focused can be a child rather than the control
# itself. A wx.RadioBox is a group box plus one native radio button per
# choice, and those children are not wx windows.
COMPOSITE_ARROW_CONTROLS = (wx.RadioBox,)


def _needs_arrows(focus):
    """True when the focused window, or a composite control containing
    it, uses arrow keys itself."""
    if isinstance(focus, ARROW_USING_CONTROLS):
        return True
    # Only composite controls are looked for up the chain. Walking up
    # for anything in ARROW_USING_CONTROLS would let arrows loose inside
    # a notebook page, where they would move focus between controls --
    # exactly what this helper exists to prevent.
    parent = focus.GetParent() if focus is not None else None
    while parent is not None:
        if isinstance(parent, COMPOSITE_ARROW_CONTROLS):
            return True
        parent = parent.GetParent()
    return False


def consume_arrow_navigation(event, focus):
    """True when this arrow key press should be swallowed so that Tab
    remains the only way to move between controls."""
    if event.GetKeyCode() not in ARROW_KEYS:
        return False
    if event.AltDown() or event.ControlDown():
        return False
    if focus is None:
        # Nothing identifiable has focus, which is what Windows reports
        # while a radio box's own native button is focused. Swallowing a
        # key we cannot account for is the dangerous choice: it left the
        # choices in the Reprocess and Ask dialogs unreachable.
        return False
    if _needs_arrows(focus):
        return False
    return True


def consume_list_arrow(event, listbox):
    """True when this arrow key press in `listbox` should be swallowed.

    Left and Right do nothing in a vertical list. Up on the first item
    and Down on the last item are swallowed so the screen reader does
    not announce the same entry again at the ends of the list.

    With Shift or Ctrl held the key is always passed through: those
    extend or move the selection, and with Ctrl the focused item can
    differ from the selected one, which cannot be tracked reliably from
    the outside.
    """
    code = event.GetKeyCode()
    if code not in ARROW_KEYS:
        return False
    if event.ShiftDown() or event.ControlDown() or event.AltDown():
        return False
    if code in HORIZONTAL_KEYS:
        return True
    count = listbox.GetCount()
    if count == 0:
        return True
    selections = listbox.GetSelections()
    if not selections:
        return False
    index = selections[0]
    if code in UP_KEYS and index <= 0:
        return True
    if code in DOWN_KEYS and index >= count - 1:
        return True
    return False
