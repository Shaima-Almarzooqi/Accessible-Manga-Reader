"""Cutting reference pictures of characters out of the reader's pages.

The bank works because the model is shown what a character looks like:
measured on one volume, a page read with the series' pictures named
the right speaker 70% of the time against 15% to 62% without. But a
reader who cannot see the book cannot choose those pictures, and
fetching them from the internet would mean a wrong character, a
different series, or a plot spoiler from a wiki, none of which they
could detect.

So the pictures come from the book they already own. The model is
asked once, for one batch of pages, to point at each named character
it can see; the app crops those boxes itself and files them with the
model's own words as the description, which is what makes the entry
checkable by ear afterwards.

One extra request per book, and only when there are characters with
no picture yet.
"""

import json
import os
import re

from . import diagnostics, series

# Asked of the model. Plain and literal: every provider has to read it
# the same way, and a vague instruction here produces boxes that crop
# to the wrong thing.
PROMPT = (
    "Look at the pages and find each named character who is clearly "
    "visible.\n\n"
    "For each one, give a box around that character, preferring a "
    "panel where the face is large, unobstructed and not covered by a "
    "speech bubble.\n\n"
    "Answer with JSON only, in this exact shape and nothing else:\n"
    '[{"name": "character name", "page": 1, '
    '"description": "a few words about how they look", '
    '"box": [top, left, bottom, right]}]\n\n'
    "Rules for the answer:\n"
    "- Use the character names given in the character notes.\n"
    "- box numbers are between 0 and 1000, measured from the top left "
    "of that page.\n"
    "- page is the page number the box is on.\n"
    "- description is for a reader who cannot see the picture, so say "
    "hair, clothing and build in a few words. Do not say the "
    "character's name in it.\n"
    "- Leave out anybody you cannot see clearly.\n"
    "- If you can see nobody, answer with []."
)

MAX_PER_RUN = 6
MIN_SIDE = 40           # pixels; smaller crops show nothing useful
PADDING = 0.06          # a little room around the box


def parse_boxes(text):
    """The model's answer as a list of boxes, ignoring anything else.

    Models wrap JSON in prose or code fences often enough that the
    answer is searched for rather than assumed to be the whole reply.
    """
    if not text:
        return []
    candidate = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", candidate, re.S)
    if fence:
        candidate = fence.group(1).strip()
    start, end = candidate.find("["), candidate.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        data = json.loads(candidate[start:end + 1])
    except ValueError:
        return []
    if not isinstance(data, list):
        return []

    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        box = item.get("box")
        if not name or not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            top, left, bottom, right = [float(v) for v in box]
        except (TypeError, ValueError):
            continue
        if bottom <= top or right <= left:
            continue
        try:
            page = int(item.get("page", 0))
        except (TypeError, ValueError):
            page = 0
        out.append({"name": name,
                    "description": str(item.get("description", "")).strip(),
                    "page": page,
                    "box": (top, left, bottom, right)})
    return out


def crop_from_page(image_path, box, target_path):
    """Cut one box out of a page. True when something usable was saved.

    Boxes come back in thousandths of the page, top left origin. A
    crop smaller than MIN_SIDE is skipped: it would be a picture of
    nothing, and a bank entry nobody can see is worse than no entry.
    """
    from PIL import Image

    try:
        with Image.open(image_path) as page:
            page = page.convert("RGB")
            width, height = page.size
            top, left, bottom, right = box
            pad_y = (bottom - top) * PADDING
            pad_x = (right - left) * PADDING
            y1 = int(max(0.0, (top - pad_y)) / 1000.0 * height)
            x1 = int(max(0.0, (left - pad_x)) / 1000.0 * width)
            y2 = int(min(1000.0, (bottom + pad_y)) / 1000.0 * height)
            x2 = int(min(1000.0, (right + pad_x)) / 1000.0 * width)
            if x2 - x1 < MIN_SIDE or y2 - y1 < MIN_SIDE:
                return False
            page.crop((x1, y1, x2, y2)).save(target_path, "PNG")
    except Exception:
        return False
    return True


def characters_without_pictures(record, names):
    """Which of these characters the bank has no picture for yet."""
    missing = []
    for name in names:
        character = series.find_character(record, name)
        if character is None or not (character.get("pictures") or []):
            missing.append(name)
    return missing


def store(record, book, boxes, page_paths):
    """Crop what the model pointed at and file it. Returns names saved.

    A character already holding a picture is skipped, so a reader's
    own choice is never pushed aside by a later automatic one.
    """
    folder = series.pictures_dir(record.get("name", ""))
    saved = []
    for item in boxes:
        if len(saved) >= MAX_PER_RUN:
            break
        name = item["name"]
        character = series.find_character(record, name)
        if character is not None and (character.get("pictures") or []):
            continue
        if name in saved:
            continue
        page_path = page_paths.get(item.get("page"))
        if not page_path or not os.path.exists(page_path):
            continue
        filename = "%s-%d.png" % (series.slug(name), item.get("page", 0))
        if not crop_from_page(page_path, item["box"],
                              os.path.join(folder, filename)):
            continue
        source = "%s, page %d" % (book.title or "this book",
                                  item.get("page", 0))
        series.add_picture(record, name, filename,
                           item.get("description", ""), source)
        diagnostics.write("bank", "picture saved", character=name,
                          page=item.get("page", 0),
                          box=",".join(str(int(v)) for v in item["box"]),
                          described=bool(item.get("description")))
        saved.append(name)
    return saved
