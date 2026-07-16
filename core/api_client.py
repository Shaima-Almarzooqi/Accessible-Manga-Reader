"""Provider-agnostic API clients.

Two providers are supported:

  - "gemini" (default): Google's Gemini API via plain REST. Has a genuine
    free tier through a Google AI Studio key -- no credit card needed.
  - "anthropic": Anthropic's Claude API via the official SDK. Paid
    (pay-as-you-go credits), typically the highest description quality.

Both share the same neutral content format built by build_content():
a list of {"type": "text", "text": ...} and
{"type": "image", "path": ...} blocks. Each client converts that into
its own wire format, so core/processor.py never cares which provider
is active.

Both clients retry rate-limit and transient server errors with
exponential backoff, polling cancel_check between waits.
"""

import base64
import functools
import json
import re
import time

from . import config


class ApiError(Exception):
    """Raised with a user-presentable message when a request finally fails.

    key_exhausted marks failures that are specific to the API key in
    use (quota used up, key rejected), which means trying a different
    key could succeed. RotatingClient uses this to switch keys.
    """

    def __init__(self, message, key_exhausted=False):
        super().__init__(message)
        self.key_exhausted = key_exhausted


def encode_image(path):
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("ascii")


def build_content(page_numbers, image_paths, user_text):
    """Interleave 'Page N' labels with their images, then the instructions.

    Provider-neutral: images are referenced by path and encoded by the
    client at send time.
    """
    content = []
    for number, path in zip(page_numbers, image_paths):
        content.append({"type": "text", "text": "Page %d:" % number})
        content.append({"type": "image", "path": path})
    content.append({"type": "text", "text": user_text})
    return content


def readable_error(response):
    """Extract the service's human-readable error sentence from a JSON
    error body (both Gemini and OpenAI use {"error": {"message": ...}}),
    falling back to trimmed raw text. Keeps log messages pleasant to
    hear through a screen reader instead of raw JSON.
    """
    try:
        message = (response.json().get("error") or {}).get("message", "")
        if message:
            return message[:400]
    except ValueError:
        pass
    return response.text[:300]


def parse_gemini_429(body_json):
    """Interpret a Gemini 429 body.

    Returns (message, retry_seconds, is_daily):
      message       Google's own explanation of which quota was hit.
      retry_seconds server-suggested wait from RetryInfo, or None.
      is_daily      True when a per-day quota was exceeded (retrying now
                    is pointless; it resets at midnight Pacific time).
    """
    error = (body_json or {}).get("error", {})
    message = error.get("message", "") or "Rate limit exceeded."
    retry_seconds = None
    is_daily = False
    haystacks = [message]
    for detail in error.get("details", []):
        detail_type = detail.get("@type", "")
        if detail_type.endswith("RetryInfo"):
            delay = detail.get("retryDelay", "")
            if isinstance(delay, str) and delay.endswith("s"):
                try:
                    retry_seconds = float(delay[:-1])
                except ValueError:
                    pass
        if detail_type.endswith("QuotaFailure"):
            for violation in detail.get("violations", []):
                haystacks.append(violation.get("quotaId", ""))
                haystacks.append(violation.get("description", ""))
    joined = " ".join(haystacks).lower()
    if "perday" in joined or "per day" in joined or "daily" in joined:
        is_daily = True
    return message, retry_seconds, is_daily


def parse_openai_429(body_json):
    """Interpret an OpenAI 429 body.

    OpenAI's limits are per model (each model has its own RPM, TPM and
    RPD numbers, which is why different models show different values in
    their error messages). Returns a dict:

      message           OpenAI's own explanation, numbers included.
      insufficient      True: the account has no API credit. Retrying can
                        never succeed; the account must be funded at
                        platform.openai.com (ChatGPT Plus does not
                        include API usage).
      is_daily          True: a per-day limit was hit; retrying within
                        minutes is pointless.
      request_too_large True: this single request asks for more tokens
                        than the account's entire per-minute limit for
                        this model, so no amount of waiting helps -- the
                        request itself must shrink (fewer pages per
                        request).
    """
    error = (body_json or {}).get("error", {})
    message = error.get("message", "") or "Rate limit exceeded."
    code = str(error.get("code") or error.get("type") or "")
    lowered = message.lower()

    request_too_large = False
    match = re.search(r"limit[:\s]+([\d,]+).*?requested[:\s]+([\d,]+)",
                      lowered, re.DOTALL)
    if match:
        try:
            limit = int(match.group(1).replace(",", ""))
            requested = int(match.group(2).replace(",", ""))
            request_too_large = requested > limit
        except ValueError:
            pass

    return {
        "message": message,
        "insufficient": "insufficient_quota" in code,
        "is_daily": ("per day" in lowered or "(rpd)" in lowered
                     or "tpd" in lowered),
        "request_too_large": request_too_large,
    }


class _RetryMixin:
    MAX_ATTEMPTS = 5
    INITIAL_BACKOFF = 10.0

    def _wait(self, seconds, cancel_check):
        waited = 0.0
        while waited < seconds:
            if cancel_check and cancel_check():
                raise ApiError("Cancelled.")
            time.sleep(1.0)
            waited += 1.0


class GeminiClient(_RetryMixin):
    """Google Gemini via the REST generateContent endpoint."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    # Relax safety filters to the highest-only threshold: manga routinely
    # depicts fictional action/violence, and this app exists to give a
    # blind reader the same access a sighted reader already has.
    SAFETY_SETTINGS = [
        {"category": category, "threshold": "BLOCK_ONLY_HIGH"}
        for category in (
            "HARM_CATEGORY_HARASSMENT",
            "HARM_CATEGORY_HATE_SPEECH",
            "HARM_CATEGORY_SEXUALLY_EXPLICIT",
            "HARM_CATEGORY_DANGEROUS_CONTENT",
        )
    ]

    def __init__(self, api_key, model, max_tokens=8000):
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens

    def _build_payload(self, system_prompt, content):
        parts = []
        for block in content:
            if block["type"] == "text":
                parts.append({"text": block["text"]})
            elif block["type"] == "image":
                parts.append({"inline_data": {
                    "mime_type": "image/jpeg",
                    "data": encode_image(block["path"]),
                }})
        return {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"maxOutputTokens": self.max_tokens},
            "safetySettings": self.SAFETY_SETTINGS,
        }

    @staticmethod
    def extract_text(data):
        """Pull the response text out of a generateContent JSON body."""
        feedback = data.get("promptFeedback", {})
        if feedback.get("blockReason"):
            raise ApiError(
                "Gemini blocked this batch of pages (reason: %s). Try "
                "processing again; if it persists, these pages may need a "
                "different model." % feedback["blockReason"])
        candidates = data.get("candidates") or []
        if not candidates:
            raise ApiError("Gemini returned no response for this batch.")
        candidate = candidates[0]
        if candidate.get("finishReason") == "SAFETY":
            raise ApiError(
                "Gemini stopped mid-response on this batch for safety "
                "filtering. Try again, or switch model in Settings.")
        parts = candidate.get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts)
        if not text.strip():
            raise ApiError("Gemini returned an empty response.")
        return text

    def request_scripts(self, system_prompt, content, cancel_check=None):
        import requests

        url = "%s/%s:generateContent" % (self.BASE_URL, self.model)
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = self._build_payload(system_prompt, content)
        delay = self.INITIAL_BACKOFF
        last_error = None

        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            if cancel_check and cancel_check():
                raise ApiError("Cancelled.")
            try:
                response = requests.post(
                    url, headers=headers, json=payload, timeout=600)
            except requests.RequestException as error:
                last_error = "network error: %s" % error
                if attempt == self.MAX_ATTEMPTS:
                    break
                self._wait(delay, cancel_check)
                delay *= 2
                continue

            if response.status_code == 200:
                try:
                    return self.extract_text(response.json())
                except ValueError:
                    raise ApiError("Gemini returned an unreadable response.")
            if response.status_code in (401, 403):
                raise ApiError(
                    "Gemini rejected the API key. Check your Gemini API key "
                    "in Settings (get a free key at aistudio.google.com).",
                    key_exhausted=True)
            if response.status_code == 404:
                raise ApiError(
                    "Gemini model '%s' was not found. Check the model name "
                    "in Settings." % self.model)
            if response.status_code == 400:
                raise ApiError(
                    "Gemini rejected the request: %s"
                    % readable_error(response))
            if response.status_code == 429:
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                message, retry_seconds, is_daily = parse_gemini_429(body)
                if is_daily:
                    raise ApiError(
                        "Gemini's daily free-tier quota for this model is "
                        "used up. It resets at midnight Pacific time; your "
                        "progress is saved, so use Process again after the "
                        "reset (or switch to a model with a higher daily "
                        "limit, like a flash-lite model). Google's "
                        "explanation: %s" % message, key_exhausted=True)
                last_error = "rate limit: %s" % message
                if attempt == self.MAX_ATTEMPTS:
                    break
                wait = max(delay, retry_seconds or 0)
                self._wait(min(wait, 120), cancel_check)
                delay *= 2
                continue
            if response.status_code in (500, 502, 503, 504):
                last_error = "HTTP %d" % response.status_code
                if attempt == self.MAX_ATTEMPTS:
                    break
                self._wait(delay, cancel_check)
                delay *= 2
                continue
            raise ApiError("Gemini request failed: HTTP %d. %s"
                           % (response.status_code,
                              readable_error(response)))

        raise ApiError(
            "Request failed after %d attempts. Last error: %s. Your "
            "progress is saved; use Process again later to resume. If this "
            "was a daily rate limit, it resets at midnight Pacific time."
            % (self.MAX_ATTEMPTS, last_error), key_exhausted=True)


class AnthropicClient(_RetryMixin):
    """Anthropic Claude via the REST messages endpoint."""

    URL = "https://api.anthropic.com/v1/messages"
    VERSION_HEADER = "2023-06-01"
    SERVICE_NAME = "Claude"

    def __init__(self, api_key, model, max_tokens=8000):
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens

    def _build_payload(self, system_prompt, content):
        blocks = []
        for block in content:
            if block["type"] == "text":
                blocks.append({"type": "text", "text": block["text"]})
            elif block["type"] == "image":
                blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": encode_image(block["path"]),
                    },
                })
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": blocks}],
        }

    @staticmethod
    def extract_text(data):
        if data.get("stop_reason") == "refusal":
            raise ApiError(
                "Claude declined to process this batch of pages.")
        text = "".join(block.get("text", "")
                       for block in data.get("content", [])
                       if block.get("type") == "text")
        if not text.strip():
            raise ApiError("Claude returned an empty response.")
        return text

    def request_scripts(self, system_prompt, content, cancel_check=None):
        import requests

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.VERSION_HEADER,
            "content-type": "application/json",
        }
        payload = self._build_payload(system_prompt, content)
        delay = self.INITIAL_BACKOFF
        last_error = None

        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            if cancel_check and cancel_check():
                raise ApiError("Cancelled.")
            try:
                response = requests.post(
                    self.URL, headers=headers, json=payload, timeout=600)
            except requests.RequestException as error:
                last_error = "network error: %s" % error
                if attempt == self.MAX_ATTEMPTS:
                    break
                self._wait(delay, cancel_check)
                delay *= 2
                continue

            if response.status_code == 200:
                try:
                    return self.extract_text(response.json())
                except ValueError:
                    raise ApiError("Claude returned an unreadable response.")
            if response.status_code in (401, 403):
                raise ApiError(
                    "Claude rejected the API key. Check the API keys for "
                    "this service in Settings: %s"
                    % readable_error(response), key_exhausted=True)
            if response.status_code == 404:
                raise ApiError(
                    "Claude does not have a model called '%s'. Use the "
                    "Refresh model list button in Settings to see what "
                    "your key can use." % self.model)
            if response.status_code == 400:
                raise ApiError(
                    "Claude rejected the request: %s"
                    % readable_error(response))
            if response.status_code in (429, 500, 502, 503, 529):
                last_error = readable_error(response)
                if attempt == self.MAX_ATTEMPTS:
                    break
                wait = delay
                if response.status_code == 429:
                    try:
                        wait = max(delay,
                                   float(response.headers.get("retry-after")))
                    except (TypeError, ValueError):
                        pass
                self._wait(min(wait, 120), cancel_check)
                delay *= 2
                continue
            raise ApiError("Claude request failed: HTTP %d. %s"
                           % (response.status_code, readable_error(response)))

        raise ApiError(
            "Request failed after %d attempts. Last error: %s. Your "
            "progress is saved; use Process again to resume."
            % (self.MAX_ATTEMPTS, last_error), key_exhausted=True)


class OpenAIClient(_RetryMixin):
    """Any service speaking the OpenAI chat completions protocol.

    base_url points at the API root (ending in /v1). OpenAI itself is
    the default; OpenRouter, Groq, Mistral, and local servers such as
    Ollama or LM Studio all work by changing it.
    """

    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    SERVICE_NAME = "OpenAI"

    def __init__(self, api_key, model, max_tokens=8000, base_url=None):
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")

    @property
    def URL(self):
        return self.base_url + "/chat/completions"

    def _build_payload(self, system_prompt, content):
        parts = []
        for block in content:
            if block["type"] == "text":
                parts.append({"type": "text", "text": block["text"]})
            elif block["type"] == "image":
                parts.append({"type": "image_url", "image_url": {
                    "url": "data:image/jpeg;base64," +
                           encode_image(block["path"]),
                }})
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": parts},
            ],
            "max_completion_tokens": self.max_tokens,
        }

    @staticmethod
    def extract_text(data):
        choices = data.get("choices") or []
        if not choices:
            raise ApiError("The service returned no response for this batch.")
        choice = choices[0]
        if choice.get("finish_reason") == "content_filter":
            raise ApiError(
                "The service's content filter stopped this batch of "
                "pages. Try again, or switch model or service in "
                "Settings.")
        text = (choice.get("message") or {}).get("content") or ""
        if not text.strip():
            raise ApiError("The service returned an empty response.")
        return text

    def request_scripts(self, system_prompt, content, cancel_check=None):
        import requests

        headers = {
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
        }
        payload = self._build_payload(system_prompt, content)
        delay = self.INITIAL_BACKOFF
        last_error = None

        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            if cancel_check and cancel_check():
                raise ApiError("Cancelled.")
            try:
                response = requests.post(
                    self.URL, headers=headers, json=payload, timeout=600)
            except requests.RequestException as error:
                last_error = "network error: %s" % error
                if attempt == self.MAX_ATTEMPTS:
                    break
                self._wait(delay, cancel_check)
                delay *= 2
                continue

            if response.status_code == 200:
                try:
                    return self.extract_text(response.json())
                except ValueError:
                    raise ApiError(
                        "%s returned an unreadable response."
                        % self.SERVICE_NAME)
            if response.status_code == 401:
                raise ApiError(
                    "%s rejected the API key. Check the API keys for "
                    "this service in Settings."
                    % self.SERVICE_NAME, key_exhausted=True)
            if response.status_code == 404:
                raise ApiError(
                    "%s does not have a model called '%s'. Use the "
                    "Refresh model list button in Settings to see what "
                    "your key can use." % (self.SERVICE_NAME, self.model))
            if response.status_code == 400:
                raise ApiError(
                    "%s rejected the request: %s"
                    % (self.SERVICE_NAME, readable_error(response)))
            if response.status_code == 429:
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                info = parse_openai_429(body)
                message = info["message"]
                if info["insufficient"]:
                    raise ApiError(
                        "Your OpenAI account has no API credit, so requests "
                        "can never succeed until it is funded. Note that a "
                        "ChatGPT Plus subscription does NOT include API "
                        "usage -- API credit is bought separately at "
                        "platform.openai.com. OpenAI's explanation: %s"
                        % message, key_exhausted=True)
                if info["request_too_large"]:
                    raise ApiError(
                        "A single batch of pages needs more tokens than "
                        "your OpenAI account's per-minute limit allows for "
                        "model %s, so retrying cannot help. Lower Pages "
                        "per request in Settings (try 1 or 2 -- each page "
                        "image costs thousands of tokens), or use a model "
                        "with higher limits. OpenAI's explanation: %s"
                        % (self.model, message))
                if info["is_daily"]:
                    raise ApiError(
                        "OpenAI's daily limit for model %s on your account "
                        "is used up; it resets over the next 24 hours. "
                        "Your progress is saved -- use Process again "
                        "later, or switch model or service in Settings. "
                        "OpenAI's explanation: %s" % (self.model, message),
                        key_exhausted=True)
                last_error = "rate limit: %s" % message
                if attempt == self.MAX_ATTEMPTS:
                    break
                retry_after = response.headers.get("Retry-After", "")
                try:
                    wait = max(delay, float(retry_after))
                except ValueError:
                    wait = delay
                self._wait(min(wait, 120), cancel_check)
                delay *= 2
                continue
            if response.status_code in (500, 502, 503, 504):
                last_error = "HTTP %d" % response.status_code
                if attempt == self.MAX_ATTEMPTS:
                    break
                self._wait(delay, cancel_check)
                delay *= 2
                continue
            raise ApiError("%s request failed: HTTP %d. %s"
                           % (self.SERVICE_NAME, response.status_code,
                              readable_error(response)))

        raise ApiError(
            "Request failed after %d attempts. Last error: %s. Your "
            "progress is saved; use Process again to resume."
            % (self.MAX_ATTEMPTS, last_error), key_exhausted=True)


class OpenRouterClient(OpenAIClient):
    """OpenRouter: one key, many models, several of them free.

    Speaks the OpenAI protocol, so only the base URL differs. Model IDs
    ending in :free cost nothing.
    """

    DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
    SERVICE_NAME = "OpenRouter"


class RotatingClient:
    """Wraps a client class and a list of API keys.

    When a request fails in a way that is specific to the current key
    (quota used up, key rejected), the next key is tried automatically
    and the request is repeated. Keys are used in the order given and
    the rotation wraps around, so a run continues as long as any key
    still has capacity.

    Note that Gemini and OpenAI enforce quotas per project or
    organisation rather than per key, so several keys from the same
    account all draw on one pool. Keys from different projects or
    accounts have separate quotas and rotate usefully.
    """

    def __init__(self, client_class, api_keys, model, max_tokens=8000):
        self.client_class = client_class
        self.api_keys = list(api_keys)
        self.model = model
        self.max_tokens = max_tokens
        self.index = 0
        self.on_key_switch = None  # optional callable(new_index, total, reason)
        self._cache = {}

    def _client_for(self, index):
        if index not in self._cache:
            self._cache[index] = self.client_class(
                self.api_keys[index], self.model, max_tokens=self.max_tokens)
        return self._cache[index]

    def request_scripts(self, system_prompt, content, cancel_check=None):
        problems = []
        for attempt in range(len(self.api_keys)):
            client = self._client_for(self.index)
            try:
                return client.request_scripts(
                    system_prompt, content, cancel_check=cancel_check)
            except ApiError as error:
                if not getattr(error, "key_exhausted", False):
                    raise  # not key-specific (cancelled, bad request, ...)
                problems.append("key %d: %s" % (self.index + 1, error))
                if len(self.api_keys) == 1:
                    raise
                self.index = (self.index + 1) % len(self.api_keys)
                if attempt < len(self.api_keys) - 1 and self.on_key_switch:
                    self.on_key_switch(self.index + 1, len(self.api_keys),
                                       str(error))
        raise ApiError(
            "All %d API keys for this service are unavailable. Note that "
            "keys from the same project or account share one quota, so "
            "rotation only helps with keys from different projects or "
            "accounts. Details -- %s"
            % (len(self.api_keys), " | ".join(problems)))


# ---------------------------------------------------------------------------
# Live model lists, used by the Refresh button in Settings. The parsers
# are pure functions so they can be tested without network access.
# ---------------------------------------------------------------------------

def parse_gemini_model_list(data):
    models = []
    for entry in data.get("models", []):
        if "generateContent" not in entry.get("supportedGenerationMethods", []):
            continue
        name = entry.get("name", "")
        if name.startswith("models/"):
            name = name[len("models/"):]
        if name.startswith("gemini"):
            models.append(name)
    return sorted(set(models), reverse=True)


_OPENAI_EXCLUDE = ("embedding", "whisper", "tts", "dall-e", "audio",
                   "realtime", "moderation", "image", "transcribe",
                   "davinci", "babbage", "codex", "search")


def parse_openai_model_list(data):
    models = []
    for entry in data.get("data", []):
        model_id = entry.get("id", "")
        lowered = model_id.lower()
        if any(word in lowered for word in _OPENAI_EXCLUDE):
            continue
        if lowered.startswith(("gpt", "o1", "o3", "o4", "chatgpt")):
            models.append(model_id)
    return sorted(set(models), reverse=True)


def parse_openai_compatible_model_list(data, vision_only=False):
    """Parse an OpenAI-style /models response.

    Used for OpenRouter and any custom OpenAI-compatible endpoint, where
    model IDs look like "google/gemma-4-31b-it:free" rather than "gpt-*",
    so the OpenAI name filter does not apply.

    When vision_only is set, entries are kept only if they declare image
    input. Entries that declare nothing are kept, since silence is not
    proof of absence. Free models are listed first.
    """
    models = []
    for entry in data.get("data", []):
        model_id = entry.get("id", "")
        if not model_id:
            continue
        if vision_only:
            modalities = entry.get("architecture", {}).get("input_modalities")
            if modalities and "image" not in modalities:
                continue
        models.append(model_id)
    models = sorted(set(models))
    free = [m for m in models if m.endswith(":free")]
    rest = [m for m in models if not m.endswith(":free")]
    return free + rest


def parse_anthropic_model_list(data):
    models = [entry.get("id", "") for entry in data.get("data", [])
              if entry.get("id")]
    return sorted(set(models), reverse=True)


def fetch_models(service, api_key, base_url=""):
    """Query the service's own list-models endpoint. Returns model IDs.

    `api_key` is a single key (the first configured for the service);
    model availability is the same across keys of one account, so one is
    enough to list them. `base_url` is required for a custom
    OpenAI-compatible service and ignored otherwise.
    """
    import requests

    if not api_key:
        raise ApiError("Enter the API key for this service first, then "
                       "refresh the model list.")
    try:
        if service == "openrouter":
            response = requests.get(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": "Bearer " + api_key}, timeout=30)
            # OpenRouter carries hundreds of models, most text-only, so
            # keep only those that can actually read a manga page.
            def parser(data):
                return parse_openai_compatible_model_list(
                    data, vision_only=True)
        elif service == "custom":
            if not base_url.strip():
                raise ApiError(
                    "Enter the endpoint URL for this service first, then "
                    "refresh the model list.")
            response = requests.get(
                base_url.strip().rstrip("/") + "/models",
                headers={"Authorization": "Bearer " + api_key}, timeout=30)
            parser = parse_openai_compatible_model_list
        elif service == "gemini":
            response = requests.get(
                "https://generativelanguage.googleapis.com/v1beta/models"
                "?pageSize=200",
                headers={"x-goog-api-key": api_key}, timeout=30)
            parser = parse_gemini_model_list
        elif service == "openai":
            response = requests.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": "Bearer " + api_key}, timeout=30)
            parser = parse_openai_model_list
        elif service == "anthropic":
            response = requests.get(
                "https://api.anthropic.com/v1/models?limit=100",
                headers={"x-api-key": api_key,
                         "anthropic-version": "2023-06-01"}, timeout=30)
            parser = parse_anthropic_model_list
        else:
            raise ApiError("Unknown service: %s" % service)
    except requests.RequestException as error:
        raise ApiError("Could not reach the service: %s" % error)

    if response.status_code in (401, 403):
        raise ApiError("The service rejected the API key.")
    if response.status_code != 200:
        raise ApiError("The service returned HTTP %d: %s"
                       % (response.status_code, readable_error(response)))
    try:
        models = parser(response.json())
    except ValueError:
        raise ApiError("The service returned an unreadable model list.")
    if not models:
        raise ApiError("The service returned no usable models.")
    return models


MISSING_KEY_MESSAGES = {
    "gemini": ("No Gemini API key is set. Get a free key at "
               "aistudio.google.com and enter it in Settings."),
    "openrouter": ("No OpenRouter API key is set. Sign up free at "
                   "openrouter.ai (no credit card needed), create a key, "
                   "and enter it in Settings."),
    "anthropic": ("No Claude API key is set. Enter one in Settings, or "
                  "switch the AI service."),
    "openai": ("No OpenAI API key is set. Enter one in Settings, or "
               "switch the AI service."),
    "custom": ("No API key is set for this service. Enter one in "
               "Settings, or switch the AI service."),
}


def service_clients():
    """Map service name to client class. Built on demand so this module
    never depends on the order the classes appear in the file."""
    return {
        "gemini": GeminiClient,
        "anthropic": AnthropicClient,
        "openai": OpenAIClient,
        "openrouter": OpenRouterClient,
        "custom": OpenAIClient,
    }


def create_client(settings):
    """Build a rotating client for the configured service."""
    clients = service_clients()
    provider = settings.get("provider", "gemini")
    if provider not in clients:
        provider = "gemini"
    keys = settings.get("%s_api_keys" % provider) or []
    if not keys:
        # A local model server needs no credentials; send a placeholder
        # so the OpenAI-style Authorization header is well formed.
        if (provider == "custom"
                and config.is_local_endpoint(settings.get("custom_base_url"))):
            keys = ["local"]
        else:
            raise ApiError(MISSING_KEY_MESSAGES[provider])
    model = settings.get("%s_model" % provider)
    if not model:
        raise ApiError(
            "No model is set for this service. Enter one in Settings, or "
            "use Refresh model list.")
    client_class = clients[provider]
    if provider == "custom":
        base_url = (settings.get("custom_base_url") or "").strip()
        if not base_url:
            raise ApiError(
                "This service needs an endpoint URL. Enter it in Settings "
                "(for example https://api.groq.com/openai/v1).")
        client_class = functools.partial(OpenAIClient, base_url=base_url)
    return RotatingClient(
        client_class, keys, model,
        max_tokens=int(settings.get("max_tokens", 8000)))
