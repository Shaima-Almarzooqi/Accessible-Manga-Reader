"""Check GitHub for a newer release of the app.

The list endpoint is used rather than /releases/latest because the
latter skips pre-releases, and our betas are published as pre-releases.

The check must never disturb the app: check_for_update returns None on
any network problem, timeout, or unexpected response, and the caller
runs it on a background thread so startup is never blocked.
"""

from collections import namedtuple

RELEASES_URL = ("https://api.github.com/repos/"
                "Shaima-Almarzooqi/Accessible-Manga-Reader/releases")
TIMEOUT_SECONDS = 5

Update = namedtuple("Update", ["version", "notes", "url"])


def parse_version(text):
    """'v0.10.1' -> (0, 10, 1). None for anything that is not a plain
    dotted version number (with or without a leading v)."""
    text = (text or "").strip()
    if text[:1] in ("v", "V"):
        text = text[1:]
    if not text:
        return None
    parts = []
    for piece in text.split("."):
        if not piece.isdigit():
            return None
        parts.append(int(piece))
    return tuple(parts)


def newest_release(releases, current_version, include_betas=True):
    """Pick the newest applicable release from parsed /releases JSON.

    Pure function so it can be tested without network access. Returns
    an Update (version string without the leading v, release notes,
    download page URL), or None if nothing newer than current_version
    is found or the data is not in the expected shape.
    """
    current = parse_version(current_version)
    if current is None or not isinstance(releases, list):
        return None
    best = None
    best_version = current
    for release in releases:
        if not isinstance(release, dict):
            continue
        if release.get("draft"):
            continue
        if release.get("prerelease") and not include_betas:
            continue
        version = parse_version(release.get("tag_name", ""))
        if version is None:
            continue
        if version > best_version:
            best_version = version
            best = release
    if best is None:
        return None
    return Update(
        version=".".join(str(part) for part in best_version),
        notes=best.get("body") or "",
        url=best.get("html_url") or "")


def check_for_update(current_version, include_betas=True):
    """Query GitHub and return an Update, or None if up to date.

    Never raises: any error of any kind returns None silently.
    """
    try:
        import requests

        response = requests.get(
            RELEASES_URL, timeout=TIMEOUT_SECONDS,
            headers={"Accept": "application/vnd.github+json"})
        if response.status_code != 200:
            return None
        return newest_release(response.json(), current_version,
                              include_betas=include_betas)
    except Exception:
        return None
