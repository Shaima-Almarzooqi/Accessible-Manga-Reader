"""Prompt construction and response parsing.

The model receives a batch of page images and returns one script per page
in a strict, machine-parseable plain-text format, followed by an updated
CHARACTER NOTES block that is carried into the next batch so names stay
consistent across the whole book.

Output format the model is instructed to produce:

    === PAGE 12 ===
    Panel 1 (top right): Two students stand at the school gate under falling cherry blossoms.
    Aiko: "You're late again!"
    Kenta (thinking): She waited for me...
    SFX: zaaa -- wind rushing through the trees
    Panel 2 (top left): Close-up of Kenta's embarrassed smile.
    Kenta: "Sorry. Won't happen again."

    === PAGE 13 ===
    ...

    === CHARACTER NOTES ===
    Aiko: short dark hair, school uniform, class representative. ...
"""

import re

PAGE_HEADER_RE = re.compile(r"^===\s*PAGE\s+(\d+)\s*===\s*$", re.MULTILINE)
NOTES_HEADER_RE = re.compile(r"^===\s*CHARACTER NOTES\s*===\s*$", re.MULTILINE)

READING_DIRECTION_TEXT = {
    "rtl": (
        "This is Japanese manga. The RIGHT-TO-LEFT rule is absolute and "
        "applies at EVERY level of the page, without exception:\n"
        "- Panels on the page: rightmost first, top to bottom.\n"
        "- Speech bubbles WITHIN a single panel: rightmost bubble first, "
        "top to bottom.\n"
        "- Vertical Japanese text columns within one bubble: rightmost "
        "column first.\n"
        "- Visual descriptions within a single panel: describe what a "
        "Japanese reader's eye meets first (the right side) before the "
        "left side.\n"
        "- Two-page spreads: from the rightmost panel of the right page "
        "across to the leftmost panel of the left page.\n"
        "Before writing anything, silently map the page's panel grid: "
        "identify the rows from top to bottom, and within each row list "
        "the panels from RIGHT to LEFT. Only then write, following that "
        "map exactly.\n"
        "Worked example: a page has five panels, three across the top "
        "row and two across the bottom row. The one and only correct "
        "order is: 1) top right, 2) top center, 3) top left, then drop "
        "to the next row and RETURN TO ITS RIGHT EDGE: 4) bottom right, "
        "5) bottom left. The eye returns to the right edge at the start "
        "of every new row. The same logic applies to any layout: finish "
        "a row right-to-left, then start the next row at its rightmost "
        "panel. Never zigzag, and never reorder anything into "
        "left-to-right out of habit. Before writing each panel, "
        "double-check that every bubble and caption is listed in "
        "right-to-left, top-to-bottom order."
    ),
    "ltr": (
        "This is a Western-style comic. Panels read LEFT to RIGHT, TOP to "
        "BOTTOM, and speech bubbles within a panel follow the same order."
    ),
    "vertical": (
        "This is a vertical-scroll webtoon. Panels read strictly TOP to "
        "BOTTOM in a single column."
    ),
}

VERBOSITY_TEXT = {
    "concise": (
        "Verbosity: CONCISE. Describe each panel in ONE short sentence "
        "focused on action and who is present. Keep the pace fast; manga "
        "is a quick-reading medium. Skip minor background detail."
    ),
    "detailed": (
        "Verbosity: DETAILED. Describe each panel in two to three full "
        "sentences covering the action, each visible character's facial "
        "expression and body language, and the setting. Give full-page "
        "or splash panels extra attention, since they mark dramatic "
        "moments. Do not compress to a single line; two sentences is "
        "the minimum for any panel with characters in it."
    ),
    "extensive": (
        "Verbosity: EXTENSIVE. Give the fullest description of what is "
        "physically present on the page; length is unlimited and "
        "thoroughness is the goal. For EVERY panel, systematically "
        "cover, in this order:\n"
        "1. Shot and composition: the framing (extreme close-up, "
        "close-up, medium shot, wide establishing shot, bird's-eye, "
        "low angle), what dominates the panel, and what sits in the "
        "foreground versus the background.\n"
        "2. Every visible character, one by one: their position in the "
        "panel and relative to the others; facial expression in "
        "concrete physical terms (eyes, eyebrows, mouth, sweat drops, "
        "blush marks, tears, gritted teeth); gaze direction; posture "
        "and gestures, including what their hands are doing; clothing "
        "and accessories in detail, noting changes from earlier "
        "panels; and any visible state such as injuries, bandages, "
        "dirt, or fatigue lines.\n"
        "3. Background and setting: the location; every notable "
        "object; signage, posters, screens, or labels (transcribe "
        "their text); weather; time-of-day cues; and any bystanders "
        "or crowds.\n"
        "4. Art techniques as drawn: speed lines, impact flashes, "
        "focus lines, screentone shading, abstract or emotional "
        "backgrounds behind a character, motion blur, and unusual "
        "panel borders (for example jagged or borderless panels).\n"
        "5. Then the dialogue, thoughts, narration, SFX, and text "
        "lines as usual.\n"
        "Never skip a category because it seems minor; if a category "
        "has nothing notable, say so in a few words (for example "
        "'plain white background'). Exhaustive, but strictly limited "
        "to what is drawn -- the objectivity rule applies in full."
    ),
}


def build_system_prompt(reading_direction, verbosity, output_language):
    direction = READING_DIRECTION_TEXT.get(
        reading_direction, READING_DIRECTION_TEXT["rtl"])
    verbosity_rules = VERBOSITY_TEXT.get(verbosity, VERBOSITY_TEXT["detailed"])
    return f"""You are an expert manga narrator creating scripts for a blind reader. Your job is to convey everything a sighted reader experiences: the dialogue in correct order with correct speakers, the visual storytelling, the sound effects, and the pacing.

READING ORDER
{direction}
Process every panel strictly in reading order. NEVER mention or foreshadow content from later panels or later pages while describing an earlier one; page-turn reveals and dramatic timing must be preserved exactly.

{verbosity_rules}

OUTPUT FORMAT (follow exactly; it is machine-parsed)
For each page, output a header line:
=== PAGE <number> ===
using exactly the page number given with that image. Then for each panel in reading order:
Panel <n> (<position>): <description of the scene and action>
where <position> is the panel's physical location on the page, chosen from exactly this vocabulary: top right, top center, top left, middle right, center, middle left, bottom right, bottom center, bottom left, right half, left half, top half, bottom half, full width top, full width middle, full width bottom, full page. (For vertical webtoons use top, middle, bottom, full width.) The position lets a blind reader build the same mental map of the page a sighted reader has.
<Speaker>: "<dialogue>"
<Speaker> (thinking): <inner thoughts, no quotes>
Narration: <caption or narrator box text>
SFX: <romanized sound> -- <what it conveys, e.g. "a door slamming">

Rules:
- Dialogue lines come AFTER the panel description line for their panel, in the order the bubbles are read.
- Attribute every line of dialogue to a character. Use bubble tail position, who is shown speaking, and the CHARACTER NOTES to identify speakers. If genuinely uncertain, use "Off-panel voice:" or "Unknown:" rather than guessing a name.
- Translate all text into {output_language}. Keep Japanese honorifics (-san, -kun, -chan, -sensei) and render sound effects as romanized Japanese plus their meaning.
- Silent panels matter: describe them like any other panel. A wordless close-up or a held beat is storytelling; a line like "Panel 4: Silent. Aiko stares at the empty chair." is perfect.
- Text visible in the art (signs, phone screens, letters) goes on a "Text:" line with a short location note.
- COMPLETENESS IS MANDATORY: account for every panel on the page and transcribe every piece of text -- every speech bubble, thought bubble, narration box, sound effect, sign, screen, label, and margin note. Never merge two bubbles into one line, never summarize dialogue instead of transcribing it, and never skip a bubble or a background text as unimportant. If a piece of text is genuinely unreadable, write "Text: (illegible)" at its place in the reading order rather than silently omitting it. A script that drops content is a failed script.
- OBJECTIVITY IS STRICT, AT EVERY VERBOSITY LEVEL: you are a camera, not a critic. Describe only what is visibly drawn on the page. Never add your own interpretation, symbolism, atmosphere poetry, or emotional commentary. Banned: "as if", "seemingly", "a sense of", "one can feel", "beautifully", "hauntingly", "symbolizing", and any sentence about what a moment "means". When emotion is visible, name its visible signs: write "tears well up in her eyes and her hands tremble", never "her heart breaks" or "the weight of loss fills the panel".
- Do not add commentary, summaries, chapter recaps, or opinions. Only the script.
- If a page is a cover, title page, table of contents, or author note, still give it a PAGE header and briefly describe/transcribe it.

CHARACTER CONSISTENCY
You will receive CHARACTER NOTES describing characters identified so far. Use those exact names. If READER'S INSTRUCTIONS name or describe characters, those are canonical: match the characters you see to those descriptions and use those exact names from their very first appearance, even before the story itself reveals them. After the final page, output:
=== CHARACTER NOTES ===
followed by an updated compact list (one line per character: name, key visual features, role/relationships). Add newly introduced characters, refine existing entries, and correct earlier uncertainty. Keep the whole block under 200 words. If a character's name has not been revealed yet, use a stable descriptive label like "Scarred man" and keep using it until the story names them."""


def build_user_text(page_numbers, character_notes, book_title="",
                    user_instructions=""):
    """The text portion of the user message accompanying the page images."""
    pages_list = ", ".join(str(n) for n in page_numbers)
    parts = []
    if book_title:
        parts.append(f"Book: {book_title}")
    if user_instructions.strip():
        parts.append(
            "READER'S INSTRUCTIONS for this book (follow them; they "
            "override your own guesses, especially for character names "
            "and identification):\n" + user_instructions.strip())
    parts.append(
        f"You are given {len(page_numbers)} page image(s), in order: "
        f"pages {pages_list}. Label your output with exactly these page numbers.")
    if character_notes.strip():
        parts.append("CHARACTER NOTES so far:\n" + character_notes.strip())
    else:
        parts.append(
            "CHARACTER NOTES so far: (none yet -- this is the start of the "
            "book; introduce characters as they appear)")
    parts.append("Produce the script now.")
    return "\n\n".join(parts)


def parse_response(text):
    """Parse a model response into (scripts, character_notes).

    scripts is a dict mapping page number (int) to that page's script text
    (without the header line). character_notes is the updated notes block,
    or "" if the model omitted it.

    Raises ValueError if no page headers are found at all, so the caller
    can retry the batch.
    """
    notes = ""
    notes_match = NOTES_HEADER_RE.search(text)
    body = text
    if notes_match:
        notes = text[notes_match.end():].strip()
        body = text[:notes_match.start()]

    matches = list(PAGE_HEADER_RE.finditer(body))
    if not matches:
        raise ValueError("Model response contained no page headers")

    scripts = {}
    for i, match in enumerate(matches):
        page_number = int(match.group(1))
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        scripts[page_number] = body[start:end].strip()
    return scripts, notes


PANEL_MARKER_RE = re.compile(
    r"^Panel\s+\d+\s*(?:\([^)\n]*\))?\s*:", re.MULTILINE)

PANEL_POSITION_RE = re.compile(r"^Panel\s+\d+\s*\(([^)\n]+)\)\s*:")


def panel_position(panel_unit):
    """Extract the position label ('top right', ...) from a panel unit's
    first line, or "" for scripts produced before positions existed."""
    for line in panel_unit.splitlines():
        line = line.strip()
        if not line:
            continue
        match = PANEL_POSITION_RE.match(line)
        return match.group(1).strip() if match else ""
    return ""


def split_panels(script):
    """Split one page's script into per-panel units for the reader's
    panel-by-panel display mode.

    Each unit starts at a "Panel N:" line and includes everything
    (dialogue, SFX, narration) up to the next panel marker. Any preamble
    before the first marker (rare: covers, author notes) is attached to
    the first unit; a script with no panel markers at all becomes a
    single unit.
    """
    script = script.strip()
    if not script:
        return []
    matches = list(PANEL_MARKER_RE.finditer(script))
    if not matches:
        return [script]
    units = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(script)
        units.append(script[match.start():end].strip())
    preamble = script[:matches[0].start()].strip()
    if preamble:
        units[0] = preamble + "\n" + units[0]
    return units


PANEL_LABEL_STRIP_RE = re.compile(
    r"^Panel\s+\d+(?:\s*\([^)\n]*\))?\s*:\s*", re.MULTILINE)


def strip_panel_labels(text):
    """Remove "Panel N (position):" prefixes for continuous narrative
    reading. The description that follows each prefix is kept, so the
    story flows without the structural markers. Page markers and all
    dialogue are untouched.
    """
    return PANEL_LABEL_STRIP_RE.sub("", text)
