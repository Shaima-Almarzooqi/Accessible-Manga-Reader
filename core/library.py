"""Book library: metadata, cached scripts, and resume support.

Each book workspace contains a book.json:
{
  "title": "My Manga Vol 1",
  "source": "C:/manga/vol1.cbz",
  "page_count": 190,
  "scripts": {"1": "...", "2": "..."},   # page number -> script text
  "character_notes": "...",
  "last_position": 0                       # caret position in reader
}

book.json is written atomically after every processed batch, so an
interrupted run (crash, rate limit, cancel) can always resume from the
first unprocessed page with zero lost API spend.
"""

import json
import os

from . import config


class Book:
    def __init__(self, workspace):
        self.workspace = workspace
        self.title = ""
        self.source = ""
        self.source_kind = "book"  # "book", "pdf", "images", or "folder"
        self.page_count = 0
        self.scripts = {}  # int page number -> script text
        self.character_notes = ""
        self.user_instructions = ""  # reader-provided guidance for the AI
        self.last_position = 0  # caret offset in full-book view
        self.last_page = 1
        self.last_panel = 0

    # ----- persistence -------------------------------------------------

    @property
    def meta_path(self):
        return os.path.join(self.workspace, "book.json")

    def save(self):
        data = {
            "title": self.title,
            "source": self.source,
            "source_kind": self.source_kind,
            "page_count": self.page_count,
            "scripts": {str(k): v for k, v in self.scripts.items()},
            "character_notes": self.character_notes,
            "user_instructions": self.user_instructions,
            "last_position": self.last_position,
            "last_page": self.last_page,
            "last_panel": self.last_panel,
        }
        tmp = self.meta_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, self.meta_path)

    @classmethod
    def load(cls, workspace):
        book = cls(workspace)
        try:
            with open(book.meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            book.title = data.get("title", "")
            book.source = data.get("source", "")
            book.page_count = int(data.get("page_count", 0))
            book.scripts = {int(k): v for k, v in data.get("scripts", {}).items()}
            book.character_notes = data.get("character_notes", "")
            book.user_instructions = data.get("user_instructions", "")
            book.source_kind = data.get("source_kind", "book")
            book.last_position = int(data.get("last_position", 0))
            book.last_page = int(data.get("last_page", 1))
            book.last_panel = int(data.get("last_panel", 0))
        except (OSError, ValueError, KeyError):
            pass
        return book

    # ----- pages -------------------------------------------------------

    def page_image_path(self, page_number):
        return os.path.join(self.workspace, "pages", "%04d.jpg" % page_number)

    def detect_page_count(self):
        """Count page images on disk (source of truth after extraction)."""
        pages_dir = os.path.join(self.workspace, "pages")
        if not os.path.isdir(pages_dir):
            self.page_count = 0
            return 0
        count = len([n for n in os.listdir(pages_dir) if n.lower().endswith(".jpg")])
        self.page_count = count
        return count

    # ----- progress ----------------------------------------------------

    def unprocessed_pages(self):
        """Page numbers (1-based) that do not yet have a cached script."""
        return [n for n in range(1, self.page_count + 1) if n not in self.scripts]

    def processed_count(self):
        return len([n for n in self.scripts if 1 <= n <= self.page_count])

    def is_complete(self):
        return self.page_count > 0 and not self.unprocessed_pages()

    # ----- reading output ----------------------------------------------

    def full_text(self):
        """Assemble the whole book as one readable text document."""
        lines = []
        if self.title:
            lines.append(self.title)
            lines.append("")
        for n in range(1, self.page_count + 1):
            lines.append("=== Page %d of %d ===" % (n, self.page_count))
            script = self.scripts.get(n)
            lines.append(script if script else "(This page has not been processed yet.)")
            lines.append("")
        return "\n".join(lines)


def list_books():
    """All books in the library, sorted by title."""
    books = []
    root = config.books_dir()
    for name in sorted(os.listdir(root)):
        workspace = os.path.join(root, name)
        if os.path.isdir(workspace) and os.path.exists(
                os.path.join(workspace, "book.json")):
            books.append(Book.load(workspace))
    books.sort(key=lambda b: b.title.lower())
    return books


def create_book(book_id, title, source_description, source_kind="book"):
    """Create (or reuse) a workspace for a new book."""
    workspace = os.path.join(config.books_dir(), book_id)
    os.makedirs(workspace, exist_ok=True)
    if os.path.exists(os.path.join(workspace, "book.json")):
        book = Book.load(workspace)
        if not book.title:
            book.title = title
        return book
    book = Book(workspace)
    book.title = title
    book.source = source_description
    book.source_kind = source_kind
    book.save()
    return book


def delete_book(book):
    """Remove a book and all its cached data from disk."""
    import shutil
    shutil.rmtree(book.workspace, ignore_errors=True)
