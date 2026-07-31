"""Reading a book aloud with the voices already on the computer.

Windows keeps its speech voices in two places. The older set --
David, Zira, Mark and their like -- sits under Speech\\Voices, and is
what a program sees by default. They are the flat, robotic ones. The
newer OneCore set sits under Speech_OneCore\\Voices, covers far more
languages, and sounds considerably better; it is simply not offered to
programs unless they ask for it by name, which is what this module
does. Asking through SpObjectTokenCategory is the interface Microsoft
points people at, so nothing here alters the registry or depends on a
trick that a Windows update could take away.

The genuinely neural "Natural" voices that Windows 11 installs for
Narrator are deliberately not used. Microsoft has not opened those to
other applications, and the only way to reach them is by extracting
keys out of system files -- something that can break with any update
and has no business in an app people rely on.

Nothing here needs a key, an account or a network connection, and it
runs far faster than speech that has to be fetched over the internet.
"""

import os
import tempfile
import wave

# The category holding the better voices. The older, flatter ones live
# under Speech\Voices, which is what a program is given by default.
ONECORE_VOICES = r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices"
LEGACY_VOICES = r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\Voices"

# Names of the old, robotic voices. Some of them are listed in the
# newer category as well, so they are filtered out by name: offering
# them alongside the good ones only invites a disappointing choice.
LEGACY_NAMES = {
    "david", "zira", "mark", "hazel", "susan", "richard", "george",
    "sean", "linda", "james", "heera", "ravi", "sam", "mike", "mary",
    "sara", "sarah",
}

SSFM_CREATE_FOR_WRITE = 3


class WindowsSpeechError(Exception):
    """Raised when the computer's own voices cannot be used."""


def available():
    """True when this computer can speak without a service."""
    try:
        import comtypes.client  # noqa: F401
    except Exception:
        return False
    return os.name == "nt"


def is_legacy(name):
    """True for the old, flat-sounding voices.

    Matched on the distinctive part of the name, since Windows reports
    them as "Microsoft David Desktop - English (United States)".
    """
    lowered = (name or "").lower()
    return any(legacy in lowered.split() or legacy in lowered.replace("-", " ").split()
               for legacy in LEGACY_NAMES)


def _tokens():
    """Voice tokens from the better category.

    The caller owns COM initialisation. That matters because synthesis
    runs on a worker thread, and Windows requires every thread using
    COM to initialise itself.
    """
    import comtypes.client
    category = comtypes.client.CreateObject("SAPI.SpObjectTokenCategory")
    category.SetId(ONECORE_VOICES, False)
    return list(category.EnumerateTokens())


def _usable_tokens(tokens):
    """Tokens that will not silently fall back to a legacy voice."""
    return [
        token for token in tokens
        if not is_legacy(token.GetDescription())
    ]


def _chosen_token(tokens, voice_id=None):
    """Return the requested usable token, or the first usable one."""
    usable = _usable_tokens(tokens)
    if not usable:
        raise WindowsSpeechError(
            "This computer has no compatible OneCore voices installed.")
    if not voice_id:
        return usable[0]
    for token in usable:
        if token.Id == voice_id:
            return token
    raise WindowsSpeechError(
        "The chosen Windows voice is no longer installed. Choose another "
        "voice and try again.")


def voices():
    """The usable voices on this computer, best first.

    Returns a list of (identifier, description). Empty when the
    computer has none worth offering, which the caller should treat as
    "this engine is not available here" rather than as an error.
    """
    if not available():
        return []
    try:
        import comtypes
        comtypes.CoInitialize()
        try:
            return [
                (token.Id, token.GetDescription())
                for token in _usable_tokens(_tokens())
            ]
        finally:
            comtypes.CoUninitialize()
    except Exception:
        return []


def _speak_to_wav(text, voice_id, path):
    """Write one stretch of speech to a WAV file."""
    import comtypes
    import comtypes.client
    stream = None
    comtypes.CoInitialize()
    try:
        stream = comtypes.client.CreateObject("SAPI.SpFileStream")
        stream.Open(path, SSFM_CREATE_FOR_WRITE)
        speaker = comtypes.client.CreateObject("SAPI.SpVoice")
        # Always assign a token from the filtered OneCore category.
        # Leaving SpVoice at its default would bring David or Zira back
        # whenever a saved voice disappeared.
        speaker.Voice = _chosen_token(_tokens(), voice_id)
        speaker.AudioOutputStream = stream
        speaker.Speak(text)
    finally:
        if stream is not None:
            try:
                stream.Close()
            except Exception:
                pass
        comtypes.CoUninitialize()


def _read_wav(path):
    """The samples in a WAV file, with the details needed to encode it."""
    with wave.open(path, "rb") as handle:
        return (handle.readframes(handle.getnframes()),
                handle.getframerate(),
                handle.getnchannels())


def speak(text, voice_id=None):
    """Speak `text`, returning (pcm, sample_rate, channels).

    Written through a temporary file because that is what the speech
    engine offers; the file never outlives the call.
    """
    if not available():
        raise WindowsSpeechError(
            "This computer's own voices are not available.")
    folder = tempfile.mkdtemp(prefix="amr-speech-")
    path = os.path.join(folder, "part.wav")
    try:
        _speak_to_wav(text, voice_id, path)
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            raise WindowsSpeechError("The voice produced no sound.")
        return _read_wav(path)
    except WindowsSpeechError:
        raise
    except Exception as error:
        raise WindowsSpeechError(
            "This computer's voice could not read that: %s" % error)
    finally:
        try:
            if os.path.exists(path):
                os.remove(path)
            os.rmdir(folder)
        except OSError:
            pass
