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
import json
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

# Models that can speak. The default is the current preview model; the
# list is offered in Settings and can be refreshed like the others.
TTS_MODELS = [
    "gemini-3.1-flash-tts-preview",
    "gemini-2.5-flash-preview-tts",
    "gemini-2.5-pro-preview-tts",
]
DEFAULT_TTS_MODEL = TTS_MODELS[0]

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Audio comes back as 16-bit mono at this rate; both numbers are needed
# to encode it and to work out how long a piece is.
SAMPLE_RATE = 24000
SAMPLE_WIDTH = 2

# Roughly two minutes of speech, well inside the point where quality is
# documented to drift. Measured in characters because that is what we
# have before the audio exists.
CHUNK_CHARACTERS = 1600

TIMEOUT_SECONDS = 300

# Pieces are independent, so several are spoken at once. This is the
# difference between a ten-page book taking a few minutes and taking a
# quarter of an hour: each request produces around two minutes of
# speech, and the service will work on several at a time. Kept low, and
# spread across however many keys are configured, so a rate limit is
# not provoked.
DEFAULT_WORKERS = 3

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
        raise SpeechError("the service sent an unexpected reply.")
    candidates = data.get("candidates") or []
    for candidate in candidates:
        for part in (candidate.get("content") or {}).get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])
    raise SpeechError(
        "the service replied without any audio, which it does "
        "occasionally; trying again usually works.")


def encode_mp3(pcm, bitrate=64):
    """Encode 16-bit mono PCM to MP3 bytes."""
    try:
        import lameenc
    except ImportError:
        raise SpeechError(
            "the MP3 encoder is missing from this build, so audio "
            "cannot be saved.")
    encoder = lameenc.Encoder()
    encoder.set_bit_rate(bitrate)
    encoder.set_in_sample_rate(SAMPLE_RATE)
    encoder.set_channels(1)
    encoder.set_quality(5)  # middle of the range: decent, and quick
    return bytes(encoder.encode(pcm)) + bytes(encoder.flush())


def pcm_to_wav(pcm):
    """Wrap raw PCM in a WAV container so it can be played.

    Used for voice previews: Windows can play WAV without any decoder,
    whereas the MP3 we save would need one.
    """
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(SAMPLE_WIDTH)
        handle.setframerate(SAMPLE_RATE)
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


def seconds_of(pcm):
    """How long a stretch of PCM lasts, for progress reporting."""
    return len(pcm) / float(SAMPLE_RATE * SAMPLE_WIDTH)


def _speak_with_retry(speak, text, key, index):
    """One piece, retried. Returns PCM or raises the last failure.

    The service answers with text instead of audio often enough that
    Google documents it, so a piece that fails is worth another go
    before the whole run is abandoned.
    """
    last = None
    for attempt in range(3):
        try:
            return speak(text, key)
        except SpeechError as error:
            last = error
        except urllib.error.HTTPError as error:
            if error.code in (400, 401, 403):
                # A key or model problem: retrying only repeats it.
                raise SpeechError(
                    "the service refused part %d (error %s). Check the "
                    "API key and the chosen voice model."
                    % (index + 1, error.code))
            last = SpeechError(
                "the service refused part %d (error %s)."
                % (index + 1, error.code))
        except Exception as error:
            last = SpeechError(
                "part %d could not be spoken: %s" % (index + 1, error))
        if attempt < 2:
            # Backing off matters most for a rate limit, which is the
            # likeliest reason several pieces fail at once.
            time.sleep(3 * (attempt + 1))
    raise last or SpeechError("part %d could not be spoken." % (index + 1))


def write_mp3(book, path, settings, on_progress=None, cancel_check=None,
              request=None, workers=None, pages=None):
    """Speak a whole book into one MP3 file.

    on_progress(message, done, total) is called as pieces finish.
    cancel_check() returning True stops the run; nothing is written, so
    a cancelled run leaves no half-finished file behind.

    Pieces are spoken several at a time, since each request takes about
    as long as the speech it produces and they do not depend on one
    another. They are reassembled in order regardless of the order they
    come back in.

    `request` exists so the chunking, retrying, ordering and encoding
    can all be tested without calling the service.
    """
    keys = [key for key in settings.get("gemini_api_keys", []) if key.strip()]
    if not keys:
        raise SpeechError(
            "speaking a book uses Gemini, so a Gemini API key is needed "
            "in Settings, even when another service is used for reading.")
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
            "there are no processed pages in that range to speak.")
    chunks = split_for_speech(lines)

    # More keys means more can be in flight without troubling any one
    # of them, but the ceiling stays low either way.
    limit = workers or min(DEFAULT_WORKERS * len(keys), DEFAULT_WORKERS + 2)
    limit = max(1, min(limit, len(chunks)))

    pieces = [None] * len(chunks)
    done = 0
    failure = None

    def work(index):
        return index, _speak_with_retry(
            speak, chunks[index], keys[index % len(keys)], index)

    if on_progress:
        on_progress("Reading %d part%s aloud..."
                    % (len(chunks), "" if len(chunks) == 1 else "s"),
                    0, len(chunks) + 1)

    with concurrent.futures.ThreadPoolExecutor(max_workers=limit) as pool:
        futures = [pool.submit(work, index) for index in range(len(chunks))]
        for future in concurrent.futures.as_completed(futures):
            if cancel_check and cancel_check():
                for pending in futures:
                    pending.cancel()
                return None
            try:
                index, pcm = future.result()
            except Exception as error:
                failure = error
                for pending in futures:
                    pending.cancel()
                break
            pieces[index] = pcm
            done += 1
            if on_progress:
                on_progress("Spoken %d of %d parts." % (done, len(chunks)),
                            done, len(chunks) + 1)
    if failure is not None:
        raise failure
    if cancel_check and cancel_check():
        return None
    if any(piece is None for piece in pieces):
        raise SpeechError("some parts of the book could not be spoken.")

    if on_progress:
        on_progress("Encoding the audio...", len(chunks), len(chunks) + 1)
    audio = b"".join(pieces)
    with open(path, "wb") as handle:
        handle.write(encode_mp3(audio))
    return seconds_of(audio)
