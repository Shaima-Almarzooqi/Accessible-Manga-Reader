"""Saving a processed book to shareable file formats.

Every format is built from one shared outline (see `book_outline`), so a
book reads the same whichever way it is exported and there is a single
place to change how a book is structured.

Headings are what make an exported book navigable with a screen reader,
so each format carries them properly:

  EPUB  real XHTML h1/h2/h3 plus a navigation document, which is the
        best of these formats for reading with assistive technology.
  DOCX  Word's own Heading 1/2/3 styles, so the navigation pane and
        screen-reader heading commands both work.
  PDF   tagged, by printing the HTML with the system's Chromium browser
        (Edge, which comes with Windows). Its structure tree and document
        outline make the headings available to assistive technology.
  HTML  handled by core.html_export.
  TXT   plain text, from the book's own full_text().
"""

import os
import pathlib
import shutil
import subprocess
import tempfile
import xml.sax.saxutils as _xml
import zipfile

from . import config, html_export, prompts


def _escape(text):
    return _xml.escape(text or "")


def _paragraph_lines(text):
    """Non-empty lines of a script, each of which becomes a paragraph."""
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def book_outline(book, show_panel_labels=True):
    """The whole book as a flat list of (kind, text) items.

    kind is "h1", "h2", "h3" or "p". Keeping this in one place means the
    EPUB, Word and PDF exports cannot drift apart from one another.
    """
    items = [("h1", book.title or "Book")]
    for number in range(1, book.page_count + 1):
        items.append(("h2", "Page %d of %d" % (number, book.page_count)))
        script = book.scripts.get(number)
        if not script:
            items.append(("p", "(This page has not been processed yet.)"))
            continue
        if show_panel_labels:
            panels = prompts.split_panels(script)
            for index, panel in enumerate(panels, start=1):
                heading = "Panel %d of %d" % (index, len(panels))
                position = prompts.panel_position(panel)
                if position:
                    heading += " (%s)" % position
                items.append(("h3", heading))
                for line in _paragraph_lines(
                        prompts.strip_panel_labels(panel)):
                    items.append(("p", line))
        else:
            for line in _paragraph_lines(prompts.strip_panel_labels(script)):
                items.append(("p", line))
    return items


# ----- plain text and HTML -------------------------------------------------

def write_text(book, path, show_panel_labels=True, language="en"):
    """Save the book as plain text, matching what the reader shows."""
    text = book.full_text()
    if not show_panel_labels:
        text = prompts.strip_panel_labels(text)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def write_html(book, path, show_panel_labels=True, language="en"):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(html_export.build_html(
            book, show_panel_labels=show_panel_labels,
            language=config.language_code(language)))


# ----- EPUB ----------------------------------------------------------------

_CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0"
    xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/package.opf"
        media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def _epub_body(items):
    parts = []
    for kind, text in items:
        if kind == "p":
            parts.append("<p>%s</p>" % _escape(text))
        else:
            parts.append("<%s>%s</%s>" % (kind, _escape(text), kind))
    return "\n".join(parts)


def _epub_nav(items, language):
    """A navigation document listing every page, so a reading app can
    jump straight to one."""
    direction = "rtl" if config.is_rtl(language) else "ltr"
    links = []
    for index, (kind, text) in enumerate(items):
        if kind == "h2":
            links.append('<li><a href="content.xhtml#p%d">%s</a></li>'
                         % (index, _escape(text)))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"\n'
        '      xmlns:epub="http://www.idpf.org/2007/ops" lang="%s"'
        ' xml:lang="%s" dir="%s">\n'
        "<head><title>Contents</title></head>\n"
        "<body>\n"
        '<nav epub:type="toc" id="toc"><h1>Contents</h1>\n'
        "<ol>\n%s\n</ol>\n</nav>\n"
        "</body>\n</html>\n"
        % (language, language, direction, "\n".join(links)))


def write_epub(book, path, show_panel_labels=True, language="en"):
    """Save the book as an EPUB.

    Written by hand rather than with a library: an EPUB is a zip of XHTML
    plus a little metadata, and doing it here keeps the app dependency
    free and the markup exactly as accessible as we want it.
    """
    language = config.language_code(language)
    direction = "rtl" if config.is_rtl(language) else "ltr"
    items = book_outline(book, show_panel_labels=show_panel_labels)
    title = book.title or "Book"

    # Page headings get ids so the navigation document can link to them.
    body_parts = []
    for index, (kind, text) in enumerate(items):
        if kind == "h2":
            body_parts.append('<h2 id="p%d">%s</h2>' % (index, _escape(text)))
        elif kind == "p":
            body_parts.append("<p>%s</p>" % _escape(text))
        else:
            body_parts.append("<%s>%s</%s>" % (kind, _escape(text), kind))

    content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" lang="%s"'
        ' xml:lang="%s" dir="%s">\n'
        "<head><title>%s</title></head>\n<body>\n%s\n</body>\n</html>\n"
        % (language, language, direction, _escape(title),
           "\n".join(body_parts)))

    package = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"\n'
        '         unique-identifier="bookid">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '    <dc:identifier id="bookid">%s</dc:identifier>\n'
        "    <dc:title>%s</dc:title>\n"
        "    <dc:language>%s</dc:language>\n"
        '    <meta property="dcterms:modified">2000-01-01T00:00:00Z</meta>\n'
        "  </metadata>\n"
        "  <manifest>\n"
        '    <item id="nav" href="nav.xhtml" '
        'media-type="application/xhtml+xml" properties="nav"/>\n'
        '    <item id="content" href="content.xhtml" '
        'media-type="application/xhtml+xml"/>\n'
        "  </manifest>\n"
        '  <spine>\n    <itemref idref="content"/>\n  </spine>\n'
        "</package>\n"
        % (_escape("amr-" + os.path.basename(book.workspace or "book")),
           _escape(title), language))

    with zipfile.ZipFile(path, "w") as archive:
        # The mimetype entry must come first and be stored uncompressed.
        archive.writestr(
            zipfile.ZipInfo("mimetype"), "application/epub+zip",
            compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", _CONTAINER_XML)
        archive.writestr("OEBPS/package.opf", package)
        archive.writestr("OEBPS/nav.xhtml", _epub_nav(items, language))
        archive.writestr("OEBPS/content.xhtml", content)


# ----- Word ----------------------------------------------------------------

_DOCX_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels"
      ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>
"""

_DOCX_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships
    xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Target="word/document.xml"
      Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"/>
</Relationships>
"""

_DOCX_DOC_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships
    xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Target="styles.xml"
      Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"/>
</Relationships>
"""

_W_NS = ("http://schemas.openxmlformats.org/wordprocessingml/2006/main")


def _docx_styles():
    """Heading styles Word recognises.

    outlineLvl is what puts an entry in Word's navigation pane and makes
    the heading reachable by a screen reader's heading command, so each
    style declares it.
    """
    styles = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<w:styles xmlns:w="%s">' % _W_NS,
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal"/></w:style>',
    ]
    for level, size in ((1, 36), (2, 30), (3, 26)):
        styles.append(
            '<w:style w:type="paragraph" w:styleId="Heading%d">'
            '<w:name w:val="heading %d"/>'
            '<w:basedOn w:val="Normal"/>'
            '<w:pPr><w:outlineLvl w:val="%d"/></w:pPr>'
            '<w:rPr><w:b/><w:sz w:val="%d"/></w:rPr>'
            "</w:style>" % (level, level, level - 1, size))
    styles.append("</w:styles>")
    return "\n".join(styles)


def write_docx(book, path, show_panel_labels=True, language="en"):
    """Save the book as a Word document.

    Built by hand for the same reason as the EPUB: a .docx is a zip of
    XML, and writing it here avoids a dependency while guaranteeing real
    heading styles rather than text that merely looks big.
    """
    language = config.language_code(language)
    rtl = config.is_rtl(language)
    items = book_outline(book, show_panel_labels=show_panel_labels)
    body = []
    for kind, text in items:
        paragraph_properties = []
        if kind != "p":
            paragraph_properties.append(
                '<w:pStyle w:val="Heading%s"/>' % kind[1])
        if rtl:
            paragraph_properties.append("<w:bidi/>")
        style = ("<w:pPr>%s</w:pPr>"
                 % "".join(paragraph_properties)
                 if paragraph_properties else "")
        run_properties = '<w:lang w:val="%s"' % _escape(language)
        if rtl:
            run_properties += ' w:bidi="%s"' % _escape(language)
        run_properties += "/>"
        if rtl:
            run_properties += "<w:rtl/>"
        body.append(
            "<w:p>%s<w:r><w:rPr>%s</w:rPr>"
            "<w:t xml:space=\"preserve\">%s</w:t></w:r></w:p>"
            % (style, run_properties, _escape(text)))
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<w:document xmlns:w="%s"><w:body>\n%s\n</w:body></w:document>\n'
        % (_W_NS, "\n".join(body)))

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _DOCX_CONTENT_TYPES)
        archive.writestr("_rels/.rels", _DOCX_RELS)
        archive.writestr("word/_rels/document.xml.rels", _DOCX_DOC_RELS)
        archive.writestr("word/styles.xml", _docx_styles())
        archive.writestr("word/document.xml", document)


# ----- PDF -----------------------------------------------------------------

def write_pdf(book, path, show_panel_labels=True, language="en"):
    """Save the book as a tagged PDF.

    The book's own HTML is printed by the system's Chromium browser.
    Microsoft Edge is Chromium and ships with supported Windows
    versions, so no rendering engine or fonts need to be bundled. The
    HTML language and direction are retained, allowing Chromium's text
    shaping and system-font fallback to handle Arabic and other scripts.

    There is deliberately no untagged fallback. A PDF without a
    structure tree cannot be navigated by heading, which is the main
    reason to offer this format; EPUB and Word are better alternatives
    if the browser cannot produce the accessible PDF.
    """
    if _write_tagged_pdf(book, path, show_panel_labels, language):
        return
    if _find_browser() is None:
        raise RuntimeError(
            "a tagged PDF is created using Microsoft Edge, which comes "
            "with Windows, and Edge or Chrome could not be found. Try "
            "saving as EPUB or as a Word document instead.")
    raise RuntimeError(
        "the PDF came back without the heading structure a screen reader "
        "needs, so it was not saved. Try saving as EPUB or as a Word "
        "document instead.")


# Chromium has supported tagged headless PDF output since 2020. New
# versions enable tagging by default; --export-tagged-pdf also enables
# it on older versions. Edge is included on Windows 10/11 (including
# ARM), while the other paths keep source runs useful elsewhere.
_BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""),
                 r"Microsoft\Edge\Application\msedge.exe"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""),
                 r"Google\Chrome\Application\chrome.exe"),
    "/usr/bin/microsoft-edge",
    "/usr/bin/chromium",
    "/usr/bin/google-chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def _find_browser():
    for candidate in _BROWSERS:
        if candidate and os.path.exists(candidate):
            return candidate
    for name in ("msedge", "microsoft-edge", "chrome", "chromium",
                 "google-chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


def has_structure_tree(path):
    """True when a PDF carries the tag tree a screen reader navigates."""
    try:
        import pypdfium2 as pdfium
        import pypdfium2.raw as raw
    except Exception:
        return False
    try:
        document = pdfium.PdfDocument(path)
    except Exception:
        return False
    try:
        is_tagged = getattr(raw, "FPDFCatalog_IsTagged", None)
        if is_tagged is not None and not is_tagged(document.raw):
            return False
        for page in document:
            tree = raw.FPDF_StructTree_GetForPage(page.raw)
            if not tree:
                continue
            try:
                if raw.FPDF_StructTree_CountChildren(tree) > 0:
                    return True
            finally:
                raw.FPDF_StructTree_Close(tree)
        return False
    except Exception:
        return False
    finally:
        try:
            document.close()
        except Exception:
            pass


def _write_tagged_pdf(book, path, show_panel_labels, language):
    """Print the book's HTML to a checked, tagged PDF.

    build_html supplies semantic headings plus the BCP-47 language and
    explicit RTL/LTR direction. Chromium turns that accessibility tree
    into PDF tags, shapes complex scripts such as Arabic, and falls back
    through installed fonts for characters outside the primary font.
    """
    browser = _find_browser()
    if not browser:
        return False

    document = html_export.build_html(
        book, show_panel_labels=show_panel_labels, language=language)
    workspace = tempfile.mkdtemp(prefix="amr-pdf-")
    source = os.path.join(workspace, "book.html")
    produced = os.path.join(workspace, "book.pdf")
    try:
        with open(source, "w", encoding="utf-8") as handle:
            handle.write(document)
        base_command = [
            "--disable-gpu",
            "--export-tagged-pdf",
            "--generate-pdf-document-outline",
            "--no-pdf-header-footer",
            "--no-first-run",
            "--no-default-browser-check",
            # A throwaway profile avoids disturbing, or waiting for, the
            # browser the reader may already have open.
            "--user-data-dir=" + os.path.join(workspace, "profile"),
            "--print-to-pdf=" + produced,
            pathlib.Path(source).as_uri(),
        ]
        for headless_mode in ("--headless=new", "--headless"):
            try:
                if os.path.exists(produced):
                    os.remove(produced)
                subprocess.run(
                    [browser, headless_mode] + base_command,
                    timeout=300, check=False,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                continue
            if os.path.exists(produced) and has_structure_tree(produced):
                shutil.copyfile(produced, path)
                return True
        return False
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


# ----- what the menus offer ------------------------------------------------

# label, extension, wildcard, writer
FORMATS = [
    ("Text file", ".txt", "Text files (*.txt)|*.txt", write_text),
    ("HTML", ".html", "HTML files (*.html)|*.html", write_html),
    ("EPUB book", ".epub", "EPUB books (*.epub)|*.epub", write_epub),
    ("Word document", ".docx",
     "Word documents (*.docx)|*.docx", write_docx),
    ("PDF", ".pdf", "PDF files (*.pdf)|*.pdf", write_pdf),
]
