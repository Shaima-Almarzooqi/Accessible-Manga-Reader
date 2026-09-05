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
        # The output language this book was processed in. Exports
        # use it rather than the current setting, which may have
        # changed since, so a book is never labelled as a language
        # its text is not in.
        self.output_language = ""
        self.user_instructions = ""  # reader-provided guidance for the AI
        self.last_position = 0  # caret offset in full-book view
        self.last_page = 1
        self.last_panel = 0
        # Where this book sits in the library. Zero means "never
        # moved", so a library nobody has reordered still comes out in
        # title order exactly as before.
        self.position = 0

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
            "output_language": self.output_language,
            "user_instructions": self.user_instructions,
            "last_position": self.last_position,
            "last_page": self.last_page,
            "last_panel": self.last_panel,
            "position": self.position,
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
            book.output_language = data.get("output_language", "")
            book.user_instructions = data.get("user_instructions", "")
            book.source_kind = data.get("source_kind", "book")
            book.last_position = int(data.get("last_position", 0))
            book.last_page = int(data.get("last_page", 1))
            book.last_panel = int(data.get("last_panel", 0))
            book.position = int(data.get("position", 0))
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

    def has_page_images(self):
        """Whether the extracted page images are still on disk. They are
        only needed for processing; reading works from the cached
        scripts alone."""
        pages_dir = os.path.join(self.workspace, "pages")
        if not os.path.isdir(pages_dir):
            return False
        return any(name.lower().endswith(".jpg")
                   for name in os.listdir(pages_dir))

    def page_images_size(self):
        """Total size in bytes of the stored page images."""
        pages_dir = os.path.join(self.workspace, "pages")
        if not os.path.isdir(pages_dir):
            return 0
        total = 0
        for name in os.listdir(pages_dir):
            try:
                total += os.path.getsize(os.path.join(pages_dir, name))
            except OSError:
                pass
        return total

    def delete_page_images(self):
        """Remove the stored page images, keeping the scripts. The book
        stays fully readable; processing again requires re-importing."""
        import shutil
        pages_dir = os.path.join(self.workspace, "pages")
        shutil.rmtree(pages_dir, ignore_errors=True)

    def unprocessed_pages(self):
        """Page numbers (1-based) that do not yet have a cached script."""
        return [n for n in range(1, self.page_count + 1) if n not in self.scripts]

    def clear_pages(self, page_numbers):
        """Drop the cached scripts for `page_numbers` so they will be
        processed again. Returns the page numbers actually cleared.

        Character notes are left alone here: a page in the middle of a
        book still needs the AI to know the cast. Callers redoing the
        whole book clear the notes themselves, since those are rebuilt
        from page one.
        """
        cleared = []
        for number in page_numbers:
            if number in self.scripts:
                del self.scripts[number]
                cleared.append(number)
        return cleared

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
            # No decoration: a screen reader would read the equals
            # signs aloud on every page turn.
            lines.append("Page %d of %d" % (n, self.page_count))
            script = self.scripts.get(n)
            lines.append(script if script else "(This page has not been processed yet.)")
            lines.append("")
        return "\n".join(lines)


def list_books():
    """All books in the library, in the order they should be shown.

    By where they have been moved to, then by title. A library nobody
    has reordered has every position at zero, so it still comes out
    alphabetically, exactly as it did before moving was possible.
    """
    books = []
    root = config.books_dir()
    for name in sorted(os.listdir(root)):
        workspace = os.path.join(root, name)
        if os.path.isdir(workspace) and os.path.exists(
                os.path.join(workspace, "book.json")):
            books.append(Book.load(workspace))
    books.sort(key=lambda b: (b.position or 0, b.title.lower()))
    return books


def current_page_of(book, reader=None):
    """The page a range should start from.

    The page open in the reader when there is one, otherwise the page
    the book was last left on. Starting every range at page one means
    retyping the number you are already looking at.
    """
    page = getattr(reader, "current_page", None)
    if not page:
        page = getattr(book, "last_page", 1)
    try:
        page = int(page)
    except (TypeError, ValueError):
        return 1
    return max(1, min(page, max(1, getattr(book, "page_count", 1))))


def range_for_scope(scope, current_page, page_count):
    """The page numbers a range should show for the chosen scope.

    The From and To fields stay enabled whatever is selected, because a
    disabled control is skipped by Tab and its value is not announced.
    That means they are read out even when the choice is the whole
    book, so they have to agree with it rather than still showing where
    the reader happened to be.
    """
    last = max(1, int(page_count or 1))
    page = max(1, min(int(current_page or 1), last))
    if scope == "whole":
        return 1, last
    if scope == "current":
        return page, page
    return page, last


def move_book(book, direction, books=None):
    """Move a book one place up or down the library.

    Returns the new list of books in order, or None when the book is
    already at that end and cannot move -- which the caller reports as
    a bell rather than a message, since pressing the key repeatedly to
    reach the top is a normal thing to do.

    Positions are renumbered from one across the whole library, but
    only the books whose number actually changed are written back. The
    first move writes every book, because until then they are all
    zero; after that a move touches two.
    """
    books = list(books if books is not None else list_books())
    here = None
    for index, other in enumerate(books):
        if other.workspace == book.workspace:
            here = index
            break
    if here is None:
        return None
    target = here + direction
    if not 0 <= target < len(books):
        return None
    books[here], books[target] = books[target], books[here]
    for index, other in enumerate(books, start=1):
        if other.position != index:
            other.position = index
            other.save()
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
    # A new book joins the end of an arranged library rather than the
    # front. Position zero would sort it above everything, which puts
    # the newest import ahead of an order the reader chose on purpose.
    # In a library nobody has arranged every position is still zero, so
    # this stays out of the way and titles decide as before.
    book.position = next_position()
    book.save()
    return book


def next_position():
    """One past the last arranged book, or zero if none are arranged."""
    highest = 0
    for other in list_books():
        highest = max(highest, other.position or 0)
    return highest + 1 if highest else 0


def delete_book(book):
    """Remove a book and all its cached data from disk."""
    import shutil
    shutil.rmtree(book.workspace, ignore_errors=True)
