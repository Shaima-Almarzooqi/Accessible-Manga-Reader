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


def build_ask_system_prompt(settings):
    comic_type = settings.get("comic_type", "manga")
    resolved = prompts.LEGACY_DIRECTION_MAP.get(comic_type, comic_type)
    direction = prompts.COMIC_TYPE_TEXT.get(
        resolved, prompts.COMIC_TYPE_TEXT["manga"])
    language = settings.get("output_language", "English")
    return (
        "You are answering a blind reader's question about specific comic "
        "pages, which are attached as images. Ground every statement "
        "strictly in what is visibly drawn on these pages; if the pages "
        "do not show the answer, say so plainly rather than guessing. "
        "Describe visual details in concrete terms a blind reader can "
        "use, and tie each detail to where it appears (which page, which "
        "panel, which character or object). Do not add interpretation or "
        "commentary beyond what is asked. Answer in %s.\n\n"
        "For reference, the pages follow these reading conventions:\n%s"
        % (language, direction))


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
    client = api_client.create_client(settings)
    system_prompt = build_ask_system_prompt(settings)
    content = build_ask_content(book, page_numbers, question, history)
    return client.request_scripts(system_prompt, content,
                                  cancel_check=cancel_check).strip()
