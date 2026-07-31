"""Turning a processed book into spoken audio.

Gemini's text-to-speech models return raw PCM: 16-bit signed samples at
24 kHz, with no container. That is unusable as a file -- a four hour
book would be about 700 MB of WAV -- so it is encoded to MP3 here,
which brings the same book down to roughly 120 MB.

Two limits from Google's own documentation shape the design:

  * speech quality drifts on outputs longer than a few minutes, so the
    book is sent in small pieces rather than one request;
  * the model occasionally returns text instead of audio and the
    request fails, which is expected rather than exceptional, so a
    piece is retried before the run is given up on.

A whole volume is several hours of speech and a large amount of a
service's allowance, so callers are expected to report progress and to
offer cancelling.
"""

import base64
import concurrent.futures
import io
import os
import random
import re
import threading
import json
import tempfile
import time
import wave
import urllib.error
import urllib.request

from . import export

# Gemini's prebuilt voices. The names are the API's own; the
# descriptions are Google's short characterisations, kept so the
# settings dialog can say something more useful than a bare name.
VOICES = [
    ("Zephyr", "Bright"),
    ("Puck", "Upbeat"),
    ("Charon", "Informative"),
    ("Kore", "Firm"),
    ("Fenrir", "Excitable"),
    ("Leda", "Youthful"),
    ("Orus", "Firm"),
    ("Aoede", "Breezy"),
    ("Callirrhoe", "Easy-going"),
    ("Autonoe", "Bright"),
    ("Enceladus", "Breathy"),
    ("Iapetus", "Clear"),
    ("Umbriel", "Easy-going"),
    ("Algieba", "Smooth"),
    ("Despina", "Smooth"),
    ("Erinome", "Clear"),
    ("Algenib", "Gravelly"),
    ("Rasalgethi", "Informative"),
    ("Laomedeia", "Upbeat"),
    ("Achernar", "Soft"),
    ("Alnilam", "Firm"),
    ("Schedar", "Even"),
    ("Gacrux", "Mature"),
    ("Pulcherrima", "Forward"),
    ("Achird", "Friendly"),
    ("Zubenelgenubi", "Casual"),
    ("Vindemiatrix", "Gentle"),
    ("Sadachbia", "Lively"),
    ("Sadaltager", "Knowledgeable"),
    ("Sulafat", "Warm"),
]

DEFAULT_VOICE = "Kore"

# Which engine reads the book.  The Windows identifier is retained for
# settings written by the earlier test build, but the audio dialog now offers
# Kokoro and Gemini.
ENGINE_GEMINI = "gemini"
ENGINE_KOKORO = "kokoro"
ENGINE_WINDOWS = "windows"
DEFAULT_ENGINE = ENGINE_KOKORO

# Voice models, offered when saving as audio so a reader can try
# another if one is refusing or sounds wrong. Every one of them is a
# preview release, which is why allowances for them are tight; there is
# no settled voice model to fall back on.
TTS_MODELS = [
    ("gemini-3.1-flash-tts-preview", "Preview"),
    ("gemini-2.5-flash-preview-tts", "Preview"),
    ("gemini-2.5-pro-preview-tts", "Preview"),
]
DEFAULT_TTS_MODEL = TTS_MODELS[0][0]

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Audio comes back as 16-bit mono at this rate; both numbers are needed
# to encode it and to work out how long a piece is.
SAMPLE_RATE = 24000
SAMPLE_WIDTH = 2

# Roughly four minutes of speech. Google warns that quality drifts on
# outputs longer than a few minutes, so this stays under that -- but
# every extra piece is another request, another wait for a turn and
# another chance of being refused, so cutting the book more finely than
# necessary makes a run slower rather than safer.
CHUNK_CHARACTERS = 3200

# These are scheduling and partial-save boundaries, not model context
# boundaries.  core.kokoro splits the resulting phonemes losslessly below the
# model's 510-character inference ceiling.  Larger outer pieces avoid hundreds
# of Python tasks for a chapter while still leaving regular points at which a
# stopped export can publish everything completed in order.
KOKORO_CHUNK_CHARACTERS = 8000
KOKORO_WORKERS = 2

TIMEOUT_SECONDS = 300

# Pieces are independent, so several are spoken at once: each request
# produces around two minutes of speech and the service will work on
# more than one at a time. Kept deliberately low, because free-tier
# text-to-speech is limited per minute rather than by how much work is
# in flight, and asking for too much at once simply earns a 429.
RATE_LIMIT_WAITS = (20, 45, 90, 150)


def _wait(seconds, cancel_check=None):
    """Sleep, but in slices so a cancel is noticed promptly.

    A rate-limit backoff can run well over a minute. Someone who has
    changed their mind should not have to sit through it, and the run
    should stop rather than carry on after the wait.

    Returns False if it was cancelled part way.
    """
    deadline = time.time() + seconds
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            return True
        if cancel_check and cancel_check():
            return False
        time.sleep(min(0.5, remaining))
# One at a time. Free allowances run to only a handful of requests a
# minute, and preview voice models less still, so asking for two at
# once simply earns two refusals instead of one -- and both then wake
# together and collide again.
DEFAULT_WORKERS = 1

# Requests start close together and are spaced further apart only when
# the service pushes back, so somebody with room to spare is not slowed
# down for nothing while somebody on a free allowance still settles at
# a pace it permits.
MIN_SPACING = 1.0
MAX_SPACING = 30.0

# Short line used to preview a voice before committing a whole book to
# it. Deliberately brief: previewing costs allowance too.
SAMPLE_TEXT = ("This is how I sound. A street at dusk, with two "
               "characters facing each other.")


class SpeechError(Exception):
    """Raised when a book cannot be turned into audio."""


def book_text(book, show_panel_labels=True, pages=None):
    """The book as plain lines to be spoken, one per line.

    Built from the same outline as every other export, so the audio
    says exactly what the other formats show. `pages` narrows it to a
    range, which is how a reader keeps the cost of a long book down.
    """
    # Unprocessed pages are left out rather than read: an audiobook
    # announcing "this page has not been processed yet" every so often
    # is worse than simply not containing it.
    wanted = range(1, book.page_count + 1) if pages is None else pages
    ready = [n for n in wanted if (book.scripts.get(n) or "").strip()]
    if not ready:
        return []
    lines = []
    for kind, text in export.book_outline(
            book, show_panel_labels=show_panel_labels, pages=ready):
        text = text.strip()
        if not text:
            continue
        # A heading read straight into the next sentence is hard to
        # follow, so each one ends with a full stop if it has no
        # punctuation of its own.
        if kind != "p" and text[-1] not in ".!?:":
            text += "."
        lines.append(text)
    return lines


def split_for_speech(lines, limit=CHUNK_CHARACTERS):
    """Group lines into pieces small enough to be spoken well.

    Splitting happens between lines, never inside one, so a sentence is
    never cut in half across two requests -- the join would be audible.
    A single line longer than the limit is left whole for the same
    reason.
    """
    chunks = []
    current = []
    length = 0
    for line in lines:
        if current and length + len(line) + 1 > limit:
            chunks.append("\n".join(current))
            current, length = [], 0
        current.append(line)
        length += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def split_for_kokoro(lines, limit=KOKORO_CHUNK_CHARACTERS):
    """Split local speech at line, sentence, then word boundaries.

    Book lines normally fit unchanged.  A single long narrative paragraph
    must still be divided, because Kokoro has a finite phoneme context and
    silently truncating it would omit part of the book.
    """
    prepared = []
    for line in lines:
        if len(line) <= limit:
            prepared.append(line)
            continue
        # The zero-width alternative also separates CJK sentences, where
        # punctuation is normally followed immediately by the next character.
        sentences = [part.strip() for part in re.split(
            r"(?<=[.!?。！？])(?:\s+|(?=\S))", line) if part.strip()]
        for sentence in sentences:
            if len(sentence) <= limit:
                prepared.append(sentence)
                continue
            words = sentence.split()
            if len(words) <= 1:
                # Scripts without spaces still need a lossless last resort.
                prepared.extend(sentence[start:start + limit]
                                for start in range(0, len(sentence), limit))
                continue
            current = []
            length = 0
            for word in words:
                if len(word) > limit:
                    if current:
                        prepared.append(" ".join(current))
                        current, length = [], 0
                    prepared.extend(word[start:start + limit]
                                    for start in range(0, len(word), limit))
                    continue
                if current and length + len(word) + 1 > limit:
                    prepared.append(" ".join(current))
                    current, length = [], 0
                current.append(word)
                length += len(word) + 1
            if current:
                prepared.append(" ".join(current))
    return split_for_speech(prepared, limit=limit)


def _request_audio(text, api_key, model, voice, timeout=TIMEOUT_SECONDS):
    """One piece of text to raw PCM bytes."""
    payload = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": voice}
                }
            },
        },
    }
    request = urllib.request.Request(
        "%s/%s:generateContent" % (BASE_URL, model),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "x-goog-api-key": api_key},
        method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    return extract_audio(data)


def extract_audio(data):
    """Pull the PCM bytes out of a response, or explain what came back.

    Kept separate from the request so it can be tested without network
    access, and because the failure worth naming -- the model returning
    words instead of speech -- is visible only here.
    """
    if not isinstance(data, dict):
        raise SpeechError("Gemini sent back something unexpected.")
    candidates = data.get("candidates") or []
    for candidate in candidates:
        for part in (candidate.get("content") or {}).get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])
    raise SpeechError(
        "Gemini sent words back instead of speech. This happens now "
        "and then, and trying again usually works.")


def mp3_encoder(bitrate=64, sample_rate=None, channels=1):
    """Create the incremental encoder used by samples and long books."""
    try:
        import lameenc
    except ImportError:
        raise SpeechError(
            "This copy of the app cannot save MP3 files.")
    encoder = lameenc.Encoder()
    encoder.set_bit_rate(bitrate)
    encoder.set_in_sample_rate(sample_rate or SAMPLE_RATE)
    encoder.set_channels(channels)
    encoder.set_quality(5)  # middle of the range: decent, and quick
    return encoder


def encode_mp3(pcm, bitrate=64, sample_rate=None, channels=1):
    """Encode 16-bit PCM to MP3 bytes.

    The rate is a parameter because the speech engines may produce
    different sample rates. Encoding at the wrong rate plays back at the
    wrong speed, so the caller passes what it actually has.
    """
    encoder = mp3_encoder(bitrate, sample_rate, channels)
    return bytes(encoder.encode(pcm)) + bytes(encoder.flush())


def pcm_to_wav(pcm, sample_rate=None, channels=1):
    """Wrap raw PCM in a WAV container so it can be played.

    Used for voice previews: Windows can play WAV without any decoder,
    whereas the MP3 we save would need one.
    """
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(SAMPLE_WIDTH)
        handle.setframerate(sample_rate or SAMPLE_RATE)
        handle.writeframes(pcm)
    return buffer.getvalue()


def sample_voice(voice, settings, request=None):
    """Speak one short line in `voice`, returned as playable WAV bytes."""
    keys = [key for key in settings.get("gemini_api_keys", []) if key.strip()]
    if not keys:
        raise SpeechError(
            "previewing a voice uses Gemini, so a Gemini API key is "
            "needed in Settings.")
    model = settings.get("tts_model") or DEFAULT_TTS_MODEL
    speak = request or (
        lambda text: _request_audio(text, keys[0], model, voice))
    return pcm_to_wav(speak(SAMPLE_TEXT))


def sample_kokoro_voice(voice, language, request=None):
    """Generate a playable local sample in one Kokoro voice."""
    from . import kokoro
    try:
        pcm, rate, channels = (
            request(kokoro.sample_text(language)) if request
            else kokoro.speak(kokoro.sample_text(language), voice, language))
    except kokoro.KokoroError as error:
        raise SpeechError(str(error))
    return pcm_to_wav(pcm, sample_rate=rate, channels=channels)


def seconds_of(pcm, sample_rate=None, channels=1):
    """How long a stretch of PCM lasts, for progress reporting."""
    return len(pcm) / float(
        (sample_rate or SAMPLE_RATE) * SAMPLE_WIDTH * channels)


class Pacer:
    """Keeps requests far enough apart to stay inside a rate limit."""

    def __init__(self, spacing=MIN_SPACING):
        self._spacing = spacing
        self._next = 0.0
        self._lock = threading.Lock()

    @property
    def spacing(self):
        return self._spacing

    def wait_turn(self, cancel_check=None):
        with self._lock:
            due = max(self._next, time.time())
            self._next = due + self._spacing
        delay = due - time.time()
        return _wait(delay, cancel_check) if delay > 0 else True

    def slow_down(self):
        """Called after a refusal: leave more room next time."""
        with self._lock:
            self._spacing = min(MAX_SPACING, max(self._spacing * 1.6, 8.0))
            return self._spacing


def rate_limit_details(error):
    """What a 429 actually said: how long to wait, and what ran out.

    Read once, because the body of an HTTPError can only be read once.
    Knowing which allowance was exhausted matters: a per-minute limit
    is worth waiting out, while a daily one will not clear until it
    resets, so retrying is pointless and saying so is kinder than
    trying for several minutes and then failing anyway.
    """
    try:
        data = json.loads(error.read().decode("utf-8", "replace"))
    except Exception:
        return None, None, False
    delay = None
    quota = None
    daily = False
    for detail in (data.get("error") or {}).get("details") or []:
        value = detail.get("retryDelay")
        if isinstance(value, str) and value.endswith("s"):
            try:
                delay = min(300, max(1, int(float(value[:-1]))))
            except ValueError:
                pass
        for violation in detail.get("violations") or []:
            identifier = (violation.get("quotaId")
                          or violation.get("quotaMetric") or "")
            if identifier:
                quota = identifier
                if "perday" in identifier.lower().replace("_", ""):
                    daily = True
    return delay, quota, daily


def retry_delay_from(error):
    """Seconds the service asked us to wait, if it said.

    A 429 body carries Google's own RetryInfo. Honouring it is far
    better than guessing, because the limit is per minute and a guess
    that is too short simply earns another refusal.
    """
    try:
        body = error.read()
    except Exception:
        return None
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return None
    for detail in (data.get("error") or {}).get("details") or []:
        delay = detail.get("retryDelay")
        if isinstance(delay, str) and delay.endswith("s"):
            try:
                return min(300, max(1, int(float(delay[:-1]))))
            except ValueError:
                continue
    return None


def _speak_with_retry(speak, text, key, index, notify=None,
                      cancel_check=None, pacer=None):
    """One piece, retried. Returns PCM or raises the last failure.

    Two very different failures are handled here. The service answers
    with text instead of audio often enough that Google documents it,
    and that is worth an immediate second go. A rate limit is not a
    fault at all -- it means slow down -- so it waits much longer, and
    for as long as the service itself asks, rather than giving up on a
    book most of the way through.
    """
    last = None
    rate_limited = 0
    attempt = 0
    while attempt < 4 and rate_limited < len(RATE_LIMIT_WAITS):
        try:
            if pacer is not None and not pacer.wait_turn(cancel_check):
                raise SpeechError("Stopped.")
            return speak(text, key)
        except SpeechError as error:
            last = error
            wait = 3 * (attempt + 1)
            attempt += 1
        except urllib.error.HTTPError as error:
            if error.code in (400, 401, 403):
                # A key or model problem: retrying only repeats it.
                raise SpeechError(
                    "Gemini would not accept the request. Check that "
                    "your API key is correct and that it can use the "
                    "chosen voice model.")
            if error.code == 429:
                asked, quota, daily = rate_limit_details(error)
                if daily:
                    # A daily allowance does not come back by waiting;
                    # it resets at midnight Pacific time.
                    raise SpeechError(
                        "Today's Gemini limit has been used up, so "
                        "nothing more can be read aloud today. It "
                        "resets at midnight Pacific time.")
                wait = asked or RATE_LIMIT_WAITS[rate_limited]
                # A little randomness so pieces that were refused
                # together do not wake together and collide again.
                wait += random.uniform(0, 3)
                rate_limited += 1
                if pacer is not None:
                    pacer.slow_down()
                last = SpeechError(
                    "Gemini is limiting how often it will answer.")
                if notify:
                    notify("Gemini is busy. Waiting %d seconds, then "
                           "carrying on." % wait)
            else:
                last = SpeechError(
                    "Gemini would not answer just then.")
                wait = 3 * (attempt + 1)
                attempt += 1
        except Exception as error:
            last = SpeechError(
                "Part %d could not be read aloud: %s" % (index + 1, error))
            wait = 3 * (attempt + 1)
            attempt += 1
        if not _wait(wait, cancel_check):
            raise SpeechError("Stopped.")
    if rate_limited >= len(RATE_LIMIT_WAITS):
        raise SpeechError(
            "Gemini kept refusing, so the audio was not finished. A "
            "free Gemini account only allows a few requests a minute. "
            "Waiting a while, or choosing fewer pages, usually works.")
    raise last or SpeechError("Part %d could not be read aloud." % (index + 1))


def _write_mp3_locally(book, path, settings, on_progress=None,
                       cancel_check=None):
    """Read a book with the computer's own voice.

    Much simpler than going out to a service: there is no allowance to
    run out of, nothing to be refused by and no waiting between pieces.
    The book is still cut up, but only so progress can be reported and
    a cancel noticed part way through.
    """
    from . import winspeech
    if not winspeech.available():
        raise SpeechError(
            "This computer's own voices are not available, so choose "
            "Gemini instead.")
    lines = book_text(
        book, show_panel_labels=bool(settings.get("show_panel_labels", True)),
        pages=settings.get("_pages"))
    if not lines:
        raise SpeechError("There are no processed pages in that range to read.")
    chunks = split_for_speech(lines)
    voice_id = settings.get("windows_voice") or None

    audio = bytearray()
    rate = None
    channels = 1
    for index, chunk in enumerate(chunks, start=1):
        if cancel_check and cancel_check():
            return None
        if on_progress:
            on_progress("Reading part %d of %d." % (index, len(chunks)),
                        index - 1, len(chunks) + 1)
        try:
            pcm, chunk_rate, chunk_channels = winspeech.speak(chunk, voice_id)
        except winspeech.WindowsSpeechError as error:
            raise SpeechError(str(error))
        if rate is None:
            rate, channels = chunk_rate, chunk_channels
        audio.extend(pcm)

    if cancel_check and cancel_check():
        return None
    if on_progress:
        on_progress("Saving the audio file.", len(chunks), len(chunks) + 1)
    with open(path, "wb") as handle:
        handle.write(encode_mp3(bytes(audio), sample_rate=rate,
                                channels=channels))
    return len(audio) / float((rate or SAMPLE_RATE) * SAMPLE_WIDTH * channels)


def _temporary_audio_path(path):
    """A private file beside the destination, suitable for atomic replace."""
    folder = os.path.dirname(os.path.abspath(path))
    descriptor, temporary = tempfile.mkstemp(
        prefix=".accessible-manga-audio-", suffix=".tmp", dir=folder)
    os.close(descriptor)
    return temporary


def _write_mp3_with_kokoro(book, path, settings, on_progress=None,
                           cancel_check=None, request=None, workers=None,
                           pages=None, save_partial_check=None):
    """Generate a book locally, streaming encoded data to a private file."""
    from . import kokoro

    lines = book_text(
        book, show_panel_labels=bool(settings.get("show_panel_labels", True)),
        pages=pages)
    if not lines:
        raise SpeechError("There are no processed pages in that range to read.")
    chunks = split_for_kokoro(lines)
    voice = settings.get("kokoro_voice") or kokoro.default_voice(
        settings.get("kokoro_language", kokoro.DEFAULT_LANGUAGE))
    language = settings.get("kokoro_language", kokoro.DEFAULT_LANGUAGE)

    if on_progress:
        on_progress("Preparing %d part%s for Kokoro."
                    % (len(chunks), "" if len(chunks) == 1 else "s"),
                    0, len(chunks) + 1)

    try:
        if request is not None:
            work_items = chunks

            def make(item):
                result = request(item)
                if isinstance(result, tuple):
                    return result
                return result, SAMPLE_RATE, 1
        else:
            engine = kokoro.load_engine()
            work_items = []
            for chunk in chunks:
                if cancel_check and cancel_check():
                    return None
                work_items.append(kokoro.phonemize(chunk, language, engine))

            def make(item):
                return kokoro.synthesize_phonemes(
                    item, voice, engine, cancel_check=cancel_check)
    except kokoro.KokoroError as error:
        raise SpeechError(str(error))

    limit = max(1, min(workers or KOKORO_WORKERS, len(work_items)))
    temporary = _temporary_audio_path(path)
    encoder = None
    sample_rate = None
    channels = None
    duration = 0.0
    completed = 0
    stopped = False
    publish = False
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=limit)
    futures = []
    try:
        with open(temporary, "wb") as output:
            futures = [pool.submit(make, item) for item in work_items]
            for index, future in enumerate(futures, start=1):
                while not future.done():
                    if cancel_check and cancel_check():
                        stopped = True
                        break
                    concurrent.futures.wait((future,), timeout=0.2)
                if stopped:
                    break
                try:
                    pcm, rate, channel_count = future.result()
                except kokoro.SynthesisCancelled:
                    if cancel_check and cancel_check():
                        stopped = True
                        break
                    raise SpeechError("Kokoro stopped unexpectedly.")
                except kokoro.KokoroError as error:
                    for pending in futures:
                        pending.cancel()
                    raise SpeechError(str(error))
                except Exception as error:
                    for pending in futures:
                        pending.cancel()
                    raise SpeechError(
                        "Kokoro could not generate the audio: %s" % error)
                if encoder is None:
                    sample_rate, channels = rate, channel_count
                    encoder = mp3_encoder(
                        sample_rate=sample_rate, channels=channels)
                elif rate != sample_rate or channel_count != channels:
                    raise SpeechError(
                        "Kokoro returned audio in inconsistent formats.")
                output.write(bytes(encoder.encode(pcm)))
                duration += seconds_of(pcm, rate, channel_count)
                completed = index
                if on_progress:
                    on_progress(
                        "Generated %d of %d parts with Kokoro."
                        % (index, len(work_items)),
                        index, len(work_items) + 1)
                if cancel_check and cancel_check():
                    stopped = True
                    break

            if not stopped and cancel_check and cancel_check():
                stopped = True

            if stopped:
                for pending in futures:
                    pending.cancel()
                keep = bool(save_partial_check and save_partial_check())
                if keep and encoder is not None and completed:
                    if on_progress:
                        on_progress("Saving the completed audio.", completed,
                                    len(work_items) + 1)
                    output.write(bytes(encoder.flush()))
                    publish = True
            else:
                if encoder is None:
                    raise SpeechError("Kokoro did not generate any audio.")
                if on_progress:
                    on_progress("Saving the audio file.", len(work_items),
                                len(work_items) + 1)
                output.write(bytes(encoder.flush()))
                publish = True
        if publish:
            os.replace(temporary, path)
            temporary = None
            return duration
        return None
    finally:
        for pending in futures:
            pending.cancel()
        pool.shutdown(wait=not stopped, cancel_futures=True)
        if temporary:
            try:
                os.remove(temporary)
            except OSError:
                pass


def write_mp3(book, path, settings, on_progress=None, cancel_check=None,
              request=None, workers=None, pages=None,
              save_partial_check=None):
    """Speak a whole book into one MP3 file.

    on_progress(message, done, total) is called as pieces finish.
    cancel_check() returning True stops the run.  If save_partial_check()
    is also true, completed consecutive parts are encoded and moved into place;
    otherwise the destination is left untouched.

    Pieces are spoken several at a time, since each request takes about
    as long as the speech it produces and they do not depend on one
    another. They are reassembled in order regardless of the order they
    come back in.

    `request` exists so the chunking, retrying, ordering and encoding
    can all be tested without calling the service.
    """
    engine = settings.get("tts_engine", ENGINE_GEMINI)
    if engine == ENGINE_KOKORO:
        return _write_mp3_with_kokoro(
            book, path, settings, on_progress, cancel_check,
            request=request, workers=workers, pages=pages,
            save_partial_check=save_partial_check)
    if engine == ENGINE_WINDOWS:
        return _write_mp3_locally(book, path, dict(settings, _pages=pages),
                                  on_progress, cancel_check)
    keys = [key for key in settings.get("gemini_api_keys", []) if key.strip()]
    if not keys:
        raise SpeechError(
            "Reading a book aloud uses Gemini, so a Gemini API key is "
            "needed in Settings, even if you use another service for the "
            "pages themselves.")
    model = settings.get("tts_model") or DEFAULT_TTS_MODEL
    voice = settings.get("tts_voice") or DEFAULT_VOICE
    if request is not None:
        speak = lambda text, key: request(text)
    else:
        speak = lambda text, key: _request_audio(text, key, model, voice)

    lines = book_text(
        book, show_panel_labels=bool(settings.get("show_panel_labels", True)),
        pages=pages)
    if not lines:
        raise SpeechError(
            "There are no processed pages in that range to read.")
    chunks = split_for_speech(lines)

    # Allowances are counted per project, not per key, so extra keys
    # from the same project buy nothing here.
    limit = max(1, min(workers or DEFAULT_WORKERS, len(chunks)))
    pacer = Pacer()

    pieces = [None] * len(chunks)
    done = 0
    next_to_write = 0
    failure = None
    stopped = False
    duration = 0.0
    encoder = None
    publish = False
    notifications = threading.Event()
    notifications.set()

    def announce(message):
        if on_progress and notifications.is_set():
            on_progress(message, done, len(chunks) + 1)

    def work(index):
        return index, _speak_with_retry(
            speak, chunks[index], keys[index % len(keys)], index,
            notify=announce, cancel_check=cancel_check,
            pacer=pacer)

    if on_progress:
        on_progress("Reading %d part%s aloud."
                    % (len(chunks), "" if len(chunks) == 1 else "s"),
                    0, len(chunks) + 1)

    temporary = _temporary_audio_path(path)
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=limit)
    futures = []
    pending = set()
    try:
        futures = [pool.submit(work, index) for index in range(len(chunks))]
        pending = set(futures)
        with open(temporary, "wb") as output:
            while pending:
                completed, _ = concurrent.futures.wait(
                    pending, timeout=0.2,
                    return_when=concurrent.futures.FIRST_COMPLETED)
                for future in completed:
                    pending.remove(future)
                    try:
                        index, pcm = future.result()
                    except Exception as error:
                        if cancel_check and cancel_check():
                            stopped = True
                        else:
                            failure = error
                        break
                    pieces[index] = pcm
                    done += 1
                    if on_progress:
                        on_progress(
                            "Read %d of %d parts." % (done, len(chunks)),
                            done, len(chunks) + 1)
                while (next_to_write < len(pieces)
                       and pieces[next_to_write] is not None):
                    pcm = pieces[next_to_write]
                    if encoder is None:
                        encoder = mp3_encoder()
                    output.write(bytes(encoder.encode(pcm)))
                    duration += seconds_of(pcm)
                    pieces[next_to_write] = b""
                    next_to_write += 1
                if failure is not None or stopped:
                    break
                if cancel_check and cancel_check():
                    stopped = True
                    break

            if stopped:
                keep = bool(save_partial_check and save_partial_check())
                if keep and encoder is not None and next_to_write:
                    if on_progress:
                        on_progress("Saving the completed audio.",
                                    next_to_write, len(chunks) + 1)
                    output.write(bytes(encoder.flush()))
                    publish = True
            elif failure is None:
                if next_to_write != len(chunks):
                    failure = SpeechError(
                        "Some parts could not be read aloud.")
                elif encoder is None:
                    failure = SpeechError(
                        "Gemini did not generate any audio.")
                else:
                    if on_progress:
                        on_progress("Saving the audio file.", len(chunks),
                                    len(chunks) + 1)
                    output.write(bytes(encoder.flush()))
                    publish = True

        if failure is not None:
            raise failure
        if publish:
            os.replace(temporary, path)
            temporary = None
            return duration
        return None
    finally:
        notifications.clear()
        for future in futures:
            future.cancel()
        pool.shutdown(
            wait=not (stopped or failure is not None),
            cancel_futures=True)
        if temporary:
            try:
                os.remove(temporary)
            except OSError:
                pass
