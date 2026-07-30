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
import json
import time
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


class SpeechError(Exception):
    """Raised when a book cannot be turned into audio."""


def book_text(book, show_panel_labels=True):
    """The book as plain lines to be spoken, one per line.

    Built from the same outline as every other export, so the audio
    says exactly what the other formats show.
    """
    lines = []
    for kind, text in export.book_outline(
            book, show_panel_labels=show_panel_labels):
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


def seconds_of(pcm):
    """How long a stretch of PCM lasts, for progress reporting."""
    return len(pcm) / float(SAMPLE_RATE * SAMPLE_WIDTH)


def write_mp3(book, path, settings, on_progress=None, cancel_check=None,
              request=None):
    """Speak a whole book into one MP3 file.

    on_progress(message, done, total) is called after each piece.
    cancel_check() returning True stops the run; nothing is written, so
    a cancelled run leaves no half-finished file behind.

    `request` exists so the chunking, retrying and encoding can be
    tested without calling the service.
    """
    keys = [key for key in settings.get("gemini_api_keys", []) if key.strip()]
    if not keys:
        raise SpeechError(
            "speaking a book uses Gemini, so a Gemini API key is needed "
            "in Settings, even when another service is used for reading.")
    model = settings.get("tts_model") or DEFAULT_TTS_MODEL
    voice = settings.get("tts_voice") or DEFAULT_VOICE
    speak = request or (
        lambda text: _request_audio(text, keys[0], model, voice))

    lines = book_text(
        book, show_panel_labels=bool(settings.get("show_panel_labels", True)))
    if not lines:
        raise SpeechError("this book has no processed pages to speak.")
    chunks = split_for_speech(lines)

    audio = bytearray()
    for index, chunk in enumerate(chunks, start=1):
        if cancel_check and cancel_check():
            return None
        if on_progress:
            on_progress("Speaking part %d of %d..." % (index, len(chunks)),
                        index - 1, len(chunks))
        piece = None
        last_error = None
        # The service sometimes answers with text instead of speech.
        # That is documented as occasional rather than exceptional, so
        # it is retried before the whole run is abandoned.
        for attempt in range(3):
            try:
                piece = speak(chunk)
                break
            except SpeechError as error:
                last_error = error
            except urllib.error.HTTPError as error:
                last_error = SpeechError(
                    "the service refused part %d (error %s)."
                    % (index, error.code))
                if error.code in (400, 401, 403):
                    raise last_error  # a key or model problem; retrying
                    # would only repeat it
            except Exception as error:
                last_error = SpeechError(
                    "part %d could not be spoken: %s" % (index, error))
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
        if piece is None:
            raise last_error or SpeechError(
                "part %d could not be spoken." % index)
        audio.extend(piece)

    if cancel_check and cancel_check():
        return None
    if on_progress:
        on_progress("Encoding the audio...", len(chunks), len(chunks))
    with open(path, "wb") as handle:
        handle.write(encode_mp3(bytes(audio)))
    return seconds_of(bytes(audio))
