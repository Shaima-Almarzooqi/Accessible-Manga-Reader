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
  PDF   a document outline (the bookmarks pane), a title and a language.
        Note that this is NOT a tagged (PDF/UA) file: producing one
        needs commercial tooling. Saving the Word export as PDF from
        Word gives a fully tagged file if that is required.
  HTML  handled by core.html_export.
  TXT   plain text, from the book's own full_text().
"""

import os
import xml.sax.saxutils as _xml
import zipfile

from . import html_export, prompts


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
            book, show_panel_labels=show_panel_labels, language=language))


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
    links = []
    for index, (kind, text) in enumerate(items):
        if kind == "h2":
            links.append('<li><a href="content.xhtml#p%d">%s</a></li>'
                         % (index, _escape(text)))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"\n'
        '      xmlns:epub="http://www.idpf.org/2007/ops" lang="%s"'
        ' xml:lang="%s">\n'
        "<head><title>Contents</title></head>\n"
        "<body>\n"
        '<nav epub:type="toc" id="toc"><h1>Contents</h1>\n'
        "<ol>\n%s\n</ol>\n</nav>\n"
        "</body>\n</html>\n"
        % (language, language, "\n".join(links)))


def write_epub(book, path, show_panel_labels=True, language="en"):
    """Save the book as an EPUB.

    Written by hand rather than with a library: an EPUB is a zip of XHTML
    plus a little metadata, and doing it here keeps the app dependency
    free and the markup exactly as accessible as we want it.
    """
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
        '<html xmlns="http://www.w3.org/1999/xhtml" lang="%s" xml:lang="%s">\n'
        "<head><title>%s</title></head>\n<body>\n%s\n</body>\n</html>\n"
        % (language, language, _escape(title), "\n".join(body_parts)))

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
    items = book_outline(book, show_panel_labels=show_panel_labels)
    body = []
    for kind, text in items:
        style = "" if kind == "p" else (
            '<w:pPr><w:pStyle w:val="Heading%s"/></w:pPr>' % kind[1])
        body.append(
            "<w:p>%s<w:r><w:rPr><w:lang w:val=\"%s\"/></w:rPr>"
            "<w:t xml:space=\"preserve\">%s</w:t></w:r></w:p>"
            % (style, _escape(language), _escape(text)))
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

# A PDF's built-in fonts only cover Latin-1, which fails on something as
# ordinary as a curly apostrophe, never mind Arabic or Japanese. A font
# is borrowed from the system rather than bundled, to keep the download
# small. Arial and Segoe UI both cover Latin, Greek, Cyrillic, Arabic
# and Hebrew; the CJK fonts are added as fallbacks for anything they
# miss. The non-Windows paths matter when the app is run from source.
# Each entry is (regular, bold). Bold is optional: without it headings
# are still larger, and the outline is what carries navigation anyway.
_UNICODE_FONTS = [
    (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
    (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\segoeuib.ttf"),
    (r"C:\Windows\Fonts\tahoma.ttf", r"C:\Windows\Fonts\tahomabd.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", None),
]

_FALLBACK_FONTS = [
    r"C:\Windows\Fonts\msgothic.ttc",     # Japanese
    r"C:\Windows\Fonts\malgun.ttf",       # Korean
    r"C:\Windows\Fonts\simsun.ttc",       # Simplified Chinese
    r"C:\Windows\Fonts\msjh.ttc",         # Traditional Chinese
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
]

# Used only when no Unicode font can be found at all, so that an export
# still succeeds instead of failing on punctuation.
_PLAIN_EQUIVALENTS = {
    0x2018: "'", 0x2019: "'", 0x201A: "'", 0x201B: "'",
    0x201C: '"', 0x201D: '"', 0x201E: '"', 0x2032: "'", 0x2033: '"',
    0x2013: "-", 0x2014: "--", 0x2212: "-", 0x2026: "...",
    0x00A0: " ", 0x2022: "*", 0x00AB: '"', 0x00BB: '"',
}


def _existing(paths):
    return [p for p in paths if os.path.exists(p)]


def _register_pdf_fonts(pdf):
    """Give the document a Unicode font plus fallbacks.

    Returns (family, bold_available). family is None when the system has
    none of the fonts we know about, and the caller must fall back to a
    built-in Latin-1 font.
    """
    regular = bold = None
    for candidate, candidate_bold in _UNICODE_FONTS:
        if os.path.exists(candidate):
            regular = candidate
            if candidate_bold and os.path.exists(candidate_bold):
                bold = candidate_bold
            break
    if regular is None:
        return None, False

    pdf.add_font("body", fname=regular)
    has_bold = False
    if bold:
        try:
            pdf.add_font("body", style="B", fname=bold)
            has_bold = True
        except Exception:
            has_bold = False

    fallbacks = []
    for index, font in enumerate(_existing(_FALLBACK_FONTS)):
        name = "fallback%d" % index
        try:
            pdf.add_font(name, fname=font)
        except Exception:
            continue  # a font we cannot read is simply not offered
        fallbacks.append(name)
    if fallbacks:
        pdf.set_fallback_fonts(fallbacks)
    return "body", has_bold


def _plain(text):
    """Text reduced to what a built-in PDF font can render."""
    text = text.translate(_PLAIN_EQUIVALENTS)
    return text.encode("latin-1", "replace").decode("latin-1")


def _write_block(pdf, text, height, unicode_ok):
    """Write one paragraph or heading, never failing on a character.

    Even with fallbacks a glyph may be missing everywhere, which fpdf2
    reports rather than silently dropping. Losing a character is a far
    better outcome than losing the whole export.
    """
    if not unicode_ok:
        text = _plain(text)
    try:
        pdf.multi_cell(0, height, text, new_x="LMARGIN", new_y="NEXT")
    except Exception:
        try:
            pdf.multi_cell(0, height, _plain(text),
                           new_x="LMARGIN", new_y="NEXT")
        except Exception:
            pass  # skip a line rather than abandon the document


def write_pdf(book, path, show_panel_labels=True, language="en"):
    """Save the book as a PDF with a navigable outline.

    Every page and panel heading becomes an outline entry, so a PDF
    reader's bookmarks pane can be used to jump around the book. The
    document also carries a title and a language, and the text runs in a
    single column so reading order is unambiguous.

    This is not a tagged (PDF/UA) file -- see the module docstring.
    """
    from fpdf import FPDF  # imported lazily: only this export needs it

    items = book_outline(book, show_panel_labels=show_panel_labels)
    title = book.title or "Book"

    pdf = FPDF()
    pdf.set_title(title)
    pdf.set_lang(language)
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    family, has_bold = _register_pdf_fonts(pdf)
    unicode_ok = family is not None
    if not unicode_ok:
        family, has_bold = "helvetica", True
    heading_style = "B" if has_bold else ""

    for kind, text in items:
        if kind == "p":
            pdf.set_font(family, size=11)
            _write_block(pdf, text, 6, unicode_ok)
            pdf.ln(2)
            continue
        level = int(kind[1])
        pdf.start_section(_plain(text) if not unicode_ok else text,
                          level=level - 1)
        pdf.set_font(family, style=heading_style,
                     size={1: 18, 2: 14, 3: 12}[level])
        _write_block(pdf, text, 8, unicode_ok)
        pdf.ln(2)
    pdf.output(path)


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
