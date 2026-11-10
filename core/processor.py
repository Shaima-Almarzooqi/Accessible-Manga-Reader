"""Batch processor.

Walks a book's unprocessed pages in batches, sends each batch to the API,
parses the returned scripts, updates the running character notes, and
saves the book after every batch so nothing is ever lost.

GUI-independent: progress is reported through callbacks, and the whole
run happens on whatever thread calls process_book() (the GUI runs it on
a worker thread and marshals callbacks with wx.CallAfter).
"""

import time

from . import api_client, capture, diagnostics, prompts, series


class ProcessResult:
    def __init__(self):
        self.pages_done = 0
        self.pages_failed = []
        self.cancelled = False
        self.error = ""


def make_batches(page_numbers, batch_size):
    """Split page numbers into consecutive-run batches of at most batch_size.

    Keeping batches consecutive matters: the model reads pages in story
    order, and gaps (already-processed pages) should not be bridged inside
    a single request.
    """
    batches = []
    current = []
    for number in page_numbers:
        if current and (len(current) >= batch_size
                        or number != current[-1] + 1):
            batches.append(current)
            current = []
        current.append(number)
    if current:
        batches.append(current)
    return batches


def align_to_batch(scripts, batch):
    """Map a model's page numbering onto the pages we actually asked for.

    Models sometimes number their output from 1 ("=== PAGE 1 ===") no
    matter which pages were sent, so a batch of page 2 comes back
    labelled page 1 and would otherwise be discarded as unparseable.

    When the response contains exactly as many page blocks as the batch
    but the numbers do not match, the blocks are taken in order and
    assigned to the batch's pages: the images were sent in order and the
    model was told so, which makes position the reliable signal and the
    label the unreliable one.

    Anything else is returned untouched, so a genuinely partial response
    is still reported as partial rather than being silently misfiled.
    """
    if not scripts:
        return scripts
    if all(number in scripts for number in batch):
        return scripts
    if len(scripts) != len(batch):
        return scripts
    ordered = [scripts[key] for key in sorted(scripts)]
    return dict(zip(batch, ordered))


def process_book(book, settings, on_progress=None, cancel_check=None,
                 pages=None):
    """Process pages of `book`.

    By default every unprocessed page is done. Pass `pages` (a list of
    1-based page numbers) to process an explicit set instead, which is
    how reprocessing a range works: the caller clears those pages'
    scripts first, then names them here.

    on_progress(message, done, total) is called with human-readable status.
    cancel_check() returning True stops after the current request.
    Returns a ProcessResult.
    """
    result = ProcessResult()
    if pages is None:
        pending = book.unprocessed_pages()
    else:
        # Trust the caller's order but keep only real, unprocessed pages,
        # so a stale range cannot resend work that is already done.
        pending = [n for n in pages
                   if 1 <= n <= book.page_count and n not in book.scripts]
    total = len(pending)
    if not pending:
        return result

    comic_type = settings.get("comic_type") or settings.get(
        "reading_direction", "manga")
    custom_prompt = ""
    custom_map = settings.get("custom_prompts")
    if isinstance(custom_map, dict):
        resolved = {"rtl": "manga", "ltr": "western",
                    "vertical": "webtoon"}.get(comic_type, comic_type)
        custom_prompt = custom_map.get(resolved, "")
    system_prompt = prompts.build_system_prompt(
        comic_type, settings["verbosity"],
        settings["output_language"], custom_prompt=custom_prompt)

    # Exhaustive scripts are long: scale the response budget with
    # verbosity and batch size so scripts are never cut off mid-page.
    per_page_tokens = {"concise": 700, "detailed": 1500,
                       "extensive": 3200}.get(settings["verbosity"], 1500)
    batch_size = max(1, int(settings["pages_per_request"]))
    needed_tokens = per_page_tokens * batch_size + 1000
    client_settings = dict(settings)
    client_settings["max_tokens"] = max(
        int(settings.get("max_tokens", 8000)), needed_tokens)

    try:
        client = api_client.create_client(client_settings)
    except api_client.ApiError as error:
        result.error = str(error)
        return result
    except Exception as error:  # misconfiguration, unexpected failure
        result.error = "Could not start the AI client: %s" % error
        return result

    batches = make_batches(pending, max(1, int(settings["pages_per_request"])))
    delay = float(settings.get("request_delay_seconds", 0))

    # What the series knows is merged in at send time and never
    # written into the book. Folding it into book.character_notes
    # would make every character in the series look like one this
    # volume has met, and the pictures are ordered by exactly that.
    bank = (series.load_series(book.series) if getattr(book, "series", "")
            else None)
    if bank and not bank.get("characters"):
        bank = None

    def notes_to_send():
        """The book's own notes, with the series bank behind them."""
        if not bank:
            return book.character_notes
        return series.notes_for_book(bank, book.character_notes)

    def references_now():
        """Pictures to send, the people this volume is about first."""
        if not bank:
            return []
        return series.pictures_for_prompt(
            bank, names=series.names_in_notes(book.character_notes))

    captured_pictures = [False]

    def capture_pictures(batch, image_paths):
        """Ask once where the characters are, and cut the crops out.

        A reader who cannot see the book cannot choose a reference
        picture, so the model is asked to point at each character and
        the app crops the page itself. One request per run, skipped
        entirely when every character already has a picture, and
        allowed to fail without touching the run.
        """
        missing = capture.characters_without_pictures(
            bank, series.names_in_notes(book.character_notes))
        if not missing:
            return False
        text = "%s\n\nCHARACTER NOTES:\n%s" % (capture.PROMPT,
                                               notes_to_send())
        content = api_client.build_content(batch, image_paths, text)
        try:
            answer = client.request_scripts(
                "You look at comic pages and answer with JSON only.",
                content, cancel_check=cancel_check)
            boxes = capture.parse_boxes(answer)
            if not boxes:
                return True
            saved = capture.store(
                bank, book, boxes,
                dict(zip(batch, image_paths)))
            if saved:
                series.save_series(bank)
        except Exception:
            # Reference pictures are a bonus. A book that processes
            # without them is still a finished book.
            pass
        return True

    if hasattr(client, "on_key_switch") and on_progress:
        def announce_key_switch(new_index, key_total, reason):
            on_progress(
                "Switching to API key %d of %d. Previous key: %s"
                % (new_index, key_total, reason), result.pages_done, total)
        client.on_key_switch = announce_key_switch

    if on_progress:
        on_progress(
            "Starting: %d pages to process in %d batches. Each batch is "
            "one AI request and typically takes 20 to 90 seconds, so "
            "quiet gaps between announcements are normal."
            % (total, len(batches)), 0, total)

    def request_one_page(number):
        """Ask for a single page on its own, returning its script or None.

        Used to recover a page the model merged into a neighbour's
        section: sent alone, there is no other image to merge it with.
        """
        paths = [book.page_image_path(number)]
        text = prompts.build_user_text(
            [number], notes_to_send(), book.title,
            user_instructions=book.user_instructions)
        content = api_client.build_content([number], paths, text,
                                           references=references_now())
        response = client.request_scripts(
            system_prompt, content, cancel_check=cancel_check)
        got, _ = prompts.parse_response(
            response, previous_notes=book.character_notes)
        return align_to_batch(got, [number]).get(number)

    for batch_index, batch in enumerate(batches):
        if cancel_check and cancel_check():
            result.cancelled = True
            return result

        if on_progress:
            on_progress(
                "Processing pages %d to %d (batch %d of %d)..."
                % (batch[0], batch[-1], batch_index + 1, len(batches)),
                result.pages_done, total)

        image_paths = [book.page_image_path(n) for n in batch]
        started_at = time.time()
        diagnostics.write(
            "processing", "batch sent", book=book.title,
            pages="%d-%d" % (batch[0], batch[-1]),
            model=settings.get("%s_model" % settings.get("provider", ""), "?"),
            provider=settings.get("provider", "?"),
            pictures=len(references_now()),
            notes_characters=len(series.names_in_notes(notes_to_send())))
        user_text = prompts.build_user_text(
            batch, notes_to_send(), book.title,
            user_instructions=book.user_instructions)
        content = api_client.build_content(batch, image_paths, user_text,
                                           references=references_now())

        try:
            response_text = client.request_scripts(
                system_prompt, content, cancel_check=cancel_check)
            scripts, notes = prompts.parse_response(
                response_text, previous_notes=book.character_notes)
            scripts = align_to_batch(scripts, batch)
            diagnostics.write(
                "processing", "batch answered",
                pages="%d-%d" % (batch[0], batch[-1]),
                seconds=time.time() - started_at,
                pages_returned=len(scripts), characters=len(response_text))
        except api_client.ApiError as error:
            if "Cancelled" in str(error):
                result.cancelled = True
                return result
            diagnostics.failure(
                "processing", "batch failed", error,
                pages="%d-%d" % (batch[0], batch[-1]),
                seconds=time.time() - started_at)
            result.error = str(error)
            result.pages_failed.extend(batch)
            return result
        except ValueError:
            # Unparseable response: skip this batch, keep going. These
            # pages stay unprocessed and a Resume pass will retry them.
            result.pages_failed.extend(batch)
            if on_progress:
                on_progress(
                    "Pages %d to %d could not be parsed; they will be "
                    "retried on Resume." % (batch[0], batch[-1]),
                    result.pages_done, total)
            continue
        except Exception as error:
            # Anything unforeseen (an unreadable page file, a library
            # fault): stop with a readable message rather than killing
            # the worker thread. Pages already saved are unaffected.
            result.error = "Unexpected error on pages %d to %d: %s" % (
                batch[0], batch[-1], error)
            result.pages_failed.extend(batch)
            return result

        if cancel_check and cancel_check():
            # Cancelled while this request was in flight: discard its
            # result rather than saving, so a cancelled run can never
            # overwrite work done by a newer one.
            result.cancelled = True
            return result

        # Models sometimes describe two images under one page header,
        # which would silently lose the second page. Ask for anything
        # missing on its own rather than dropping it -- alone, there is
        # nothing for it to be merged with.
        missing = [n for n in batch if n not in scripts]
        if missing and len(batch) > 1:
            for number in missing:
                if cancel_check and cancel_check():
                    result.cancelled = True
                    return result
                if on_progress:
                    on_progress(
                        "Page %d came back combined with another page; "
                        "asking for it on its own." % number,
                        result.pages_done, total)
                try:
                    recovered = request_one_page(number)
                except Exception:
                    recovered = None  # leave it for a later Process again
                if recovered:
                    scripts[number] = recovered

        for number in batch:
            if number in scripts:
                book.scripts[number] = scripts[number]
                result.pages_done += 1
            else:
                result.pages_failed.append(number)
        # Record what the pages were actually produced in, so an
        # export can label the book correctly later even if the
        # setting has changed.
        book.output_language = settings.get("output_language", "English")
        if notes:
            book.character_notes = notes
        if bank and not captured_pictures[0]:
            captured_pictures[0] = capture_pictures(batch, image_paths)
        book.save()  # crash-safe checkpoint after every batch

        if on_progress:
            percent = int(round(100.0 * result.pages_done / total))
            on_progress(
                "Saved pages %d to %d. %d of %d pages done, %d percent."
                % (batch[0], batch[-1], result.pages_done, total, percent),
                result.pages_done, total)

        is_last = batch_index == len(batches) - 1
        if delay > 0 and not is_last:
            waited = 0.0
            while waited < delay:
                if cancel_check and cancel_check():
                    result.cancelled = True
                    return result
                time.sleep(min(1.0, delay - waited))
                waited += 1.0

    return result
