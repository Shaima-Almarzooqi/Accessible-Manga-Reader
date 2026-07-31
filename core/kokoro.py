"""Local speech synthesis with the official Kokoro v1.0 voices.

The inference runtime is included with the app, while the model and voice
files are downloaded on first use.  They are intentionally kept under the
application data folder instead of inside the executable: together they are
about 196 MB and can be shared by every build of the app.

Downloads are pinned to named release files and verified with SHA-256 before
they are moved into place.  A cancelled or failed download leaves neither a
usable-looking model nor a partial final file behind.
"""

import hashlib
import json
import os
import threading
import urllib.request

from . import config


MODEL_VERSION = "1.0"
MODEL_DIRECTORY = "v1.0"
MODEL_DOWNLOAD_BYTES = 205_679_185

MODEL_ASSETS = (
    {
        "name": "kokoro-v1.0.fp16.onnx",
        "size": 177_464_787,
        "sha256": (
            "c1610a859f3bdea01107e73e50100685af38fff88f5cd8e5c56df109ec880204"
        ),
        "url": (
            "https://github.com/thewh1teagle/kokoro-onnx/releases/"
            "download/model-files-v1.0/kokoro-v1.0.fp16.onnx"
        ),
    },
    {
        "name": "voices-v1.0.bin",
        "size": 28_214_398,
        "sha256": (
            "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"
        ),
        "url": (
            "https://github.com/thewh1teagle/kokoro-onnx/releases/"
            "download/model-files-v1.0/voices-v1.0.bin"
        ),
    },
)

LANGUAGES = (
    ("en-us", "American English"),
    ("en-gb", "British English"),
    ("ja", "Japanese"),
    ("zh", "Mandarin Chinese"),
    ("es", "Spanish"),
    ("fr-fr", "French"),
    ("hi", "Hindi"),
    ("it", "Italian"),
    ("pt-br", "Brazilian Portuguese"),
)
DEFAULT_LANGUAGE = "en-us"

# Voice identifiers and groupings are from hexgrad/Kokoro-82M v1.0.  The
# second value is the voice's gender as documented in the official catalogue;
# it is used only to make otherwise terse identifiers easier to browse.
VOICES_BY_LANGUAGE = {
    "en-us": (
        ("af_heart", "female"), ("af_alloy", "female"),
        ("af_aoede", "female"), ("af_bella", "female"),
        ("af_jessica", "female"), ("af_kore", "female"),
        ("af_nicole", "female"), ("af_nova", "female"),
        ("af_river", "female"), ("af_sarah", "female"),
        ("af_sky", "female"), ("am_adam", "male"),
        ("am_echo", "male"), ("am_eric", "male"),
        ("am_fenrir", "male"), ("am_liam", "male"),
        ("am_michael", "male"), ("am_onyx", "male"),
        ("am_puck", "male"), ("am_santa", "male"),
    ),
    "en-gb": (
        ("bf_alice", "female"), ("bf_emma", "female"),
        ("bf_isabella", "female"), ("bf_lily", "female"),
        ("bm_daniel", "male"), ("bm_fable", "male"),
        ("bm_george", "male"), ("bm_lewis", "male"),
    ),
    "ja": (
        ("jf_alpha", "female"), ("jf_gongitsune", "female"),
        ("jf_nezumi", "female"), ("jf_tebukuro", "female"),
        ("jm_kumo", "male"),
    ),
    "zh": (
        ("zf_xiaobei", "female"), ("zf_xiaoni", "female"),
        ("zf_xiaoxiao", "female"), ("zf_xiaoyi", "female"),
        ("zm_yunjian", "male"), ("zm_yunxi", "male"),
        ("zm_yunxia", "male"), ("zm_yunyang", "male"),
    ),
    "es": (
        ("ef_dora", "female"), ("em_alex", "male"),
        ("em_santa", "male"),
    ),
    "fr-fr": (("ff_siwis", "female"),),
    "hi": (
        ("hf_alpha", "female"), ("hf_beta", "female"),
        ("hm_omega", "male"), ("hm_psi", "male"),
    ),
    "it": (("if_sara", "female"), ("im_nicola", "male")),
    "pt-br": (
        ("pf_dora", "female"), ("pm_alex", "male"),
        ("pm_santa", "male"),
    ),
}

DEFAULT_VOICES = {
    "en-us": "af_heart", "en-gb": "bf_emma", "ja": "jf_alpha",
    "zh": "zf_xiaobei", "es": "ef_dora", "fr-fr": "ff_siwis",
    "hi": "hf_alpha", "it": "if_sara", "pt-br": "pf_dora",
}

SAMPLE_TEXTS = {
    "en-us": "This is how I sound. A street at dusk, with two characters facing each other.",
    "en-gb": "This is how I sound. A street at dusk, with two characters facing each other.",
    "ja": "これは声のサンプルです。夕暮れの通りで、二人の登場人物が向き合っています。",
    "zh": "这是声音示例。黄昏的街道上，两个人物面对面站着。",
    "es": "Esta es una muestra de voz. Una calle al atardecer, con dos personajes frente a frente.",
    "fr-fr": "Voici un exemple de voix. Une rue au crépuscule, avec deux personnages face à face.",
    "hi": "यह आवाज़ का एक नमूना है। शाम की सड़क पर दो पात्र आमने-सामने खड़े हैं।",
    "it": "Questo è un esempio di voce. Una strada al tramonto, con due personaggi uno di fronte all'altro.",
    "pt-br": "Esta é uma amostra de voz. Uma rua ao entardecer, com dois personagens frente a frente.",
}

_BOOK_LANGUAGE_NAMES = {
    "english": "en-us",
    "chinese (simplified)": "zh",
    "chinese (traditional)": "zh",
    "mandarin chinese": "zh",
    "chinese": "zh",
    "japanese": "ja",
    "spanish": "es",
    "french": "fr-fr",
    "hindi": "hi",
    "italian": "it",
    "portuguese": "pt-br",
    "brazilian portuguese": "pt-br",
}

_ESPEAK_LANGUAGES = {
    "en-us": "en-us", "en-gb": "en-gb", "ja": "ja", "zh": "cmn",
    "es": "es", "fr-fr": "fr-fr", "hi": "hi", "it": "it",
    "pt-br": "pt-br",
}


class KokoroError(Exception):
    """A model download or local synthesis could not be completed."""


class DownloadCancelled(KokoroError):
    """The user stopped a model download."""


class SynthesisCancelled(KokoroError):
    """The user stopped local speech synthesis."""


def language_labels():
    return [label for _, label in LANGUAGES]


def language_name(code):
    return dict(LANGUAGES).get(code, code)


def voice_options(language):
    """Return (identifier, accessible label) pairs for one locale."""
    result = []
    for identifier, gender in VOICES_BY_LANGUAGE.get(language, ()):
        name = identifier.split("_", 1)[-1].replace("_", " ").title()
        result.append((identifier, "%s — %s" % (name, gender)))
    return result


def default_voice(language):
    return DEFAULT_VOICES.get(language, DEFAULT_VOICES[DEFAULT_LANGUAGE])


def language_for_book(book, settings):
    """Choose a supported locale from a book's recorded output language."""
    value = (getattr(book, "output_language", "")
             or settings.get("output_language", "") or "").strip()
    lowered = value.lower().replace("_", "-")
    if lowered in _BOOK_LANGUAGE_NAMES:
        return _BOOK_LANGUAGE_NAMES[lowered]
    if lowered.startswith("en-gb"):
        return "en-gb"
    if lowered.startswith("en"):
        return "en-us"
    for prefix, language in (
            ("zh", "zh"), ("ja", "ja"), ("es", "es"),
            ("fr", "fr-fr"), ("hi", "hi"), ("it", "it"),
            ("pt", "pt-br")):
        if lowered == prefix or lowered.startswith(prefix + "-"):
            return language
    remembered = settings.get("kokoro_language", DEFAULT_LANGUAGE)
    return remembered if remembered in dict(LANGUAGES) else DEFAULT_LANGUAGE


def model_dir(directory=None):
    path = directory or os.path.join(
        config.data_dir(), "models", "kokoro", MODEL_DIRECTORY)
    os.makedirs(path, exist_ok=True)
    return path


def model_paths(directory=None):
    directory = model_dir(directory)
    return tuple(os.path.join(directory, asset["name"])
                 for asset in MODEL_ASSETS)


def _manifest_path(directory):
    return os.path.join(directory, "manifest.json")


def _expected_manifest(assets=MODEL_ASSETS):
    return {
        "version": MODEL_VERSION,
        "files": {asset["name"]: asset["sha256"] for asset in assets},
    }


def models_ready(directory=None, assets=MODEL_ASSETS):
    """Whether both verified model files are ready for inference."""
    directory = model_dir(directory)
    try:
        with open(_manifest_path(directory), "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError):
        return False
    if manifest != _expected_manifest(assets):
        return False
    for asset in assets:
        path = os.path.join(directory, asset["name"])
        try:
            if os.path.getsize(path) != asset["size"]:
                return False
        except OSError:
            return False
    return True


def _open_download(opener, url):
    try:
        return opener(url, timeout=60)
    except TypeError:
        return opener(url)


def download_models(on_progress=None, cancel_check=None, directory=None,
                    opener=None, assets=MODEL_ASSETS):
    """Download and verify every model asset.

    `on_progress(message, bytes_done, bytes_total)` is called from the
    downloading thread.  Callers that own a GUI must marshal it back to the
    UI thread.
    """
    directory = model_dir(directory)
    if models_ready(directory, assets):
        return tuple(os.path.join(directory, asset["name"])
                     for asset in assets)
    opener = opener or urllib.request.urlopen
    total = sum(asset["size"] for asset in assets)
    done = 0
    temporary = []
    try:
        for asset in assets:
            if cancel_check and cancel_check():
                raise DownloadCancelled("The download was cancelled.")
            target = os.path.join(directory, asset["name"])
            part = target + ".download"
            temporary.append(part)
            digest = hashlib.sha256()
            written = 0
            try:
                response = _open_download(opener, asset["url"])
                with response, open(part, "wb") as handle:
                    while True:
                        if cancel_check and cancel_check():
                            raise DownloadCancelled(
                                "The download was cancelled.")
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        handle.write(block)
                        digest.update(block)
                        written += len(block)
                        if on_progress:
                            on_progress(
                                "Downloading Kokoro model and voice files.",
                                done + written, total)
            except DownloadCancelled:
                raise
            except Exception as error:
                raise KokoroError(
                    "The Kokoro model and voice files could not be "
                    "downloaded: %s"
                    % error)
            if written != asset["size"]:
                raise KokoroError(
                    "A Kokoro model file was incomplete. Try the download "
                    "again.")
            if digest.hexdigest().lower() != asset["sha256"].lower():
                raise KokoroError(
                    "A Kokoro model file did not pass verification. Try the "
                    "download again.")
            done += written

        # Nothing is made available until every download has passed both
        # checks, so a complete model can never be paired with a partial voice
        # file.
        for asset in assets:
            target = os.path.join(directory, asset["name"])
            os.replace(target + ".download", target)
        manifest = _manifest_path(directory)
        pending_manifest = manifest + ".download"
        with open(pending_manifest, "w", encoding="utf-8") as handle:
            json.dump(_expected_manifest(assets), handle, indent=2,
                      sort_keys=True)
        os.replace(pending_manifest, manifest)
        if on_progress:
            on_progress("Kokoro model and voice files are ready.",
                        total, total)
        return tuple(os.path.join(directory, asset["name"])
                     for asset in assets)
    finally:
        for path in temporary:
            try:
                os.remove(path)
            except OSError:
                pass


_ENGINE = None
_ENGINE_PATHS = None
_ENGINE_LOCK = threading.Lock()
_PHONEME_LOCK = threading.Lock()
_ZH_G2P = None


def load_engine(directory=None):
    """Load and cache the FP16 ONNX model with ARM-friendly threading."""
    global _ENGINE, _ENGINE_PATHS
    paths = model_paths(directory)
    if not models_ready(directory):
        raise KokoroError(
            "Kokoro's model files have not been downloaded yet.")
    with _ENGINE_LOCK:
        if _ENGINE is not None and _ENGINE_PATHS == paths:
            return _ENGINE
        try:
            import onnxruntime as runtime
            from kokoro_onnx import Kokoro

            options = runtime.SessionOptions()
            # The default uses every logical core and was substantially slower
            # on Windows ARM64. Four threads reached approximately real time in
            # the local packaging probe and also behaves well on x64.
            options.intra_op_num_threads = min(4, os.cpu_count() or 1)
            options.inter_op_num_threads = 1
            options.execution_mode = runtime.ExecutionMode.ORT_SEQUENTIAL
            options.graph_optimization_level = (
                runtime.GraphOptimizationLevel.ORT_ENABLE_ALL)
            session = runtime.InferenceSession(
                paths[0], sess_options=options,
                providers=["CPUExecutionProvider"])
            _ENGINE = Kokoro.from_session(session, paths[1])
            _ENGINE_PATHS = paths
            return _ENGINE
        except KokoroError:
            raise
        except Exception as error:
            raise KokoroError(
                "Kokoro could not load its speech model: %s" % error)


def phonemize(text, language, engine=None):
    """Turn text into the phonemes expected by Kokoro v1.0."""
    global _ZH_G2P
    engine = engine or load_engine()
    with _PHONEME_LOCK:
        try:
            if language == "zh":
                # Mandarin's current Kokoro frontend is separate from eSpeak.
                # It is pure Python on the 3.12 builds. Development runtimes
                # where it is unavailable retain a documented eSpeak fallback.
                try:
                    if _ZH_G2P is None:
                        from misaki import zh
                        _ZH_G2P = zh.ZHG2P()
                    value, _ = _ZH_G2P(text)
                    return value
                except ImportError:
                    pass
            return engine.tokenizer.phonemize(
                text, _ESPEAK_LANGUAGES.get(language, language))
        except Exception as error:
            raise KokoroError(
                "Kokoro could not prepare the selected text: %s" % error)


MAX_PHONEME_CHARACTERS = 500


def split_phonemes(phonemes, limit=MAX_PHONEME_CHARACTERS):
    """Split phonemes losslessly below Kokoro's 510-character ceiling.

    kokoro-onnx accepts long input, but its final inference method truncates
    any individual phoneme batch beyond 510 characters.  Keeping a little
    room here and preferring punctuation or whitespace prevents narration
    from disappearing at that boundary.
    """
    remaining = phonemes.strip()
    pieces = []
    while len(remaining) > limit:
        floor = max(1, limit // 2)
        cut = -1
        for character in (
                ".", "!", "?", ";", ":", ",", "。", "！", "？", " "):
            candidate = remaining.rfind(character, floor, limit)
            if candidate >= 0:
                candidate += 1
                cut = max(cut, candidate)
        if cut <= 0:
            cut = limit
        piece = remaining[:cut].strip()
        if piece:
            pieces.append(piece)
        remaining = remaining[cut:].strip()
    if remaining:
        pieces.append(remaining)
    return pieces


def synthesize_phonemes(phonemes, voice, engine=None, cancel_check=None):
    """Generate signed 16-bit mono PCM from already prepared phonemes."""
    engine = engine or load_engine()
    try:
        import numpy as np
        audio = []
        sample_rate = None
        for piece in split_phonemes(phonemes):
            if cancel_check and cancel_check():
                raise SynthesisCancelled("Stopped.")
            samples, piece_rate = engine.create(
                piece, voice=voice, speed=1.0,
                is_phonemes=True, trim=True)
            if sample_rate is None:
                sample_rate = piece_rate
            elif piece_rate != sample_rate:
                raise KokoroError(
                    "Kokoro returned audio at inconsistent sample rates.")
            audio.append(samples)
        if not audio:
            raise KokoroError("Kokoro did not generate any audio.")
        samples = np.concatenate(audio)
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
        return pcm.tobytes(), int(sample_rate), 1
    except SynthesisCancelled:
        raise
    except KokoroError:
        raise
    except Exception as error:
        raise KokoroError(
            "Kokoro could not generate the selected audio: %s" % error)


def speak(text, voice, language, engine=None):
    engine = engine or load_engine()
    return synthesize_phonemes(
        phonemize(text, language, engine), voice, engine)


def sample_text(language):
    return SAMPLE_TEXTS.get(language, SAMPLE_TEXTS[DEFAULT_LANGUAGE])


def runtime_self_test():
    """Exercise native libraries without requiring the downloaded model."""
    import espeakng_loader
    import onnxruntime
    from kokoro_onnx.tokenizer import Tokenizer

    tokenizer = Tokenizer()
    phonemes = tokenizer.phonemize("Packaged speech test.", "en-us")
    if not phonemes:
        raise KokoroError("The packaged speech frontend returned no output.")
    result = {
        "onnxruntime": onnxruntime.__version__,
        "providers": onnxruntime.get_available_providers(),
        "espeak_library": os.path.basename(espeakng_loader.get_library_path()),
        "english_phonemes": len(phonemes),
    }
    try:
        from misaki import zh
        chinese, _ = zh.ZHG2P()("这是语音测试。")
        result["mandarin_phonemes"] = len(chinese)
    except ImportError:
        result["mandarin_phonemes"] = None
    return result
