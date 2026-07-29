"""Accessible Manga Reader entry point.

Run from source with:  python main.py
Dependencies:          pip install -r requirements.txt
"""

import json
import os
import sys
import traceback

# Ensure the project root is importable regardless of working directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    self_test_prefix = "--pdf-export-self-test="
    for argument in sys.argv[1:]:
        if argument.startswith(self_test_prefix):
            report_path = argument[len(self_test_prefix):]
            return _run_pdf_export_self_test(report_path)

    # Kept below the diagnostic route so a packaged PDF smoke test does
    # not initialize the GUI or need an interactive desktop.
    import wx
    from gui.main_frame import MainFrame

    app = wx.App()
    frame = MainFrame()
    frame.Show()
    app.MainLoop()
    return 0


def _run_pdf_export_self_test(report_path):
    """Exercise PDF export inside the packaged executable.

    Source tests cannot reveal a native library omitted by PyInstaller.
    This hidden command writes a JSON report so CI, and a failed build on
    a reader's own computer, can say exactly which packaged step failed.
    """
    from core import export

    class Book:
        title = "\u0643\u062a\u0627\u0628 \u0627\u0644\u0627\u062e\u062a\u0628\u0627\u0631"
        page_count = 1
        workspace = "pdf-export-self-test"
        scripts = {
            1: "Panel 1 (top right): "
               "\u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645. "
               "English 123.",
        }

    report_path = os.path.abspath(report_path)
    output_path = os.path.splitext(report_path)[0] + ".pdf"
    diagnostics = {}
    report = {
        "ok": False,
        "output_path": output_path,
        "diagnostics": diagnostics,
    }
    try:
        export.write_pdf(
            Book(), output_path, show_panel_labels=True,
            language="Arabic", diagnostics=diagnostics)
        report["ok"] = True
        report["output_bytes"] = os.path.getsize(output_path)
    except Exception as error:
        report["error_type"] = type(error).__name__
        report["error"] = str(error)
        report["traceback"] = traceback.format_exc()
    try:
        report_folder = os.path.dirname(report_path)
        if report_folder:
            os.makedirs(report_folder, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
    except Exception:
        return 2
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
