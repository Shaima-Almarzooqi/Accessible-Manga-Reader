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
import time
import xml.sax.saxutils as _xml
import zipfile

from . import config, html_export, prompts


def _escape(text):
    return _xml.escape(text or "")


def _paragraph_lines(text):
    """Non-empty lines of a script, each of which becomes a paragraph."""
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def book_outline(book, show_panel_labels=True, pages=None):
    """The book as a flat list of (kind, text) items.

    kind is "h1", "h2", "h3" or "p". Keeping this in one place means the
    EPUB, Word and PDF exports cannot drift apart from one another.

    `pages` limits the result to those page numbers. Page headings keep
    the book's real numbering, so a range still reads "Page 12 of 189"
    rather than renumbering from one and losing the reader's place.
    """
    items = [("h1", book.title or "Book")]
    wanted = None if pages is None else set(pages)
    for number in range(1, book.page_count + 1):
        if wanted is not None and number not in wanted:
            continue
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
    # dir="auto" per block: the book's text and the chosen output
    # language can disagree, and forcing one direction on everything
    # puts punctuation at the wrong end and runs words together.
    body_parts = []
    for index, (kind, text) in enumerate(items):
        if kind == "h2":
            body_parts.append('<h2 id="p%d" dir="auto">%s</h2>'
                              % (index, _escape(text)))
        elif kind == "p":
            body_parts.append('<p dir="auto">%s</p>' % _escape(text))
        else:
            body_parts.append('<%s dir="auto">%s</%s>'
                              % (kind, _escape(text), kind))

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

def write_pdf(book, path, show_panel_labels=True, language="en",
              diagnostics=None):
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
    if diagnostics is None:
        diagnostics = {}
    if _write_tagged_pdf(
            book, path, show_panel_labels, language, diagnostics):
        return
    if _find_browser() is None:
        raise RuntimeError(
            "a tagged PDF is created using Microsoft Edge, which comes "
            "with Windows, and Edge or Chrome could not be found. Try "
            "saving as EPUB or as a Word document instead.")
    raise RuntimeError(_pdf_failure_message(diagnostics))


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


def _find_browsers():
    """Every installed supported browser, in preferred order."""
    found = []
    for candidate in _BROWSERS:
        if candidate and os.path.exists(candidate):
            found.append(os.path.normcase(os.path.abspath(candidate)))
    for name in ("msedge", "microsoft-edge", "chrome", "chromium",
                 "google-chrome"):
        candidate = shutil.which(name)
        if candidate:
            found.append(os.path.normcase(os.path.abspath(candidate)))
    # A browser can be found both at its standard path and on PATH.
    # dict preserves discovery order while removing duplicates.
    return list(dict.fromkeys(found))


def _find_browser():
    """The preferred installed browser, retained for callers/tests."""
    browsers = _find_browsers()
    return browsers[0] if browsers else None


def has_structure_tree(path, diagnostics=None):
    """True when a PDF carries the tag tree a screen reader navigates."""
    if diagnostics is None:
        diagnostics = {}
    try:
        import pypdfium2 as pdfium
        import pypdfium2.raw as raw
        diagnostics["validator"] = "pypdfium2"
    except Exception as error:
        diagnostics["validator_error"] = (
            "%s: %s" % (type(error).__name__, error))
        return False
    try:
        document = pdfium.PdfDocument(path)
        diagnostics["pdf_pages"] = len(document)
    except Exception as error:
        diagnostics["validator_error"] = (
            "%s: %s" % (type(error).__name__, error))
        return False
    try:
        is_tagged = getattr(raw, "FPDFCatalog_IsTagged", None)
        if is_tagged is not None:
            diagnostics["catalog_tagged"] = bool(is_tagged(document.raw))
            if not diagnostics["catalog_tagged"]:
                return False
        child_counts = []
        for page_number in range(len(document)):
            page = document[page_number]
            try:
                tree = raw.FPDF_StructTree_GetForPage(page.raw)
                if not tree:
                    child_counts.append(0)
                    continue
                try:
                    count = raw.FPDF_StructTree_CountChildren(tree)
                    child_counts.append(count)
                    if count > 0:
                        diagnostics["structure_children"] = child_counts
                        return True
                finally:
                    raw.FPDF_StructTree_Close(tree)
            finally:
                page.close()
        diagnostics["structure_children"] = child_counts
        return False
    except Exception as error:
        diagnostics["validator_error"] = (
            "%s: %s" % (type(error).__name__, error))
        return False
    finally:
        try:
            document.close()
        except Exception:
            pass


def _write_tagged_pdf(book, path, show_panel_labels, language,
                      diagnostics=None):
    """Print the book's HTML to a checked, tagged PDF.

    build_html supplies semantic headings plus the BCP-47 language and
    explicit RTL/LTR direction. Chromium turns that accessibility tree
    into PDF tags, shapes complex scripts such as Arabic, and falls back
    through installed fonts for characters outside the primary font.
    """
    if diagnostics is None:
        diagnostics = {}
    browsers = _find_browsers()
    diagnostics["browsers"] = browsers
    diagnostics["browser"] = browsers[0] if browsers else None
    diagnostics["attempts"] = []
    if not browsers:
        diagnostics["success"] = False
        return False

    language = config.language_code(language)
    diagnostics["language"] = language
    diagnostics["direction"] = (
        "rtl" if config.is_rtl(language) else "ltr")
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
            # No --generate-pdf-document-outline. It turns every heading
            # into a bookmark, and a full volume has well over a thousand
            # panel headings; a reader has to build that whole tree
            # before showing the first page, which made the file slow to
            # open. Nothing is lost for navigation: a screen reader moves
            # by heading using the tag tree, which is what makes this
            # export worth having.
            "--no-pdf-header-footer",
            "--no-first-run",
            "--no-default-browser-check",
            "--print-to-pdf=" + produced,
            pathlib.Path(source).as_uri(),
        ]
        # Tagging is the default in current Chromium. The explicit switch
        # is retained as a retry for older versions and managed installs;
        # the final attempt also uses the legacy headless spelling.
        browser_attempts = (
            ("--headless=new", False),
            ("--headless=new", True),
            ("--headless", True),
        )
        attempt_number = 0
        for browser in browsers:
            for headless_mode, legacy_tagging in browser_attempts:
                attempt_number += 1
                attempt = {
                    "browser": browser,
                    "headless_mode": headless_mode,
                    "tagging_mode": (
                        "legacy-switch" if legacy_tagging else "default"),
                }
                diagnostics["attempts"].append(attempt)
                try:
                    if os.path.exists(produced):
                        os.remove(produced)
                    # Each retry gets its own profile. A Chromium child
                    # process can briefly keep the previous profile locked
                    # even after its command returns.
                    profile = os.path.join(
                        workspace, "profile-%d" % attempt_number)
                    command = [
                        browser, headless_mode,
                        "--user-data-dir=" + profile]
                    if legacy_tagging:
                        command.append("--export-tagged-pdf")
                    completed = subprocess.run(
                        command + base_command,
                        timeout=300, check=False,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, encoding="utf-8", errors="replace")
                    attempt["return_code"] = completed.returncode
                    if completed.stdout:
                        attempt["stdout"] = completed.stdout[-2000:]
                    if completed.stderr:
                        attempt["stderr"] = completed.stderr[-2000:]
                except Exception as error:
                    attempt["browser_error"] = (
                        "%s: %s" % (type(error).__name__, error))
                    continue
                attempt["output_exists"] = os.path.exists(produced)
                if attempt["output_exists"]:
                    attempt["output_bytes"] = os.path.getsize(produced)
                tagged = False
                if attempt["output_exists"]:
                    # Normally the browser has fully closed the file when
                    # it exits. Antivirus scanning can briefly make a
                    # fresh PDF unreadable, so retry only load errors.
                    for validation_number in range(3):
                        validation = {}
                        attempt["validation"] = validation
                        tagged = has_structure_tree(produced, validation)
                        if tagged or "validator_error" not in validation:
                            break
                        if validation_number < 2:
                            time.sleep(0.25 * (validation_number + 1))
                if tagged:
                    shutil.copyfile(produced, path)
                    diagnostics["success"] = True
                    diagnostics["selected_browser"] = browser
                    diagnostics["selected_mode"] = headless_mode
                    diagnostics["selected_tagging"] = (
                        attempt["tagging_mode"])
                    return True
        diagnostics["success"] = False
        return False
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def _pdf_failure_message(diagnostics):
    """Turn detailed renderer diagnostics into a useful short error."""
    attempts = diagnostics.get("attempts", [])
    browser_names = []
    for attempt in attempts:
        name = _browser_display_name(attempt.get("browser"))
        if name and name not in browser_names:
            browser_names.append(name)
    browser_list = " and ".join(browser_names) or "The browser"
    validation_errors = [
        attempt.get("validation", {}).get("validator_error")
        for attempt in attempts
        if attempt.get("validation", {}).get("validator_error")
    ]
    if validation_errors:
        return (
            "%s created a PDF, but this app build could not verify its "
            "heading structure (%s). It was not saved. Try saving as EPUB "
            "or as a Word document instead."
            % (browser_list, validation_errors[-1]))
    produced = [attempt for attempt in attempts
                if attempt.get("output_exists")]
    if produced:
        return (
            "%s created a PDF, but it did not contain the heading "
            "structure a screen reader needs, so it was not saved. Try "
            "saving as EPUB or as a Word document instead." % browser_list)
    if attempts:
        last = attempts[-1]
        detail = last.get("browser_error")
        if not detail:
            return_code = last.get("return_code")
            last_browser = _browser_display_name(last.get("browser"))
            if return_code == 0:
                detail = "%s reported success but produced no PDF" % (
                    last_browser or "the last browser")
            else:
                detail = "%s returned exit code %s" % (
                    last_browser or "the last browser",
                    return_code if return_code is not None else "unknown")
        return (
            "%s could not create the PDF (%s). Try saving as EPUB or as "
            "a Word document instead." % (browser_list, detail))
    return (
        "The browser could not create a tagged PDF. Try saving as EPUB "
        "or as a Word document instead.")


def _browser_display_name(path):
    """A short user-facing name for a browser executable path."""
    if not path:
        return None
    name = os.path.basename(path).lower()
    if "edge" in name:
        return "Microsoft Edge"
    if "chrome" in name:
        return "Google Chrome"
    if "chromium" in name:
        return "Chromium"
    return os.path.basename(path)


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
