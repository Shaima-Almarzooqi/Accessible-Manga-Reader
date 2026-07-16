"""Turn any supported source (CBZ, ZIP, PDF, folder, or a batch of image
files) into an ordered list of normalized page images inside a book
workspace directory.

Pages are resized so their longest edge is at most `image_max_dimension`
pixels and re-encoded as JPEG. This keeps API payloads small (important
for rate limits and cost) without hurting OCR/vision quality.

Workspace layout:
  <books_dir>/<book_id>/
      pages/0001.jpg, 0002.jpg, ...
      book.json          (metadata + cached scripts, managed by library.py)
"""

import hashlib
import io
import os
import re
import zipfile

from PIL import Image

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
ARCHIVE_EXTENSIONS = {".cbz", ".zip"}
PDF_EXTENSIONS = {".pdf"}


def natural_sort_key(name):
    """Sort key that orders page2 before page10 (numeric-aware)."""
    parts = re.split(r"(\d+)", name.lower())
    return [int(p) if p.isdigit() else p for p in parts]


def book_id_for_source(source_description):
    """Stable ID for a book, derived from its source description string."""
    digest = hashlib.sha1(source_description.encode("utf-8")).hexdigest()[:16]
    return digest


def _is_image_name(name):
    return os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS


def _normalize_and_save(image, out_path, max_dim, quality):
    """Resize image to fit max_dim on its longest edge and save as JPEG."""
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    width, height = image.size
    longest = max(width, height)
    if longest > max_dim:
        scale = max_dim / float(longest)
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        image = image.resize(new_size, Image.LANCZOS)
    image.save(out_path, "JPEG", quality=quality)


def _pages_dir(workspace):
    path = os.path.join(workspace, "pages")
    os.makedirs(path, exist_ok=True)
    return path


def extract_archive(archive_path, workspace, max_dim=1568, quality=85,
                    progress=None):
    """Extract images from a CBZ/ZIP file into the workspace.

    Returns the number of pages extracted. Non-image entries are ignored.
    Entries are ordered by natural sort of their full path inside the
    archive, which matches standard CBZ reading order.
    """
    pages = _pages_dir(workspace)
    count = 0
    with zipfile.ZipFile(archive_path, "r") as zf:
        names = [n for n in zf.namelist()
                 if not n.endswith("/") and _is_image_name(n)
                 and not os.path.basename(n).startswith(".")]
        names.sort(key=natural_sort_key)
        total = len(names)
        for index, name in enumerate(names, start=1):
            data = zf.read(name)
            image = Image.open(io.BytesIO(data))
            out_path = os.path.join(pages, "%04d.jpg" % index)
            _normalize_and_save(image, out_path, max_dim, quality)
            count += 1
            if progress:
                progress(index, total)
    return count


def extract_pdf(pdf_path, workspace, max_dim=1568, quality=85, progress=None):
    """Render each PDF page to an image in the workspace.

    Rendering (rather than extracting embedded images) is used because it
    is robust across every PDF structure: single-image pages, multi-image
    composites, and vector overlays all come out correctly.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise RuntimeError(
            "PDF import needs the PyMuPDF library, which is not "
            "available in this build (it publishes no Windows ARM64 "
            "package). Everything else works normally. To read a PDF, "
            "convert it to a CBZ or ZIP of page images first, or import "
            "the pages as image files.")

    pages = _pages_dir(workspace)
    doc = fitz.open(pdf_path)
    try:
        total = doc.page_count
        for index in range(total):
            page = doc.load_page(index)
            # Scale so the longest edge lands near max_dim.
            rect = page.rect
            longest = max(rect.width, rect.height)
            zoom = (max_dim / longest) if longest > 0 else 1.0
            zoom = max(0.5, min(zoom, 4.0))
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            out_path = os.path.join(pages, "%04d.jpg" % (index + 1))
            _normalize_and_save(image, out_path, max_dim, quality)
            if progress:
                progress(index + 1, total)
        return total
    finally:
        doc.close()


def extract_image_files(file_paths, workspace, max_dim=1568, quality=85,
                        progress=None):
    """Copy a batch of image files into the workspace in natural-sort order."""
    pages = _pages_dir(workspace)
    ordered = sorted(file_paths, key=lambda p: natural_sort_key(os.path.basename(p)))
    total = len(ordered)
    for index, path in enumerate(ordered, start=1):
        image = Image.open(path)
        out_path = os.path.join(pages, "%04d.jpg" % index)
        _normalize_and_save(image, out_path, max_dim, quality)
        if progress:
            progress(index, total)
    return total


def extract_folder(folder_path, workspace, max_dim=1568, quality=85,
                   progress=None):
    """Import every image directly inside a folder (non-recursive)."""
    files = [os.path.join(folder_path, n) for n in os.listdir(folder_path)
             if _is_image_name(n)]
    return extract_image_files(files, workspace, max_dim, quality, progress)


def extract_source(source, workspace, max_dim=1568, quality=85, progress=None):
    """Dispatch on source type.

    `source` may be:
      - a path to a .cbz/.zip archive
      - a path to a .pdf file
      - a path to a folder of images
      - a list of image file paths
    Returns the number of pages extracted.
    """
    if isinstance(source, (list, tuple)):
        return extract_image_files(source, workspace, max_dim, quality, progress)
    ext = os.path.splitext(source)[1].lower()
    if os.path.isdir(source):
        return extract_folder(source, workspace, max_dim, quality, progress)
    if ext in ARCHIVE_EXTENSIONS:
        return extract_archive(source, workspace, max_dim, quality, progress)
    if ext in PDF_EXTENSIONS:
        return extract_pdf(source, workspace, max_dim, quality, progress)
    raise ValueError("Unsupported source type: %s" % source)
