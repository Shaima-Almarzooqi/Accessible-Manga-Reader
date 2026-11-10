"""Character banks shared by every book in a series.

A book's character notes are built up as it is processed and then
thrown away at the book boundary, so volume 2 of a series starts
knowing nothing that volume 1 learned. Measured on one volume, a model
reading a page with no notes named the right speaker 28% of the time,
and 50% once it had them. Every later volume currently starts at the
lower figure.

A series bank is those notes, plus optional reference pictures, kept
against the series rather than the book, so the second volume opens
with what the first one worked out.

Pictures are cut from the reader's own pages rather than fetched from
anywhere, and each one carries a description in words. A reader who
cannot see the picture can still read its description and tell that
the entry filed under one character shows somebody else, which is the
only way a wrong picture can ever be noticed. A picture without a
description is a silent fault that would degrade every later volume.

This module is storage and text only: no wx, no network.
"""

import json
import os
import re

from . import config, diagnostics

# Volume, chapter and batch markers that belong to one book rather than
# to the series. "Riverside Diary v14 (2012)" and "Riverside Diary v15" are
# the same series; the suffix is what differs.
_BOOK_MARKERS = re.compile(
    r"""(?ix)
    \s*(?:
        [\[(][^\])]*[\])]        # (2012), [Digital], (Batch 2)
      | \b(?:v|vol|volume|ch|chapter|part|pt|book|episode|ep)\s*\.?\s*\d+
      | \#\s*\d+
      | \bbatch\s*\d+
    )\s*$
    """)
_TRAILING_JUNK = re.compile(r"[\s\-–—_,:;.]+$")
_UNSAFE = re.compile(r"[^A-Za-z0-9]+")

MAX_PICTURES_PER_CHARACTER = 6


def series_name_from_title(title):
    """The series a book title belongs to, with the book part removed.

    Applied repeatedly, because a title often carries more than one
    marker: "Riverside Diary v14 (2012)" has both a volume and a year.
    Anything left empty falls back to the original title, since a
    series called "" would collect every unnamed book together.
    """
    name = (title or "").strip()
    while True:
        trimmed = _BOOK_MARKERS.sub("", name)
        trimmed = _TRAILING_JUNK.sub("", trimmed)
        if trimmed == name:
            break
        name = trimmed
    name = name.strip()
    return name or (title or "").strip()


def slug(name):
    """A folder name for a series.

    Case, punctuation and accents are ignored, so "Riverside Diary",
    "riverside diary!" and "Wé Were There" are one series.

    A title written in Japanese, Korean or Chinese leaves nothing
    behind once non-Latin characters are removed, and every such title
    would then share the folder "series" and overwrite the last one. So
    a short hash of the name is appended whenever too little survives
    to tell two titles apart.
    """
    import hashlib
    import unicodedata

    text = (name or "").strip()
    flattened = "".join(
        ch for ch in unicodedata.normalize("NFKD", text.lower())
        if not unicodedata.combining(ch))
    cleaned = _UNSAFE.sub("-", flattened).strip("-")
    if len(cleaned) >= 3:
        return cleaned
    if not text:
        return "series"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
    return "%s-%s" % (cleaned, digest) if cleaned else "series-%s" % digest


def series_dir():
    """The folder holding every series bank, created on first use."""
    path = os.path.join(config.data_dir(), "series")
    os.makedirs(path, exist_ok=True)
    return path


def _record_path(name):
    return os.path.join(series_dir(), slug(name), "series.json")


def pictures_dir(name):
    """Where one series' reference pictures live."""
    path = os.path.join(series_dir(), slug(name), "pictures")
    os.makedirs(path, exist_ok=True)
    return path


def blank_series(name):
    return {"name": (name or "").strip(), "characters": []}


def load_series(name):
    """One series bank, or an empty one if it has never been saved."""
    try:
        with open(_record_path(name), "r", encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        return blank_series(name)
    if not isinstance(record, dict):
        return blank_series(name)
    record.setdefault("name", (name or "").strip())
    characters = record.get("characters")
    record["characters"] = [c for c in characters
                            if isinstance(c, dict) and c.get("name")] \
        if isinstance(characters, list) else []
    for character in record["characters"]:
        character.setdefault("description", "")
        pictures = character.get("pictures")
        character["pictures"] = [p for p in pictures
                                 if isinstance(p, dict) and p.get("file")] \
            if isinstance(pictures, list) else []
    return record


def save_series(record):
    """Write a bank, replacing any earlier one for the same series."""
    name = (record or {}).get("name", "").strip()
    if not name:
        raise ValueError("A series bank needs a name.")
    path = _record_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)
    os.replace(temporary, path)
    pictures = sum(len(c.get("pictures") or [])
                   for c in record.get("characters", []))
    diagnostics.write("bank", "series saved", series=name,
                      characters=len(record.get("characters", [])),
                      pictures=pictures)


def list_series():
    """Every saved bank, by name, with how much each holds."""
    out = []
    root = series_dir()
    for folder in sorted(os.listdir(root)):
        path = os.path.join(root, folder, "series.json")
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                record = json.load(handle)
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict) or not record.get("name"):
            continue
        characters = record.get("characters") or []
        out.append({
            "name": record["name"],
            "characters": len(characters),
            "pictures": sum(len(c.get("pictures") or [])
                            for c in characters if isinstance(c, dict)),
        })
    return sorted(out, key=lambda item: item["name"].lower())


def delete_series(name):
    """Remove a bank and the pictures stored with it."""
    import shutil

    folder = os.path.join(series_dir(), slug(name))
    diagnostics.write("bank", "series deleted", series=name)
    if os.path.isdir(folder):
        shutil.rmtree(folder, ignore_errors=True)


def _words(name):
    return frozenset(w for w in _UNSAFE.split((name or "").lower()) if w)


def find_character(record, name):
    """The character entry for this name.

    The model names the same person several ways in one book: Mira,
    Mira Alcott, Alcott. Matching only on the exact string
    would file those as three characters, so a name whose words are
    contained in a stored name (or the reverse) counts as the same
    person.

    Where two stored characters would both match -- siblings sharing a
    surname, say -- nothing is returned rather than a guess, because
    filing a line under the wrong sibling is worse than leaving the
    name unrecognised.
    """
    wanted = _words(name)
    if not wanted:
        return None
    characters = record.get("characters", [])
    for character in characters:
        if _words(character.get("name")) == wanted:
            return character
    loose = [c for c in characters
             if _words(c.get("name")) and (
                 wanted < _words(c.get("name"))
                 or _words(c.get("name")) < wanted)]
    return loose[0] if len(loose) == 1 else None


def set_character(record, name, description="", chosen_by_reader=False):
    """Add a character, or update an existing one.

    An existing description is kept when the new one is blank, so
    merging a later book's notes cannot wipe out what an earlier one
    recorded.

    `chosen_by_reader` marks a name somebody typed. Scripts call a
    character whatever the bank calls them, so a reader who shortens
    Dorian Vale to Vale is deciding how every later volume will read.
    Without this, the next book to mention his full name would match
    that entry, see a longer name, and quietly undo the choice.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("A character needs a name.")
    character = find_character(record, name)
    if character is None:
        character = {"name": name, "description": (description or "").strip(),
                     "pictures": []}
        if chosen_by_reader:
            character["chosen_by_reader"] = True
        record.setdefault("characters", []).append(character)
        return character
    if chosen_by_reader:
        character["name"] = name
        character["chosen_by_reader"] = True
    elif (not character.get("chosen_by_reader")
          and len(_words(name)) > len(_words(character.get("name")))):
        # Keep the fuller name: a later book calling him Dorian Vale
        # should improve the entry the first one filed as Vale.
        character["name"] = name
    if (description or "").strip():
        character["description"] = description.strip()
    return character


def remove_character(record, name):
    """Drop a character. True when one was there to drop."""
    character = find_character(record, name)
    if character is None:
        return False
    record["characters"].remove(character)
    return True


def describe_picture(picture):
    """The line a reader hears for one stored picture.

    The description is what makes the bank checkable without sight, so
    a picture saved without one says so plainly rather than looking
    like any other entry.
    """
    description = (picture.get("description") or "").strip()
    source = (picture.get("source") or "").strip()
    if description and source:
        return "%s, from %s" % (description, source)
    if description:
        return description
    if source:
        return "No description, from %s" % source
    return "No description"


def add_picture(record, character_name, filename, description="",
                source=""):
    """File a reference picture against a character.

    The oldest picture is dropped once the limit is reached: every
    picture is sent with every request, so an unbounded bank would
    quietly make each request larger and slower.
    """
    character = set_character(record, character_name)
    pictures = character.setdefault("pictures", [])
    pictures[:] = [p for p in pictures if p.get("file") != filename]
    pictures.append({"file": filename,
                     "description": (description or "").strip(),
                     "source": (source or "").strip()})
    if len(pictures) > MAX_PICTURES_PER_CHARACTER:
        del pictures[:len(pictures) - MAX_PICTURES_PER_CHARACTER]
    return character


def remove_picture(record, character_name, filename):
    """Drop one picture. True when one was there to drop."""
    character = find_character(record, character_name)
    if character is None:
        return False
    pictures = character.get("pictures") or []
    remaining = [p for p in pictures if p.get("file") != filename]
    if len(remaining) == len(pictures):
        return False
    character["pictures"] = remaining
    return True


# The format the app already uses for a book's character notes, so a
# bank can be handed to the AI through the same path.
_NOTE_LINE = re.compile(r"^\s*[-*•]\s*([^:]{1,60}?)\s*:\s*(.*)$")


def notes_from_text(text):
    """Pull "- Name: description" lines out of a notes block."""
    found = []
    for line in (text or "").split("\n"):
        if line.strip().upper().startswith("LABELS"):
            continue
        match = _NOTE_LINE.match(line)
        if not match:
            continue
        name = match.group(1).strip()
        if not name or name.upper() == name and len(name.split()) > 4:
            continue
        found.append((name, match.group(2).strip()))
    return found


def merge_notes(record, text):
    """Fold a book's character notes into the series bank.

    Returns the names that were new, which is what the app shows when
    it offers to save them.
    """
    added = []
    for name, description in notes_from_text(text):
        if find_character(record, name) is None:
            added.append(name)
        set_character(record, name, description)
    return added


def notes_text(record):
    """The bank written back out as a character notes block.

    This is what gets sent to the AI, in the same shape the model
    already writes and already reads, so nothing else has to change.
    """
    lines = []
    for character in record.get("characters", []):
        name = character.get("name", "").strip()
        if not name:
            continue
        description = (character.get("description") or "").strip()
        lines.append("- %s: %s" % (name, description) if description
                     else "- %s" % name)
    return "\n".join(lines)


# A bank holds the whole recurring cast, but every picture in it would
# otherwise be sent with every request. Twenty characters at six
# pictures each is a hundred and twenty images on each call: slower,
# dearer, and refused outright by a busy service. So storage is
# unbounded and sending is not.
PICTURES_SENT_PER_CHARACTER = 1
PICTURES_SENT_IN_TOTAL = 12


def promote_picture(record, character_name, filename):
    """Move a picture to the front, making it the one that is sent.

    A character may be stored with several pictures -- in costume and
    out of it, front and profile, as the art changes over a long
    series -- but only the first is sent. This is how a reader chooses
    which, using the same Move up idea as the book list.
    """
    character = find_character(record, character_name)
    if character is None:
        return False
    pictures = character.get("pictures") or []
    for index, picture in enumerate(pictures):
        if picture.get("file") == filename:
            pictures.insert(0, pictures.pop(index))
            return True
    return False


def notes_for_book(record, book_notes):
    """The character notes to send: the series bank, book's own on top.

    A book keeps learning as it is read, so what it has worked out
    about a character is newer than what the series bank holds and
    wins where the two disagree. Characters the book has not met yet
    still come through from the bank, which is the whole point: a
    second volume opens knowing the cast.
    """
    merged = blank_series(record.get("name", ""))
    for source in (notes_text(record), book_notes):
        for name, description in notes_from_text(source):
            set_character(merged, name, description)
    return notes_text(merged)


def names_in_notes(text):
    """Just the character names out of a notes block."""
    return [name for name, _description in notes_from_text(text)]


def pictures_for_prompt(record, names=None,
                        per_character=PICTURES_SENT_PER_CHARACTER,
                        total=PICTURES_SENT_IN_TOTAL):
    """The pictures to send, as (path, character name, description).

    `names` orders rather than filters: characters the book has
    already mentioned come first, then the rest of the bank. A filter
    would be wrong at the start of a volume, when the book has
    mentioned nobody yet and the bank is the only thing that knows the
    cast -- which is the case the whole feature exists for. The cap is
    what keeps a long series from sending everyone.

    Within each group the bank's own order is kept, so two runs of the
    same book send the same pictures in the same order.
    """
    folder = os.path.join(series_dir(), slug(record.get("name", "")),
                          "pictures")
    wanted = [n for n in (names or []) if (n or "").strip()]

    def mentioned(character):
        return any(find_character({"characters": [character]}, n) is not None
                   for n in wanted)

    characters = record.get("characters", [])
    ordered = ([c for c in characters if mentioned(c)]
               + [c for c in characters if not mentioned(c)]) \
        if wanted else characters

    out = []
    for character in ordered:
        name = character.get("name", "").strip()
        taken = 0
        for picture in character.get("pictures") or []:
            if taken >= per_character or len(out) >= total:
                break
            path = os.path.join(folder, picture.get("file", ""))
            if os.path.exists(path):
                out.append((path, name,
                            (picture.get("description") or "").strip()))
                taken += 1
        if len(out) >= total:
            break
    return out
