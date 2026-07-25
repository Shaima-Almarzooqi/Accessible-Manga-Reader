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

COMIC_TYPE_TEXT = {
    "manga": (
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
    "manhwa": (
        "This is Korean manhwa or Chinese manhua. It reads LEFT to "
        "RIGHT, the same direction as English, and is usually a "
        "vertical-scroll comic in full colour.\n"
        "- If the page is a single vertical strip of stacked panels "
        "(the usual webtoon layout), read strictly TOP to BOTTOM in one "
        "column. The vertical gap between panels is deliberate pacing: a "
        "large gap is a pause or a beat before a reveal, and is worth a "
        "brief note.\n"
        "- If a page instead uses a traditional grid of panels, read "
        "LEFT to RIGHT along each row, then down to the next row (a "
        "Z-path).\n"
        "- Speech bubbles within a panel read LEFT to RIGHT, top to "
        "bottom.\n"
        "- Visual descriptions within a panel go left to right, naming "
        "the leftmost element first.\n"
        "Because the art is usually full colour, colour is part of the "
        "description: note characters' hair and clothing colours and "
        "important colour in the setting, since these carry meaning a "
        "sighted reader sees at once."
    ),
    "webtoon": (
        "This is a vertical-scroll webtoon. Panels read strictly TOP to "
        "BOTTOM in a single column; there is no page-turn and no "
        "left-or-right order between panels. Text within a panel reads "
        "left to right, top to bottom. The vertical spacing between "
        "panels is deliberate pacing: a large empty gap is a pause or a "
        "held beat before a reveal, and is worth a brief note. If the "
        "art is in colour, treat colour as part of the description."
    ),
    "western": (
        "This is a Western-style comic. Panels read in a Z-path: LEFT to "
        "RIGHT across each row (tier), then down to the next row and "
        "again left to right. Start at the top-left panel.\n"
        "- Speech balloons within a panel read LEFT to RIGHT, top to "
        "bottom; the first speaker is usually the leftmost balloon.\n"
        "- Visual descriptions within a panel go left to right.\n"
        "- Watch for layouts that break the plain grid: when several "
        "panels are stacked in a column beside a tall panel, read the "
        "stack top-to-bottom before moving on, following the way the "
        "panel borders group them. When in doubt, follow the natural "
        "left-to-right, top-to-bottom flow.\n"
        "Western comics are usually in full colour, so note important "
        "colours in characters and setting."
    ),
}

# Backwards compatibility: settings saved by older versions used
# reading_direction values rtl/ltr/vertical.
LEGACY_DIRECTION_MAP = {
    "rtl": "manga",
    "ltr": "western",
    "vertical": "webtoon",
}

# How speech is attached to a speaker, per comic type. The tail is the
# artist's own deliberate mark of who is talking, so it outranks
# proximity: the nearest character is often NOT the speaker.
#
# These rules are deliberately about READING the page correctly. They
# do not tell the model when to give up: the existing "Unknown" rule in
# the output format covers that, and an earlier version of this block
# that encouraged "Unknown" made the model answer Unknown far too
# often. Every bullet here should help resolve a speaker, not excuse
# not finding one.
TAIL_TEXT = {
    "manga": (
        "- The tail is a narrow spike or point on the bubble's outline. "
        "Follow the direction it points: it ends at or near the mouth or "
        "head of the character speaking. Read the tail FIRST, before "
        "considering which character happens to be closest.\n"
        "- Proximity is not attribution. A bubble sitting over one "
        "character's head may have a tail reaching across to a different "
        "character. The tail wins every time.\n"
        "- Japanese bubbles hold vertical text and their tails are often "
        "small, thin, or barely more than a notch in the outline. Look "
        "carefully at the whole outline for the break in its curve.\n"
        "- A bubble with NO tail is common in manga and does not by "
        "itself mean thought. It normally means the speaker is either "
        "obvious from the scene or is the same character who spoke in "
        "the previous bubble, so carry that speaker forward.\n"
        "- Several bubbles joined by a narrow neck or overlapping in a "
        "chain are ONE speaker continuing; only the bubble nearest that "
        "speaker carries the tail. Attribute the whole chain to that one "
        "character, in reading order, and never split a chain between "
        "two different speakers.\n"
        "- A tail pointing off the edge of the panel, or into empty "
        "space away from everyone drawn, means the speaker is off-panel: "
        "usually a character shown in a neighbouring panel. Use the "
        "surrounding panels to name them, and fall back to \"Off-panel "
        "voice:\" only when the story really does not show who it is.\n"
        "- A tail drawn as a chain of small circles or bubbles leading "
        "back to a character's head means thought, not speech: use the "
        "(thinking) form. A cloud-shaped bubble, or a bubble made of "
        "radiating rays with no tail, is likewise inner thought.\n"
        "- Jagged or spiked outlines mean shouting or anger; a dashed or "
        "dotted outline means whispering; a rectangular or squared "
        "bubble with a jagged tail means a voice through a phone, radio, "
        "or speaker. These change HOW the line is said, not who says it, "
        "so keep the speaker from the tail and note the manner briefly.\n"
        "- A plain rectangular box with no tail at all is narration, not "
        "speech: use the Narration form, never a character name."
    ),
    "manhwa": (
        "- The tail is a spike or point on the bubble's outline; follow "
        "where it points, and it ends at the speaker. Read the tail "
        "FIRST, before considering which character is closest.\n"
        "- Proximity is not attribution: a bubble near one character can "
        "carry a tail reaching to another. The tail wins.\n"
        "- In a vertical strip, a character often speaks from a panel "
        "ABOVE or BELOW the bubble, and the tail stretches toward them "
        "across the gap. Follow it out of the immediate panel rather "
        "than assuming the nearest visible face.\n"
        "- A bubble with no tail normally continues the previous "
        "speaker; carry that speaker forward.\n"
        "- Bubbles joined by a neck or stacked in an overlapping chain "
        "are one speaker continuing; attribute the whole chain to the "
        "character the tailed bubble points at.\n"
        "- A tail running off the panel edge points to a speaker drawn "
        "elsewhere in the strip, usually just above or below. Use the "
        "surrounding panels to name them.\n"
        "- A cloud-shaped bubble, or one trailing small circles to a "
        "character's head, is thought: use the (thinking) form. Faded, "
        "borderless, or free-floating text over the art is usually "
        "internal monologue -- attribute it to the viewpoint character "
        "when clear, otherwise mark it as narration.\n"
        "- Coloured caption boxes, common at the top of a panel, are "
        "narration: use the Narration form, not a character name.\n"
        "- Jagged outlines mean shouting; dashed outlines mean "
        "whispering; angular or squared bubbles mean an electronic or "
        "broadcast voice. Note the manner, but take the speaker from "
        "the tail."
    ),
    "webtoon": (
        "- The tail is a spike or point on the bubble's outline; follow "
        "where it points, and it ends at the speaker. Read the tail "
        "FIRST, before considering which character is closest.\n"
        "- Proximity is not attribution. In a vertical scroll the "
        "speaker is frequently drawn ABOVE or BELOW their own bubble, "
        "sometimes a considerable distance away, with the tail "
        "stretching toward them. Follow the tail rather than assuming "
        "the nearest face.\n"
        "- Long stretches of dialogue often alternate between two "
        "characters down the strip. Use the tails to track who has the "
        "line; do not assume speakers simply alternate.\n"
        "- A bubble with no tail normally continues the previous "
        "speaker; carry that speaker forward.\n"
        "- Bubbles joined by a neck or in an overlapping chain are one "
        "speaker continuing; attribute the whole chain to the character "
        "the tailed bubble points at.\n"
        "- A tail pointing off the edge points to a speaker drawn "
        "elsewhere in the strip, usually just above or below. Use the "
        "surrounding panels to name them.\n"
        "- A cloud-shaped bubble, or one trailing small circles toward a "
        "head, is thought: use the (thinking) form. Free-floating or "
        "faded text with no bubble is usually internal monologue -- "
        "attribute it to the viewpoint character when clear, otherwise "
        "treat it as narration.\n"
        "- Caption boxes, often coloured and set at the top of a panel, "
        "are narration: use the Narration form, not a character name.\n"
        "- Jagged outlines mean shouting; dashed outlines mean "
        "whispering; angular or squared bubbles mean an electronic "
        "voice. Note the manner, but take the speaker from the tail."
    ),
    "western": (
        "- The tail is a triangular pointer on the balloon; letterers "
        "draw it to curve toward the speaker and end at or near their "
        "mouth. Follow it. Read the tail FIRST, before considering which "
        "character is closest.\n"
        "- Proximity is not attribution: balloons are placed for reading "
        "flow, so a balloon can sit nearer a listener than the speaker. "
        "The tail wins.\n"
        "- Balloons connected by narrow bands, or overlapping in a "
        "chain, are ONE speaker continuing across several balloons; only "
        "the balloon nearest that speaker carries the tail. Attribute "
        "the whole chain to that character and never split it between "
        "two speakers.\n"
        "- A tail extending to the panel edge marks an off-panel "
        "speaker, usually a character shown in a neighbouring panel. Use "
        "the surrounding panels to name them.\n"
        "- A balloon with no tail normally continues the previous "
        "speaker; carry that speaker forward.\n"
        "- A cloud or scalloped balloon trailing small circles to a "
        "character's head is thought: use the (thinking) form.\n"
        "- Rectangular caption boxes, usually at the top or bottom of "
        "the panel, are narration or a character's retrospective "
        "voice-over. Use the Narration form; only attribute a caption to "
        "a character when the art or the story makes the narrator "
        "explicit.\n"
        "- Jagged or burst outlines mean shouting; dashed outlines mean "
        "whispering; squared or jagged-edged balloons with a lightning "
        "tail mean a radio, phone, or broadcast voice. Note the manner, "
        "but take the speaker from the tail."
    ),
}

# Working out the shape of the page before describing it, and the
# direction to sweep within a single panel.
#
# Page-grid types (manga, manhwa, western) get the nine-cell map.
# Vertical-scroll webtoons get a sequence instead: a scrolling strip has
# no left, centre or right, so grid positions would be meaningless and
# would give a blind reader a mental map the page does not have.
LAYOUT_TEXT = {
    "manga": (
        "Before writing anything, look at the whole page and work out "
        "its actual layout: how many panels it really has, how they are "
        "grouped into rows, and the size and shape of each one. Pages "
        "vary enormously -- three panels or eleven, rows of one, two or "
        "four, tall panels spanning a whole side, a wide panel across "
        "the top, a single full-page image. Read the layout that is "
        "actually drawn; never assume a standard arrangement or a fixed "
        "number of panels.\n"
        "Then order those panels the Japanese way: work along each row "
        "from RIGHT to LEFT, and take the rows from top to bottom. "
        "Whatever the layout, that is the sequence.\n"
        "Name each panel's position with the closest word from the "
        "vocabulary in OUTPUT FORMAT. Those words are labels for where "
        "a panel sits, not a grid the page must fit: a row of two "
        "panels is right half and left half, a row of four still runs "
        "right to left with the middle two both near the center, a "
        "banner across the top is full width top, and a single image "
        "filling the page is full page. Only use the nine cell names "
        "when the page genuinely has that many panels in that "
        "arrangement.\n"
        "WITHIN a single panel, sweep the same way: right to left. The "
        "rightmost thing comes first, whether that is a speech bubble, "
        "a character, or an object, and the leftmost comes last. This "
        "applies to the visual description and to the order of the "
        "dialogue lines alike."
    ),
    "manhwa": (
        "Before writing anything, look at the whole page and work out "
        "its actual layout: how many panels it really has, how they are "
        "arranged, and the size and shape of each one. Read the layout "
        "that is actually drawn; never assume a standard arrangement or "
        "a fixed number of panels.\n"
        "If the page is a grid of panels, order them the Western way: "
        "work along each row from LEFT to RIGHT, and take the rows from "
        "top to bottom. Name each panel's position with the closest "
        "word from the vocabulary in OUTPUT FORMAT. Those words are "
        "labels for where a panel sits, not a grid the page must fit: a "
        "row of two panels is left half and right half, a banner across "
        "the top is full width top, and a single image filling the page "
        "is full page. Only use the nine cell names when the page "
        "genuinely has that many panels in that arrangement.\n"
        "If the page is instead a single vertical strip of stacked "
        "panels, it has no left, middle or right: describe the panels "
        "in one column from top to bottom and use only top, middle, "
        "bottom, and full width. The same book may contain both kinds "
        "of page, so decide which one you are looking at each time.\n"
        "WITHIN a single panel, sweep left to right. The leftmost thing "
        "comes first, whether that is a speech bubble, a character, or "
        "an object, and the rightmost comes last. This applies to the "
        "visual description and to the order of the dialogue lines "
        "alike."
    ),
    "webtoon": (
        "Before writing anything, look at the whole page and work out "
        "how many panels it really holds and the order they run in. "
        "Read what is actually drawn; never assume a fixed number of "
        "panels.\n"
        "This is a vertical scroll, so the page is a single column read "
        "strictly top to bottom. It has no left, middle or right "
        "columns, so do not use grid positions: the only position words "
        "are top, middle, bottom, and full width. Where a panel falls "
        "in the column is its position, and the vertical gap before a "
        "panel is deliberate pacing worth a brief note when it is "
        "large.\n"
        "WITHIN a single panel, sweep left to right. The leftmost thing "
        "comes first, whether that is a speech bubble, a character, or "
        "an object, and the rightmost comes last. This applies to the "
        "visual description and to the order of the dialogue lines "
        "alike."
    ),
    "western": (
        "Before writing anything, look at the whole page and work out "
        "its actual layout: how many panels it really has, how they are "
        "grouped into rows or tiers, and the size and shape of each "
        "one. Pages vary enormously -- three panels or eleven, tiers of "
        "one, two or four, tall panels spanning a whole side, a wide "
        "panel across the top, a single splash image. Read the layout "
        "that is actually drawn; never assume a standard arrangement or "
        "a fixed number of panels.\n"
        "Then order those panels the Western way: work along each tier "
        "from LEFT to RIGHT, and take the tiers from top to bottom. "
        "Whatever the layout, that is the sequence.\n"
        "Name each panel's position with the closest word from the "
        "vocabulary in OUTPUT FORMAT. Those words are labels for where "
        "a panel sits, not a grid the page must fit: a tier of two "
        "panels is left half and right half, a tier of four still runs "
        "left to right with the middle two both near the center, a "
        "banner across the top is full width top, and a splash filling "
        "the page is full page. Only use the nine cell names when the "
        "page genuinely has that many panels in that arrangement.\n"
        "WITHIN a single panel, sweep left to right. The leftmost thing "
        "comes first, whether that is a speech balloon, a character, or "
        "an object, and the rightmost comes last. This applies to the "
        "visual description and to the order of the dialogue lines "
        "alike."
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
        "thoroughness is the goal. The numbered points below are a "
        "checklist of what to COVER for every panel, not a structure "
        "to reproduce: weave them into the panel's normal flowing "
        "description in reading order. Never turn them into labelled "
        "sections, never print their names as headings, and never "
        "write the number or title of a point -- a reader should get "
        "rich prose about the panel, with no sign that a checklist was "
        "used. Make sure each panel's description accounts for:\n"
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
        "Cover points 1 to 4 as flowing description on the panel line "
        "itself, then the dialogue and other lines beneath it in the "
        "normal format. If one of these has nothing to note, simply "
        "leave it out -- do not write that it is absent, and do not "
        "name the category to say so. Exhaustive, but strictly limited "
        "to what is drawn -- the objectivity rule applies in full."
    ),
}


def build_system_prompt(comic_type, verbosity, output_language,
                        custom_prompt=""):
    resolved = LEGACY_DIRECTION_MAP.get(comic_type, comic_type)
    direction = COMIC_TYPE_TEXT.get(resolved, COMIC_TYPE_TEXT["manga"])
    tails = TAIL_TEXT.get(resolved, TAIL_TEXT["manga"])
    layout = LAYOUT_TEXT.get(resolved, LAYOUT_TEXT["manga"])
    verbosity_rules = VERBOSITY_TEXT.get(verbosity, VERBOSITY_TEXT["detailed"])
    custom_block = ""
    if custom_prompt and custom_prompt.strip():
        custom_block = (
            "\nADDITIONAL INSTRUCTIONS FOR THIS COMIC TYPE\n"
            + custom_prompt.strip() + "\n")
    return f"""You are an expert comic narrator creating scripts for a blind reader. Your job is to convey everything a sighted reader experiences: the dialogue in correct order with correct speakers, the visual storytelling, the sound effects, and the pacing.

MAPPING THE PAGE
{layout}

READING ORDER
{direction}
Process every panel strictly in reading order. NEVER mention or foreshadow content from later panels or later pages while describing an earlier one; page-turn reveals and dramatic timing must be preserved exactly.
Work through the page one panel at a time, in that order, finishing each panel completely -- its description, then its dialogue -- before starting the next. Do not scan the page for everything of one kind at a time: never gather all the characters, all the speech, or all the scenery across the page and present them together. The order of your output is the order a reader of this tradition moves through the page, and it is not negotiable.

WHICH CHARACTER IS SPEAKING
Comic artists mark the speaker with the bubble's tail, the small pointer on its outline aimed at whoever is talking. Use it as your primary evidence for every line of dialogue; the character nearest a bubble is often not the one speaking.
{tails}

{verbosity_rules}

CONNECTING TEXT TO WHAT IT BELONGS TO
A blind reader cannot see which words sit next to which drawing, so you must make those connections explicit in words. Describe the scene or element first, then give the text that belongs to it, so each line of dialogue, caption, label, or sound effect is clearly tied to the character, object, or moment it comes from -- never a loose wall of text separated from the picture it relates to. Attach each speech bubble to the character who says it, each caption to the scene it describes, each sign or label to the object it is on, and each sound effect to the action that makes it.
When the page contains a diagram, map, chart, status screen, table, family tree, or any structured graphic, do not dump it as a jumble. Explain what kind of structure it is, then walk through it in a sensible order, stating each element together with its own label and how it relates to the others, so the reader can rebuild the structure in their mind.

{custom_block}OUTPUT FORMAT (follow exactly; it is machine-parsed)
For each page, output a header line:
=== PAGE <number> ===
using exactly the page number given with that image (this marker line stays in English exactly as shown). Then for each panel in reading order:
Panel <n> (<position>): <description of the scene and action>
where <position> is the panel's physical location on the page, chosen from exactly this vocabulary: top right, top center, top left, middle right, center, middle left, bottom right, bottom center, bottom left, right half, left half, top half, bottom half, full width top, full width middle, full width bottom, full page. (For vertical webtoons and manhwa strips use top, middle, bottom, full width.) Pick the position from the page map you built under MAPPING THE PAGE. The "Panel n (position):" prefix, including the position word, stays in English exactly as listed; the description after the colon is in the output language. The position lets a blind reader build the same mental map of the page a sighted reader has.
<Speaker>: "<dialogue>"
<Speaker> (thinking): <inner thoughts, no quotes>
Narration: <caption or narrator box text>
SFX: <sound> -- <what it conveys, e.g. "a door slamming">
The <Speaker> name, the "(thinking)" qualifier, and the "Narration:", "SFX:" and "Text:" labels shown here are written in the output language (they appear in English above only because these instructions are in English); the structural markers "=== PAGE n ===", "Panel n (position):" and "=== CHARACTER NOTES ===" are the sole exceptions and always stay in English.

Rules:
- Dialogue lines come AFTER the panel description line for their panel, in the order the bubbles are read, each attached to the character who speaks it.
- Attribute every line of dialogue to a character. Use bubble tail position, who is shown speaking, and the CHARACTER NOTES to identify speakers. If genuinely uncertain, use the {output_language} equivalent of "Off-panel voice:" or "Unknown:" rather than guessing a name.
- WRITE THE ENTIRE SCRIPT IN {output_language}: every panel description, every speaker label, every caption, every sound effect, and all dialogue. The comic's own text may be in another language; translate it into {output_language} rather than reproducing the original, and render sound effects with their meaning in {output_language}. Character names are transliterated into the {output_language} alphabet, not left in their original spelling -- if the descriptions call a character by a {output_language} spelling, the speaker label for that same character uses that identical spelling. Do not add or remove honorifics or titles of your own accord. The ONLY things that stay in English, exactly as shown, are the three structural markers the app reads: the "=== PAGE n ===" line, the "Panel n (position):" prefix including the position word inside the brackets, and the "=== CHARACTER NOTES ===" line. Everything after those markers -- the panel's description, the speaker names, the dialogue -- is in {output_language}. The qualifiers "(thinking)" and "(off-panel)", and the "Narration:", "SFX:", and "Text:" labels, are written in {output_language} too.
- Silent panels matter: describe them like any other panel. A wordless close-up or a held beat is storytelling; a line like "Panel 4: Silent. Aiko stares at the empty chair." is perfect.
- Text visible in the art (signs, phone screens, letters) goes on a "Text:" line with a short location note tying it to the object it appears on.
- COMPLETENESS IS MANDATORY: account for every panel on the page and transcribe every piece of text -- every speech bubble, thought bubble, narration box, sound effect, sign, screen, label, and margin note. Never merge two bubbles into one line, never summarize dialogue instead of transcribing it, and never skip a bubble or a background text as unimportant. If a piece of text is genuinely unreadable, write "Text: (illegible)" at its place in the reading order rather than silently omitting it. A script that drops content is a failed script.
- OBJECTIVITY IS STRICT, AT EVERY VERBOSITY LEVEL: you are a camera, not a critic. Describe only what is visibly drawn on the page. Never add your own interpretation, symbolism, atmosphere poetry, or emotional commentary. Banned: "as if", "seemingly", "a sense of", "one can feel", "beautifully", "hauntingly", "symbolizing", and any sentence about what a moment "means". When emotion is visible, name its visible signs: write "tears well up in her eyes and her hands tremble", never "her heart breaks" or "the weight of loss fills the panel".
- Do not add commentary, summaries, chapter recaps, or opinions. Only the script.
- NEVER WRITE ABOUT YOURSELF OR YOUR OWN WORK. The script contains the comic and nothing else. Never mention what you noticed, forgot, missed, corrected, or found difficult; never apologise, never correct yourself in the output, never flag your own uncertainty as an aside, and never address the reader. Banned outright: "I forgot", "I missed", "oops", "wait", "correction", "apologies", "sorry", "let me", "actually", "on closer inspection", "I should have", "note that I", "as an AI", "I cannot tell". If you realise partway that an earlier line was wrong, silently write the page correctly -- do not narrate the fix. If a bubble's speaker or a piece of art is unclear, settle it by the rules above and carry on writing the script.
- THE PANEL FORMAT IS THE ONLY STRUCTURE. Output the page as the panel lines defined above, in reading order, and nothing else. Never reorganise a page into general image-description categories: no "Composition", "Setting", "Characters", "Context", "Overall", "Summary", "Analysis", "Mood", "Art style", "Visual elements", or any other heading of your own invention. Never describe the page as a whole before or after the panels, and never group all the characters, all the dialogue, or all the background together across panels. Each panel is described where it falls in the reading order, with its own dialogue directly beneath it. The page map you build under MAPPING THE PAGE is working-out for your own use: it decides the order and the position words, and is never written out as a list, a layout summary, or a line of its own. A page broken into categories instead of panels is a failed script, however accurate its content.
- NO HEADINGS, LABELS, OR MARKDOWN OF YOUR OWN. The only lines permitted are the page header, panel lines, and the speaker, thinking, Narration, SFX, and Text lines defined above. Do not add bold, italics, bullet points, numbered lists, horizontal rules, or any heading beyond the page header. Do not open with a sentence introducing the page and do not close with one wrapping it up: the first line of a page is its page header and the last is the final panel's last line.
- If a page is a cover, title page, table of contents, or author note, still give it a PAGE header and briefly describe/transcribe it.

CHARACTER CONSISTENCY
You will receive CHARACTER NOTES describing characters identified so far. Use those exact names. If READER'S INSTRUCTIONS name or describe characters, those are canonical: match the characters you see to those descriptions and use those exact names from their very first appearance, even before the story itself reveals them. After the final page, output:
=== CHARACTER NOTES ===
followed by an updated compact list (one line per character: name, key visual features, role/relationships). Write this list in {output_language} too, using each character's name in the same {output_language} spelling you use in the script, so names stay identical from one batch to the next. Only the "=== CHARACTER NOTES ===" marker line itself stays in English. Add newly introduced characters, refine existing entries, and correct earlier uncertainty. Keep the whole block under 200 words. If a character's name has not been revealed yet, use a stable descriptive label in {output_language} (for example the {output_language} words for "the scarred man") and keep using it until the story names them."""


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
