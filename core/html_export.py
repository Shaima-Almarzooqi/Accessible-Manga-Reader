"""Build an HTML document of a processed book for reading in a web
browser, where screen reader browse mode gives heading navigation for
free: H jumps to the next heading, 2 to the next page, 3 to the next
panel.

Heading structure:
  h1  book title
  h2  Page N of M
  h3  Panel i of k (position)   -- only when panel labels are shown

With panel labels hidden the page reads as a continuous narrative under
its h2, with the panel prefixes stripped and every line a paragraph.
"""

import html

from . import prompts

PAGE_STYLE = """
body { font-family: sans-serif; max-width: 46em; margin: 1em auto;
       padding: 0 1em; line-height: 1.6; }
h1 { font-size: 1.5em; }
h2 { font-size: 1.25em; margin-top: 1.5em; }
h3 { font-size: 1.05em; margin-top: 1em; }
p { margin: 0.4em 0; }
"""


def _paragraphs(text):
    lines = [html.escape(line.strip())
             for line in text.splitlines() if line.strip()]
    return "\n".join("<p>%s</p>" % line for line in lines)


def build_html(book, show_panel_labels=True, language="en"):
    """Return a complete HTML document for the whole book."""
    title = html.escape(book.title or "Book")
    parts = [
        "<!DOCTYPE html>",
        '<html lang="%s">' % html.escape(language),
        "<head>",
        '<meta charset="utf-8">',
        "<title>%s</title>" % title,
        "<style>%s</style>" % PAGE_STYLE,
        "</head>",
        "<body>",
        "<h1>%s</h1>" % title,
    ]
    for number in range(1, book.page_count + 1):
        parts.append("<h2>Page %d of %d</h2>" % (number, book.page_count))
        script = book.scripts.get(number)
        if not script:
            parts.append("<p>(This page has not been processed yet.)</p>")
            continue
        if show_panel_labels:
            panels = prompts.split_panels(script)
            for index, panel in enumerate(panels, start=1):
                position = prompts.panel_position(panel)
                heading = "Panel %d of %d" % (index, len(panels))
                if position:
                    heading += " (%s)" % position
                parts.append("<h3>%s</h3>" % html.escape(heading))
                parts.append(_paragraphs(prompts.strip_panel_labels(panel)))
        else:
            parts.append(_paragraphs(prompts.strip_panel_labels(script)))
    parts.append("</body>")
    parts.append("</html>")
    return "\n".join(parts)
