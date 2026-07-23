"""Answering a reader's question about specific pages.

The question is answered from the raw page images (not the generated
script), so the AI can look again at anything the script left unclear.
The script for those pages and the book's character notes are supplied
as context so names and prior events resolve correctly.
"""

from . import api_client, prompts

# At most this many pages can be attached to one question: every page is
# an image, and an unbounded range would exhaust tokens and quota.
MAX_ASK_PAGES = 10

ASK_MAX_ATTEMPTS = 2
ASK_INITIAL_BACKOFF = 4.0


def build_ask_system_prompt(settings):
    comic_type = settings.get("comic_type", "manga")
    resolved = prompts.LEGACY_DIRECTION_MAP.get(comic_type, comic_type)
    direction = prompts.COMIC_TYPE_TEXT.get(
        resolved, prompts.COMIC_TYPE_TEXT["manga"])
    tails = prompts.TAIL_TEXT.get(resolved, prompts.TAIL_TEXT["manga"])
    language = settings.get("output_language", "English")
    return (
        "You are answering a blind reader's question about specific comic "
        "pages, which are attached as images. Ground every statement "
        "strictly in what is visibly drawn on these pages; if the pages "
        "do not show the answer, say so plainly rather than guessing. "
        "Describe visual details in concrete terms a blind reader can "
        "use, and tie each detail to where it appears (which page, which "
        "panel, which character or object). Do not add interpretation or "
        "commentary beyond what is asked. Write your answer as clear "
        "flowing prose for a screen reader: do not use Markdown "
        "formatting symbols such as asterisks, hash signs, pipes, or "
        "horizontal rules. When walking through several panels, start "
        "each panel on its own line with a short lead-in like 'Panel 2, "
        "middle right:' in words. Answer in %s.\n\n"
        "If the question is about who says or thinks something, settle "
        "it from the bubble's tail, which is the artist's own mark of "
        "the speaker and outranks which character sits nearest the "
        "bubble. If this contradicts the existing script supplied "
        "below, trust the page images and say so.\n\n"
        "For reference, the pages follow these reading conventions:\n%s"
        "\n\nHow speech is attached to a speaker in this kind of "
        "comic:\n%s"
        % (language, direction, tails))


def build_ask_content(book, page_numbers, question, history=None):
    """Assemble the provider-neutral content for one question."""
    parts = []
    notes = (book.character_notes or "").strip()
    if notes:
        parts.append("CHARACTER NOTES (who is who):\n" + notes)
    script_bits = []
    for number in page_numbers:
        script = (book.scripts.get(number) or "").strip()
        if script:
            script_bits.append("Page %d script:\n%s" % (number, script))
    if script_bits:
        parts.append(
            "THE EXISTING SCRIPT FOR THESE PAGES (for context; the "
            "images are the authority):\n\n" + "\n\n".join(script_bits))
    for earlier_question, earlier_answer in (history or []):
        parts.append("The reader previously asked: %s\n"
                     "You answered: %s" % (earlier_question, earlier_answer))
    parts.append("THE READER'S QUESTION about the attached page%s (%s): %s"
                 % ("s" if len(page_numbers) != 1 else "",
                    ", ".join(str(n) for n in page_numbers), question))
    image_paths = [book.page_image_path(n) for n in page_numbers]
    return api_client.build_content(
        page_numbers, image_paths, "\n\n".join(parts))


def ask_question(book, settings, question, page_numbers, history=None,
                 cancel_check=None):
    """Send one question and return the answer text.

    Raises api_client.ApiError with a readable message on failure.
    """
    page_numbers = sorted(set(page_numbers))[:MAX_ASK_PAGES]
    client = api_client.set_retry_limits(
        api_client.create_client(settings),
        ASK_MAX_ATTEMPTS, ASK_INITIAL_BACKOFF)
    system_prompt = build_ask_system_prompt(settings)
    content = build_ask_content(book, page_numbers, question, history)
    return client.request_scripts(system_prompt, content,
                                  cancel_check=cancel_check).strip()


import html as _html
import re as _re


def _inline_html(text):
    """Escape, then convert the inline markdown that models emit."""
    escaped = _html.escape(text)
    escaped = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = _re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)",
                      r"<em>\1</em>", escaped)
    return escaped


def answer_to_html(text):
    """Turn an answer (plain prose, or markdown that slipped through the
    instructions) into clean HTML: headings become h4, bullets become
    lists, everything else becomes paragraphs. Never shows raw symbols.
    """
    blocks = []
    bullets = []

    def flush_bullets():
        if bullets:
            blocks.append("<ul>%s</ul>"
                          % "".join("<li>%s</li>" % b for b in bullets))
            bullets.clear()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or _re.fullmatch(r"[-_*]{3,}", line):
            flush_bullets()
            continue
        heading = _re.fullmatch(r"#{1,6}\s*(.+?)\s*#*", line)
        if heading:
            flush_bullets()
            blocks.append("<h4>%s</h4>" % _inline_html(heading.group(1)))
            continue
        bullet = _re.fullmatch(r"[*+-]\s+(.+)", line)
        if bullet:
            bullets.append(_inline_html(bullet.group(1)))
            continue
        flush_bullets()
        blocks.append("<p>%s</p>" % _inline_html(line))
    flush_bullets()
    return "\n".join(blocks)


WAITING_TEXT = "Waiting for the answer. This usually takes a few seconds."

STOPPED_TEXT = ("Stopped before the AI answered. Your question is still in "
                "the question box, so you can ask it again.")

EMPTY_TEXT = ("No questions yet. Type a question in the box above, choose "
              "which pages the AI should look at, then select Ask.")


def conversation_html(book_title, history, pending=None):
    """The whole Ask session as an HTML document: each question is a
    level-2 heading and each answer a level-3 heading, so browse mode
    jumps between them with H, 2, and 3.

    `pending` is an optional (question, status text) pair for a question
    that has been sent but not answered yet.
    """
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        "<title>%s</title>" % _html.escape("Ask - %s" % book_title),
        "<style>body{font-family:sans-serif;max-width:46em;margin:0.5em "
        "auto;padding:0 1em;line-height:1.6}h2{font-size:1.15em;"
        "margin-top:1.2em}h3{font-size:1.05em;margin:0.7em 0 0.2em}"
        "h4{font-size:1em;margin:0.8em 0 0.2em}"
        "p{margin:0.4em 0}</style></head><body>",
    ]
    exchanges = list(history)
    if pending is not None:
        exchanges.append(pending)
    if not exchanges:
        parts.append("<p>%s</p>" % _html.escape(EMPTY_TEXT))
    for index, (question, answer) in enumerate(exchanges, start=1):
        parts.append("<h2>Question %d: %s</h2>"
                     % (index, _inline_html(question)))
        parts.append("<h3>Answer</h3>")
        parts.append(answer_to_html(answer))
    parts.append("</body></html>")
    return "\n".join(parts)
