"""Configuration, versioning, and data directories."""

import json
import os

APP_NAME = "Accessible Manga Reader"
APP_VERSION = "1.0.0"

# Folders used by earlier versions, migrated on first run so existing
# libraries and settings are not lost to a rename.
LEGACY_APP_NAMES = ("PanelReader",)

# Maximum API keys stored per service. This is our own cap, not a limit
# imposed by any service; ten is plenty for rotating between accounts.
MAX_API_KEYS = 10

DEFAULT_SETTINGS = {
    # One of: gemini, openrouter, anthropic, openai, custom.
    "provider": "gemini",
    "gemini_api_keys": [],
    # Default confirmed working on current free-tier projects; older
    # gemini-2.5-* models are no longer served to all projects. Use the
    # "Refresh model list" button in Settings to fetch what YOUR key can use.
    "gemini_model": "gemini-3.6-flash",
    "anthropic_api_keys": [],
    "anthropic_model": "claude-sonnet-5",
    "openai_api_keys": [],
    "openai_model": "gpt-5.6",
    "openrouter_api_keys": [],
    "openrouter_model": "google/gemma-4-31b-it:free",
    # Any OpenAI-compatible endpoint: Groq, Mistral, a local Ollama or
    # LM Studio server, or anything else that speaks the same protocol.
    "custom_api_keys": [],
    "custom_model": "",
    "custom_base_url": "",
    "pages_per_request": 4,
    "max_tokens": 8000,
    # 7 seconds keeps a steady run under Gemini's free-tier
    # requests-per-minute limit with headroom. Lower it on paid tiers.
    "request_delay_seconds": 7.0,
    "output_language": "English",
    "verbosity": "detailed",  # "concise", "detailed", or "extensive"
    "comic_type": "manga",  # manga, manhwa, webtoon, western
    # A user's own extra instructions, one set per comic type, applied to
    # every book read as that type. Kept separate from a book's own
    # per-book instructions.
    # Show the AI-instructions dialog before processing a book. Off
    # starts processing immediately; instructions stay reachable from
    # the Book menu.
    "ask_instructions_before_processing": True,
    "custom_prompts": {
        "manga": "",
        "manhwa": "",
        "webtoon": "",
        "western": "",
    },
    # Reader display mode: "book" (whole book as one document),
    # "page" (one page at a time), "panel" (one panel at a time).
    "reader_view": "book",
    # Show "Panel N (position)" markers in the reader text. Off gives a
    # continuous narrative; the cached scripts are unchanged either way.
    "show_panel_labels": True,
    "converted_pages_one_page": True,
    "tts_engine": "kokoro",
    "say_page_numbers": False,
    "kokoro_language": "en-us",
    "kokoro_voice": "af_heart",
    "kokoro_voice_by_language": {},
    "windows_voice": "",
    "tts_voice": "Kore",
    "tts_model": "gemini-3.1-flash-tts-preview",
    "image_max_dimension": 1568,
    "image_jpeg_quality": 85,
    # Update notifications: checked on a background thread at startup.
    "check_updates_on_start": True,
    "include_beta_updates": True,
    # A version the user asked not to be reminded about again.
    "dismissed_update_version": "",
}

# Fallback suggestions shown before the user fetches the live list with
# the Refresh button in Settings (which queries the service's own
# list-models endpoint and is always the source of truth).
SUGGESTED_MODELS = {
    # 2.5 Flash and 2.5 Flash-Lite are gone from this list: Google has
    # them shutting down in October 2026, and 2.5 Flash was already
    # reported unavailable months before its stated date, so leaving
    # them here would only offer readers a model that stops answering.
    "gemini": [
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
    ],
    "anthropic": [
        "claude-sonnet-5",
        "claude-opus-5",
        "claude-fable-5",
        "claude-haiku-4-5-20251001",
    ],
    "openai": [
        "gpt-5.6",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "gpt-5.5",
        "gpt-5.4-mini",
    ],
    # Free, vision-capable OpenRouter models (IDs ending in :free cost
    # nothing). The roster rotates, so use Refresh model list to see
    # what is actually live for your key.
    "openrouter": [
        "google/gemma-4-31b-it:free",
        "google/gemma-4-26b-a4b-it:free",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "openrouter/free",
    ],
    "custom": [],
}

# Offered in the Settings language box, which stays editable: any
# language the AI service knows can be typed in instead.
# Chosen instead of a language name when the reader wants the comic
# left as it is, rather than translated.
ORIGINAL_LANGUAGE = "Original (same as the comic)"

SUGGESTED_LANGUAGES = [
    # First, because leaving a comic in its own language is a real
    # choice and not an exotic one: a reader who reads Japanese should
    # not have to know to go looking for it.
    ORIGINAL_LANGUAGE,
    "English",
    "Arabic",
    "Chinese (Simplified)",
    "Dutch",
    "French",
    "German",
    "Hindi",
    "Indonesian",
    "Italian",
    "Japanese",
    "Korean",
    "Persian",
    "Polish",
    "Portuguese",
    "Russian",
    "Spanish",
    "Swedish",
    "Turkish",
    "Urdu",
    "Vietnamese",
]

# BCP-47 codes for the languages above. Exports carry this in their
# lang attribute: a screen reader chooses its voice from it, and a
# tagged PDF is not valid without one. The name itself ("Arabic") is not
# a code and must never be used directly.
LANGUAGE_CODES = {
    "English": "en", "Arabic": "ar", "Chinese (Simplified)": "zh-Hans",
    "Chinese (Traditional)": "zh-Hant", "Dutch": "nl", "French": "fr",
    "German": "de", "Hindi": "hi", "Indonesian": "id", "Italian": "it",
    "Japanese": "ja", "Korean": "ko", "Persian": "fa", "Polish": "pl",
    "Portuguese": "pt", "Russian": "ru", "Spanish": "es",
    "Swedish": "sv", "Turkish": "tr", "Urdu": "ur",
    "Vietnamese": "vi", "Hebrew": "he", "Pashto": "ps",
    "Sindhi": "sd", "Uyghur": "ug", "Yiddish": "yi",
    "Divehi": "dv", "Kurdish (Sorani)": "ckb", "Dari": "prs",
}

# Languages and script subtags that read right to left, so exports can
# declare their direction instead of leaving layout to a renderer's
# guess. A script subtag takes precedence: ar-Latn is LTR, while an
# otherwise LTR language explicitly written as en-Arab is RTL.
RTL_LANGUAGE_CODES = {
    "ar", "ckb", "dv", "fa", "he", "nqo", "prs", "ps", "sd", "syr",
    "ug", "ur", "yi",
}
RTL_SCRIPT_CODES = {
    "adlm", "arab", "hebr", "mand", "nkoo", "rohg", "samr", "syrc",
    "thaa",
}


def language_code(name):
    """The BCP-47 code for a language name.

    Anything already code-shaped is passed through, so a language typed
    in by hand still works. Unknown names fall back to English rather
    than producing an invalid document.
    """
    if name == ORIGINAL_LANGUAGE:
        # The comic's own language, which we have no way of knowing.
        # Claiming English would make a screen reader read a Japanese
        # book in an English voice, so the document says nothing and
        # lets the reader's own settings decide.
        return ""
    if not name:
        return "en"
    if name in LANGUAGE_CODES:
        return LANGUAGE_CODES[name]
    trimmed = name.strip()
    parts = trimmed.split("-")
    # A language tag starts with a two or three letter subtag, which is
    # what separates "pt-BR" from a language name like "Klingon".
    if (2 <= len(parts[0]) <= 3 and parts[0].isalpha()
            and all(part.isalnum() for part in parts)):
        return trimmed
    return "en"


def is_rtl(code):
    if not code:
        return False
    parts = code.replace("_", "-").split("-")
    # A four-letter subtag is an ISO 15924 script code.
    scripts = [part.lower() for part in parts[1:]
               if len(part) == 4 and part.isalpha()]
    if scripts:
        return scripts[0] in RTL_SCRIPT_CODES
    return parts[0].lower() in RTL_LANGUAGE_CODES


SERVICE_LABELS = [
    ("gemini", "Gemini by Google (free tier available)"),
    ("openrouter", "OpenRouter (one key, many models, free ones available)"),
    ("anthropic", "Claude by Anthropic"),
    ("openai", "ChatGPT by OpenAI"),
    ("custom", "Other OpenAI-compatible service (Groq, Mistral, local...)"),
]

# Services needing a user-supplied endpoint URL.
SERVICES_NEEDING_BASE_URL = ("custom",)

# Handy presets offered next to the endpoint URL field.
BASE_URL_PRESETS = [
    ("Groq", "https://api.groq.com/openai/v1"),
    ("Mistral", "https://api.mistral.ai/v1"),
    ("Local Ollama", "http://localhost:11434/v1"),
    ("Local LM Studio", "http://localhost:1234/v1"),
]


def _app_dir_for(name):
    appdata = os.environ.get("APPDATA")
    if appdata:
        return os.path.join(appdata, name)
    return os.path.join(os.path.expanduser("~"),
                        "." + name.replace(" ", "-").lower())


def data_dir():
    """Return (and create) the application data directory.

    If a folder from an earlier name exists and the current one does
    not, it is moved across so processed books and settings survive.
    """
    path = _app_dir_for(APP_NAME)
    if not os.path.exists(path):
        for legacy_name in LEGACY_APP_NAMES:
            legacy = _app_dir_for(legacy_name)
            if os.path.isdir(legacy):
                try:
                    os.rename(legacy, path)
                    break
                except OSError:
                    pass  # fall through and start fresh
    os.makedirs(path, exist_ok=True)
    return path


def books_dir():
    path = os.path.join(data_dir(), "books")
    os.makedirs(path, exist_ok=True)
    return path


def settings_path():
    return os.path.join(data_dir(), "settings.json")


def is_local_endpoint(url):
    """True for an endpoint served from this machine.

    Local model servers (Ollama, LM Studio, llama.cpp) do not
    authenticate, so the app does not insist on an API key for them.

    The hostname is parsed rather than prefix-matched, so a remote
    lookalike such as https://localhost.example.com is correctly treated
    as remote and still requires a key.
    """
    from urllib.parse import urlparse

    text = (url or "").strip()
    if not text:
        return False
    try:
        hostname = urlparse(text).hostname
    except ValueError:
        return False
    return hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1")


def parse_api_keys(text):
    """Turn a one-key-per-line text block into a clean list of keys."""
    keys = []
    for line in text.splitlines():
        line = line.strip()
        if line and line not in keys:
            keys.append(line)
    return keys


# Models that have been retired, and what to move a reader to. Leaving
# somebody pointed at a shut-down model means their next book simply
# stops working with a message about a model they never chose, so the
# move happens quietly when settings are loaded.
RETIRED_MODELS = {
    "gemini_model": {
        "gemini-2.5-flash": "gemini-3.5-flash",
        "gemini-2.5-flash-lite": "gemini-3.5-flash-lite",
        "gemini-3-flash-preview": "gemini-3.6-flash",
    },
}


def _migrate(saved):
    """Migrate settings from older versions in place."""
    # Pre-provider single key/model.
    if "api_key" in saved and "anthropic_api_key" not in saved:
        saved["anthropic_api_key"] = saved.pop("api_key")
        if saved.get("anthropic_api_key"):
            saved.setdefault("provider", "anthropic")
    if "model" in saved and "anthropic_model" not in saved:
        saved["anthropic_model"] = saved.pop("model")
    # Single key per service -> list of keys per service.
    for service in ("gemini", "anthropic", "openai"):
        single = "%s_api_key" % service
        plural = "%s_api_keys" % service
        if single in saved and plural not in saved:
            value = saved.pop(single)
            saved[plural] = [value] if isinstance(value, str) and value else []
    # Models that no longer exist.
    for setting, replacements in RETIRED_MODELS.items():
        if saved.get(setting) in replacements:
            saved[setting] = replacements[saved[setting]]
    # reading_direction (rtl/ltr/vertical) -> comic_type.
    if "reading_direction" in saved and "comic_type" not in saved:
        legacy = {"rtl": "manga", "ltr": "western", "vertical": "webtoon"}
        saved["comic_type"] = legacy.get(saved.pop("reading_direction"),
                                         "manga")
    return saved


def load_settings():
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(settings_path(), "r", encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            saved = _migrate(saved)
            for key in DEFAULT_SETTINGS:
                if key in saved:
                    settings[key] = saved[key]
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings):
    path = settings_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
