"""Choosing what to read aloud, and in which voice.

Asked when saving as audio rather than living in Settings, because both
are decisions about this particular book. Reading a whole volume is
several hours of speech and a large part of a service's allowance, so
the dialog shows roughly how much audio the current choice comes to and
lets a range be picked instead.

A Gemini voice sample costs a little of the same allowance, so each one
is fetched once and kept. Samples from this computer are generated
locally and cost nothing.
"""

import os
import threading

import wx
import wx.adv

from core import config, export, tts, winspeech

from . import keys as keyhelp


def samples_dir():
    path = os.path.join(config.data_dir(), "voice-samples")
    os.makedirs(path, exist_ok=True)
    return path


# Ordinary reading aloud is around this pace, which is close enough to
# turn a word count into a useful estimate.
WORDS_PER_MINUTE = 150


class AudioOptionsDialog(wx.Dialog):
    def __init__(self, parent, book, settings):
        super().__init__(parent, title="Save as audio")
        self.book = book
        self.settings = settings
        self._fetching = None

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # ----- what to read -------------------------------------------
        self.scope = wx.RadioBox(
            panel, label="Pages to read",
            choices=["The &whole book", "A page &range"],
            majorDimension=1, style=wx.RA_SPECIFY_COLS)
        self.scope.Bind(wx.EVT_RADIOBOX, self.on_changed)
        sizer.Add(self.scope, 0, wx.EXPAND | wx.ALL, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(panel, label="&From page:"), 0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        last = max(1, book.page_count)
        self.from_ctrl = wx.SpinCtrl(panel, min=1, max=last, initial=1)
        row.Add(self.from_ctrl, 0, wx.RIGHT, 16)
        row.Add(wx.StaticText(panel, label="T&o page:"), 0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.to_ctrl = wx.SpinCtrl(panel, min=1, max=last, initial=last)
        row.Add(self.to_ctrl, 0)
        for control in (self.from_ctrl, self.to_ctrl):
            # Typing a page number means the range option, so select it
            # rather than making someone go back to the choices. The
            # fields stay enabled: a disabled control is skipped by Tab
            # and its value is not announced.
            control.Bind(wx.EVT_TEXT, self.on_range_typed)
            control.Bind(wx.EVT_SPINCTRL, self.on_range_typed)
        sizer.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.estimate = wx.StaticText(panel, label="")
        sizer.Add(self.estimate, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # ----- the voice ------------------------------------------------
        # The computer's own voices are only offered when there are
        # some worth offering; a list of one flat voice is worse than
        # no choice at all.
        self.local_voices = winspeech.voices()
        engines = ["&Gemini, better but uses your allowance"]
        self._engine_ids = [tts.ENGINE_GEMINI]
        if self.local_voices:
            engines.append("&This computer, free and much faster")
            self._engine_ids.append(tts.ENGINE_WINDOWS)
        self.engine = wx.RadioBox(
            panel, label="Read with", choices=engines,
            majorDimension=1, style=wx.RA_SPECIFY_COLS)
        chosen_engine = settings.get("tts_engine", tts.DEFAULT_ENGINE)
        if chosen_engine in self._engine_ids:
            self.engine.SetSelection(self._engine_ids.index(chosen_engine))
        self.engine.Bind(wx.EVT_RADIOBOX, self.on_engine_changed)
        sizer.Add(self.engine, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                  10)

        sizer.Add(wx.StaticText(panel, label="&Voice:"), 0, wx.LEFT, 10)
        # A list rather than a drop-down: arrows move through it and a
        # screen reader announces each voice as it is reached.
        self.voices = wx.ListBox(panel, size=(320, 160))
        sizer.Add(self.voices, 1, wx.EXPAND | wx.ALL, 10)

        sizer.Add(wx.StaticText(panel, label="Voice &model:"), 0,
                  wx.LEFT | wx.TOP, 10)
        self.model = wx.Choice(
            panel,
            choices=["%s - %s" % (name, note) for name, note in tts.TTS_MODELS])
        model_names = [name for name, _ in tts.TTS_MODELS]
        chosen = settings.get("tts_model", tts.DEFAULT_TTS_MODEL)
        self.model.SetSelection(
            model_names.index(chosen) if chosen in model_names else 0)
        sizer.Add(self.model, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.status = wx.StaticText(panel, label="")
        sizer.Add(self.status, 0, wx.LEFT | wx.RIGHT, 10)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.play_button = wx.Button(panel, wx.ID_ANY, "&Play sample")
        self.play_button.Bind(wx.EVT_BUTTON, self.on_play)
        buttons.Add(self.play_button, 0, wx.RIGHT, 8)
        ok = wx.Button(panel, wx.ID_OK, "&Save as audio")
        ok.SetDefault()
        buttons.Add(ok, 0, wx.RIGHT, 8)
        buttons.Add(wx.Button(panel, wx.ID_CANCEL, "Cancel"), 0)
        sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 10)

        # This must come after the model and sample button exist because
        # changing engines also enables and disables those controls.
        self._fill_voices()

        panel.SetSizer(sizer)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizerAndFit(outer)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self._update_estimate()
        self.scope.SetFocus()

    # ----- what was chosen -------------------------------------------------

    def chosen_engine(self):
        return self._engine_ids[self.engine.GetSelection()]

    def _fill_voices(self):
        """Show the voices belonging to the engine that is selected."""
        local = self.chosen_engine() == tts.ENGINE_WINDOWS
        if local:
            labels = [name for _, name in self.local_voices]
            wanted = self.settings.get("windows_voice", "")
            identifiers = [key for key, _ in self.local_voices]
        else:
            labels = ["%s, %s" % (name, note) for name, note in tts.VOICES]
            wanted = self.settings.get("tts_voice", tts.DEFAULT_VOICE)
            identifiers = [name for name, _ in tts.VOICES]
        self.voices.Set(labels)
        if labels:
            self.voices.SetSelection(
                identifiers.index(wanted) if wanted in identifiers else 0)
        # Only Gemini has a model to pick, and only Gemini charges for a
        # sample.
        self.model.Enable(not local)
        self.play_button.Enable(bool(labels))

    def on_engine_changed(self, event):
        self._fill_voices()
        self._update_estimate()
        event.Skip()

    def chosen_local_voice(self):
        index = self.voices.GetSelection()
        if self.chosen_engine() != tts.ENGINE_WINDOWS or index < 0:
            return ""
        return self.local_voices[index][0]

    def chosen_voice(self):
        if self.chosen_engine() == tts.ENGINE_WINDOWS:
            return self.settings.get("tts_voice", tts.DEFAULT_VOICE)
        index = self.voices.GetSelection()
        return tts.VOICES[index][0] if index >= 0 else tts.DEFAULT_VOICE

    def chosen_model(self):
        index = self.model.GetSelection()
        return (tts.TTS_MODELS[index][0] if index >= 0
                else tts.DEFAULT_TTS_MODEL)

    def chosen_pages(self):
        """The page numbers to read, or None for the whole book."""
        if self.scope.GetSelection() == 0:
            return None
        first, last = self.from_ctrl.GetValue(), self.to_ctrl.GetValue()
        if first > last:
            # Clearly the span they meant, so read it that way round.
            first, last = last, first
        last = min(last, self.book.page_count)
        return list(range(first, last + 1))

    def range_label(self):
        """A short description for the suggested file name."""
        pages = self.chosen_pages()
        if not pages:
            return ""
        if len(pages) == 1:
            return " page %d" % pages[0]
        return " pages %d-%d" % (pages[0], pages[-1])

    # ----- the estimate ----------------------------------------------------

    def _update_estimate(self):
        pages = self.chosen_pages()
        words = sum(
            len(text.split())
            for _, text in export.book_outline(
                self.book,
                show_panel_labels=bool(
                    self.settings.get("show_panel_labels", True)),
                pages=pages))
        if not words:
            self.estimate.SetLabel("Nothing processed in that range yet.")
            return
        minutes = words / float(WORDS_PER_MINUTE)
        if minutes < 60:
            rounded_minutes = max(1, round(minutes))
            length = "about %d minute%s" % (
                rounded_minutes, "" if rounded_minutes == 1 else "s")
        else:
            length = "about %.1f hours" % (minutes / 60)
        if self.chosen_engine() == tts.ENGINE_WINDOWS:
            self.estimate.SetLabel(
                "That is %s of audio. This computer reads it locally, "
                "with no account or allowance." % length)
        else:
            self.estimate.SetLabel(
                "That is %s of audio, and uses your Gemini allowance."
                % length)

    def on_changed(self, event):
        self._update_estimate()
        event.Skip()

    def on_range_typed(self, event):
        if self.scope.GetSelection() != 1:
            self.scope.SetSelection(1)
        self._update_estimate()
        event.Skip()

    # ----- previewing a voice ---------------------------------------------

    def on_play(self, event):
        if self.chosen_engine() == tts.ENGINE_WINDOWS:
            # Nothing to fetch and nothing to pay: speak it there and
            # then.
            self._play_local()
            return
        voice = self.chosen_voice()
        cached = os.path.join(samples_dir(), "%s.wav" % voice)
        if os.path.exists(cached):
            self._play(cached, voice)
            return
        if self._fetching:
            return
        self._fetching = voice
        # The button's own label carries the news: a screen reader
        # announces a focused control's name when it changes, whereas a
        # separate status line goes unread.
        self.play_button.SetLabel("Fetching %s..." % voice)
        self._say("Fetching a sample of %s..." % voice)
        threading.Thread(target=self._fetch, args=(voice, cached),
                         daemon=True).start()

    def _play_local(self):
        voice_id = self.chosen_local_voice()
        index = self.voices.GetSelection()
        voice_name = (self.local_voices[index][1] if index >= 0
                      else "the selected voice")
        self.play_button.Enable(False)
        self.status.SetLabel("Speaking a sample...")

        def work():
            try:
                pcm, rate, channels = winspeech.speak(
                    tts.SAMPLE_TEXT, voice_id)
                path = os.path.join(samples_dir(), "local.wav")
                with open(path, "wb") as handle:
                    handle.write(tts.pcm_to_wav(pcm, rate, channels))
                wx.CallAfter(
                    self._fetched, path, None, voice_name, True)
            except Exception as error:
                wx.CallAfter(
                    self._fetched, None, str(error), voice_name, True)

        threading.Thread(target=work, daemon=True).start()

    def _fetch(self, voice, path):
        """Runs on a worker thread; must never raise."""
        try:
            audio = tts.sample_voice(
                voice, dict(self.settings, tts_voice=voice,
                           tts_model=self.chosen_model()))
            with open(path, "wb") as handle:
                handle.write(audio)
            wx.CallAfter(self._fetched, path, None, voice, False)
        except Exception as error:
            wx.CallAfter(self._fetched, path, str(error), voice, False)

    def _fetched(self, path, error, voice_name, local=False):
        self._fetching = None
        self.play_button.SetLabel("&Play sample")
        self.play_button.Enable(True)
        if error:
            # Said out loud rather than written to a status line, which
            # a screen reader would not read: otherwise a failed sample
            # looks exactly like a button that does nothing.
            self._say("Could not play a sample.")
            if local:
                wx.MessageBox(
                    "This computer could not play that voice: %s" % error,
                    "Play sample", wx.OK | wx.ICON_INFORMATION, self)
                return
            wx.MessageBox(
                "That sample could not be fetched: %s\n\nSamples use the "
                "same Gemini allowance as reading a book, so this often "
                "means the key is being rate limited. Waiting a minute "
                "usually works." % error,
                "Play sample", wx.OK | wx.ICON_INFORMATION, self)
            return
        self._play(path, voice_name)

    def _play(self, path, voice_name):
        sound = wx.adv.Sound(path)
        if sound.IsOk():
            # Kept on the dialog: a Sound that goes out of scope stops.
            self._sound = sound
            sound.Play(wx.adv.SOUND_ASYNC)
            self._say("Playing %s." % voice_name)
        else:
            self._say("That sample could not be played.")
            wx.MessageBox(
                "That sample could not be played on this computer.",
                "Play sample", wx.OK | wx.ICON_INFORMATION, self)

    def _say(self, message):
        self.status.SetLabel(message)

    def _on_char_hook(self, event):
        code = event.GetKeyCode()
        if code == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        # Windows sends Enter to a dialog's default button whatever has
        # focus, so pressing it on Play sample was starting the export
        # instead. Play when that is where you are.
        if (code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
                and wx.Window.FindFocus() is self.play_button):
            self.on_play(event)
            return
        if keyhelp.consume_arrow_navigation(event, wx.Window.FindFocus()):
            return
        event.Skip()
