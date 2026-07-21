"""Configuration, versioning, and data directories."""

import json
import os

APP_NAME = "Accessible Manga Reader"
APP_VERSION = "0.15.0"

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
    "gemini_model": "gemini-3.5-flash",
    "anthropic_api_keys": [],
    "anthropic_model": "claude-sonnet-4-6",
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
    "gemini": [
        "gemini-3.5-flash",
        "gemini-3-flash-preview",
        "gemini-3.1-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    ],
    "anthropic": [
        "claude-sonnet-4-6",
        "claude-fable-5",
        "claude-opus-4-8",
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
SUGGESTED_LANGUAGES = [
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
