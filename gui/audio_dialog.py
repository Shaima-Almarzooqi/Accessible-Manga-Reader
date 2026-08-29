"""Choose the pages, speech engine, language, and voice for an MP3."""

import os
import re
import threading

import wx
import wx.adv

from core import config, export, kokoro, tts

from . import keys as keyhelp


def samples_dir():
    path = os.path.join(config.data_dir(), "voice-samples")
    os.makedirs(path, exist_ok=True)
    return path


def _safe_filename(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value)


# Ordinary narration is close enough to this rate for a pre-export estimate.
WORDS_PER_MINUTE = 150

ENGINE_EXPLANATION = (
    "Kokoro generates audio on this computer after a one-time model and "
    "voice download, and supports the nine language and locale choices "
    "shown here. Gemini uses its API key, detects the input language "
    "automatically, and supports 78 documented languages. Pages to read "
    "chooses the whole processed book or a page range.")


def _is_button_activation_key(code):
    return code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_SPACE)


class AudioOptionsDialog(wx.Dialog):
    def __init__(self, parent, book, settings):
        super().__init__(parent, title="Save as audio")
        self.book = book
        self.settings = settings
        self._fetching = None
        self._sound = None
        self._closed = False
        self._download_thread = None
        self._download_cancel = threading.Event()
        self._download_after = None

        panel = wx.Panel(self)
        self.panel = panel
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
            # Typing a page number selects the range option. The fields stay
            # enabled so they remain in the tab order for screen readers.
            control.Bind(wx.EVT_TEXT, self.on_range_typed)
            control.Bind(wx.EVT_SPINCTRL, self.on_range_typed)
        sizer.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.estimate = wx.StaticText(panel, label="")
        sizer.Add(self.estimate, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # ----- engine and language ------------------------------------
        self._engine_ids = [tts.ENGINE_KOKORO, tts.ENGINE_GEMINI]
        self.engine = wx.RadioBox(
            panel, label="Read with", choices=["&Kokoro", "&Gemini"],
            majorDimension=1, style=wx.RA_SPECIFY_COLS)
        chosen_engine = settings.get("tts_engine", tts.DEFAULT_ENGINE)
        if chosen_engine not in self._engine_ids:
            chosen_engine = tts.DEFAULT_ENGINE
        self.engine.SetSelection(self._engine_ids.index(chosen_engine))
        self.engine.Bind(wx.EVT_RADIOBOX, self.on_engine_changed)
        sizer.Add(self.engine, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                  10)

        explanation_box = wx.StaticBoxSizer(
            wx.VERTICAL, panel, "About the options")
        explanation_parent = explanation_box.GetStaticBox()
        explanation = wx.StaticText(
            explanation_parent,
            label=ENGINE_EXPLANATION)
        explanation.Wrap(500)
        explanation_box.Add(explanation, 0, wx.ALL, 8)
        sizer.Add(explanation_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT
                  | wx.BOTTOM, 10)

        language_row = wx.BoxSizer(wx.HORIZONTAL)
        self.language_label = wx.StaticText(panel, label="&Language:")
        language_row.Add(self.language_label, 0,
                         wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.language = wx.Choice(panel, choices=kokoro.language_labels())
        language_codes = [code for code, _ in kokoro.LANGUAGES]
        initial_language = kokoro.language_for_book(book, settings)
        self.language.SetSelection(
            language_codes.index(initial_language)
            if initial_language in language_codes else 0)
        self.language.Bind(wx.EVT_CHOICE, self.on_language_changed)
        language_row.Add(self.language, 1)
        sizer.Add(language_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                  10)

        # ----- voice and Gemini model ---------------------------------
        sizer.Add(wx.StaticText(panel, label="&Voice:"), 0, wx.LEFT, 10)
        # A list rather than a drop-down: arrows move through it and a
        # screen reader announces each voice as it is reached.
        self.voices = wx.ListBox(panel, size=(340, 145))
        sizer.Add(self.voices, 1, wx.EXPAND | wx.ALL, 10)
        self._voice_ids = []

        self.model_label = wx.StaticText(panel, label="Voice &model:")
        sizer.Add(self.model_label, 0, wx.LEFT | wx.TOP, 10)
        self.model = wx.Choice(
            panel, choices=[name for name, _ in tts.TTS_MODELS])
        model_names = [name for name, _ in tts.TTS_MODELS]
        chosen_model = settings.get("tts_model", tts.DEFAULT_TTS_MODEL)
        self.model.SetSelection(
            model_names.index(chosen_model)
            if chosen_model in model_names else 0)
        sizer.Add(self.model, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                  10)

        self.download_button = wx.Button(
            panel, wx.ID_ANY, "&Download Kokoro model and voice files")
        self.download_button.Bind(wx.EVT_BUTTON, self.on_download)
        sizer.Add(self.download_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM,
                  10)

        self.status = wx.StaticText(panel, label="")
        self.status.Wrap(500)
        sizer.Add(self.status, 0, wx.LEFT | wx.RIGHT, 10)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.play_button = wx.Button(panel, wx.ID_ANY, "&Play sample")
        self.play_button.Bind(wx.EVT_BUTTON, self.on_play)
        self.play_button.Bind(wx.EVT_KEY_DOWN, self._on_play_key)
        buttons.Add(self.play_button, 0, wx.RIGHT, 8)
        self.ok_button = wx.Button(panel, wx.ID_OK, "&Save as audio")
        self.ok_button.Bind(wx.EVT_BUTTON, self.on_accept)
        self.ok_button.SetDefault()
        buttons.Add(self.ok_button, 0, wx.RIGHT, 8)
        self.cancel_button = wx.Button(panel, wx.ID_CANCEL, "Cancel")
        self.cancel_button.Bind(wx.EVT_BUTTON, self.on_cancel_dialog)
        buttons.Add(self.cancel_button, 0)
        sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 10)

        self._fill_voices()

        panel.SetSizer(sizer)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizerAndFit(outer)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.Bind(wx.EVT_CLOSE, self.on_cancel_dialog)
        self._update_estimate()
        self.scope.SetFocus()

    # ----- current choices --------------------------------------------

    def chosen_engine(self):
        return self._engine_ids[self.engine.GetSelection()]

    def chosen_language(self):
        index = self.language.GetSelection()
        return (kokoro.LANGUAGES[index][0] if index >= 0
                else kokoro.DEFAULT_LANGUAGE)

    def _fill_voices(self):
        local = self.chosen_engine() == tts.ENGINE_KOKORO
        if local:
            options = kokoro.voice_options(self.chosen_language())
            remembered = self.settings.get("kokoro_voice_by_language", {})
            wanted = remembered.get(
                self.chosen_language(),
                self.settings.get(
                    "kokoro_voice", kokoro.default_voice(
                        self.chosen_language())))
        else:
            options = [(name, "%s, %s" % (name, note))
                       for name, note in tts.VOICES]
            wanted = self.settings.get("tts_voice", tts.DEFAULT_VOICE)
        self._voice_ids = [identifier for identifier, _ in options]
        self.voices.Set([label for _, label in options])
        if self._voice_ids:
            self.voices.SetSelection(
                self._voice_ids.index(wanted)
                if wanted in self._voice_ids else 0)

        self.language.Enable(local)
        self.language_label.Enable(local)
        self.model.Enable(not local)
        self.model_label.Enable(not local)
        self.model.Show(not local)
        self.model_label.Show(not local)
        self.download_button.Show(local)
        self._refresh_download_button()
        self.play_button.Enable(bool(self._voice_ids))
        if self.panel.GetSizer():
            self.panel.Layout()
            self.Fit()

    def _refresh_download_button(self):
        if self.chosen_engine() != tts.ENGINE_KOKORO:
            return
        if kokoro.models_ready():
            self.download_button.SetLabel(
                "Kokoro model and voice files are ready")
            self.download_button.Enable(False)
        else:
            self.download_button.SetLabel(
                "&Download Kokoro model and voice files")
            self.download_button.Enable(True)

    def on_engine_changed(self, event):
        self._fill_voices()
        self._update_estimate()
        event.Skip()

    def on_language_changed(self, event):
        self._fill_voices()
        self._update_estimate()
        event.Skip()

    def chosen_voice(self):
        index = self.voices.GetSelection()
        if 0 <= index < len(self._voice_ids):
            return self._voice_ids[index]
        if self.chosen_engine() == tts.ENGINE_KOKORO:
            return kokoro.default_voice(self.chosen_language())
        return tts.DEFAULT_VOICE

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
            first, last = last, first
        last = min(last, self.book.page_count)
        return list(range(first, last + 1))

    def range_label(self):
        pages = self.chosen_pages()
        if not pages:
            return ""
        if len(pages) == 1:
            return " page %d" % pages[0]
        return " pages %d-%d" % (pages[0], pages[-1])

    # ----- estimate ----------------------------------------------------

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
            rounded = max(1, round(minutes))
            length = "about %d minute%s" % (
                rounded, "" if rounded == 1 else "s")
        else:
            length = "about %.1f hours" % (minutes / 60)
        if self.chosen_engine() == tts.ENGINE_KOKORO:
            self.estimate.SetLabel(
                "That is %s of audio. Kokoro generates it on this "
                "computer." % length)
        else:
            self.estimate.SetLabel(
                "That is %s of audio. Gemini generates it through the "
                "API." % length)

    def on_changed(self, event):
        self._update_estimate()
        event.Skip()

    def on_range_typed(self, event):
        if self.scope.GetSelection() != 1:
            self.scope.SetSelection(1)
        self._update_estimate()
        event.Skip()

    # ----- model download ---------------------------------------------

    def _ensure_kokoro(self, after):
        if kokoro.models_ready():
            after()
            return
        size_mb = round(kokoro.MODEL_DOWNLOAD_BYTES / (1024 * 1024))
        answer = wx.MessageBox(
            "The Kokoro model and voice files are required before a sample "
            "or MP3 can be generated. This one download installs every "
            "Kokoro voice listed here and is about %d MB. Download it now?"
            % size_mb,
            "Kokoro model and voice files",
            wx.YES_NO | wx.ICON_QUESTION, self)
        if answer == wx.YES:
            self._start_download(after)

    def on_download(self, event):
        if self._download_thread and self._download_thread.is_alive():
            self._download_cancel.set()
            self.download_button.SetLabel("Stopping download...")
            self.download_button.Enable(False)
            return
        self._start_download(None)

    def _start_download(self, after):
        if self._download_thread and self._download_thread.is_alive():
            return
        self._download_after = after
        self._download_cancel = threading.Event()
        self._set_download_busy(True)
        self._say("Downloading Kokoro model and voice files.")

        def progress(message, done, total):
            wx.CallAfter(self._download_progress, message, done, total)

        def work():
            error = None
            cancelled = False
            try:
                kokoro.download_models(
                    on_progress=progress,
                    cancel_check=self._download_cancel.is_set)
            except kokoro.DownloadCancelled:
                cancelled = True
            except Exception as caught:
                error = str(caught)
            wx.CallAfter(self._download_finished, error, cancelled)

        self._download_thread = threading.Thread(target=work, daemon=True)
        self._download_thread.start()

    def _set_download_busy(self, busy):
        for control in (
                self.scope, self.from_ctrl, self.to_ctrl, self.engine,
                self.language, self.voices, self.model, self.play_button,
                self.ok_button):
            control.Enable(not busy)
        if busy:
            self.download_button.SetLabel("&Cancel download")
            self.download_button.Enable(True)
        else:
            self._fill_voices()

    def _download_progress(self, message, done, total):
        if self._closed:
            return
        percent = int(done * 100 / total) if total else 0
        self._say("%s %d percent." % (message, percent))

    def _download_finished(self, error, cancelled):
        self._download_thread = None
        if self._closed:
            return
        self._set_download_busy(False)
        after = self._download_after
        self._download_after = None
        if cancelled:
            self._say(
                "The Kokoro model and voice download was cancelled.")
            return
        if error:
            self._say("The Kokoro model and voice files are not ready.")
            wx.MessageBox(
                error, "Kokoro model and voice files",
                wx.OK | wx.ICON_ERROR, self)
            return
        self._say("Kokoro model and voice files are ready.")
        if after:
            after()

    def on_accept(self, event):
        if self.chosen_engine() == tts.ENGINE_KOKORO:
            self._ensure_kokoro(lambda: self.EndModal(wx.ID_OK))
            return
        self.EndModal(wx.ID_OK)

    # ----- voice samples ----------------------------------------------

    def on_play(self, event):
        if self.chosen_engine() == tts.ENGINE_KOKORO:
            self._ensure_kokoro(self._play_kokoro_sample_and_focus)
        else:
            self._play_gemini_sample()
        # Generating a sample disables its button, which otherwise lets
        # Windows move focus to the dialog's default Save as audio button.
        # Put the reader back on the selected voice so another voice is one
        # arrow key away. CallAfter makes this the last focus change made by
        # the button event itself.
        wx.CallAfter(self._focus_chosen_voice)

    def _play_kokoro_sample_and_focus(self):
        """Start a sample and restore focus after a first-time download."""
        self._play_kokoro_sample()
        wx.CallAfter(self._focus_chosen_voice)

    def _play_kokoro_sample(self):
        voice = self.chosen_voice()
        language = self.chosen_language()
        cached = os.path.join(
            samples_dir(), "kokoro-%s-%s-%s.wav" % (
                kokoro.MODEL_VERSION, _safe_filename(language),
                _safe_filename(voice)))
        if os.path.exists(cached):
            self._play(cached, voice)
            return
        if self._fetching:
            return
        self._fetching = (tts.ENGINE_KOKORO, voice)
        self.play_button.SetLabel("Generating sample...")
        self.play_button.Enable(False)
        self._say("Generating a sample of %s." % voice)
        threading.Thread(
            target=self._fetch_kokoro,
            args=(voice, language, cached), daemon=True).start()

    def _play_gemini_sample(self):
        voice = self.chosen_voice()
        model = self.chosen_model()
        cached = os.path.join(
            samples_dir(), "gemini-%s-%s.wav" % (
                _safe_filename(model), _safe_filename(voice)))
        if os.path.exists(cached):
            self._play(cached, voice)
            return
        if self._fetching:
            return
        self._fetching = (tts.ENGINE_GEMINI, voice)
        self.play_button.SetLabel("Generating sample...")
        self.play_button.Enable(False)
        self._say("Generating a sample of %s." % voice)
        threading.Thread(
            target=self._fetch_gemini,
            args=(voice, model, cached), daemon=True).start()

    def _fetch_kokoro(self, voice, language, path):
        try:
            audio = tts.sample_kokoro_voice(voice, language)
            with open(path, "wb") as handle:
                handle.write(audio)
            wx.CallAfter(self._fetched, path, None, voice,
                         tts.ENGINE_KOKORO)
        except Exception as error:
            wx.CallAfter(self._fetched, path, str(error), voice,
                         tts.ENGINE_KOKORO)

    def _fetch_gemini(self, voice, model, path):
        try:
            audio = tts.sample_voice(
                voice, dict(self.settings, tts_voice=voice,
                            tts_model=model))
            with open(path, "wb") as handle:
                handle.write(audio)
            wx.CallAfter(self._fetched, path, None, voice,
                         tts.ENGINE_GEMINI)
        except Exception as error:
            wx.CallAfter(self._fetched, path, str(error), voice,
                         tts.ENGINE_GEMINI)

    def _fetched(self, path, error, voice_name, engine):
        if self._closed:
            return
        self._fetching = None
        self.play_button.SetLabel("&Play sample")
        self.play_button.Enable(True)
        if error:
            self._say("Could not play a sample.")
            service = "Kokoro" if engine == tts.ENGINE_KOKORO else "Gemini"
            wx.MessageBox(
                "%s could not generate that sample: %s" % (service, error),
                "Play sample", wx.OK | wx.ICON_INFORMATION, self)
            return
        self._play(path, voice_name)

    def _play(self, path, voice_name):
        sound = wx.adv.Sound(path)
        if sound.IsOk():
            self._sound = sound
            sound.Play(wx.adv.SOUND_ASYNC)
            self._say("Playing %s." % voice_name)
        else:
            self._say("That sample could not be played.")
            wx.MessageBox(
                "That sample could not be played on this computer.",
                "Play sample", wx.OK | wx.ICON_INFORMATION, self)

    def _say(self, message):
        if not self._closed:
            self.status.SetLabel(message)

    # ----- closing and keyboard ---------------------------------------

    def _on_play_key(self, event):
        if _is_button_activation_key(event.GetKeyCode()):
            self.on_play(event)
            return
        event.Skip()

    def _play_button_has_focus(self):
        focus = wx.Window.FindFocus()
        while focus is not None:
            if focus is self.play_button:
                return True
            focus = focus.GetParent()
        return False

    def _focus_chosen_voice(self):
        if (not self._closed and self.voices.IsEnabled()
                and self.voices.GetSelection() != wx.NOT_FOUND):
            self.voices.SetFocus()

    def on_cancel_dialog(self, event):
        self._download_cancel.set()
        self._closed = True
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Destroy()

    def Destroy(self):
        self._closed = True
        self._download_cancel.set()
        return super().Destroy()

    def _on_char_hook(self, event):
        code = event.GetKeyCode()
        if code == wx.WXK_ESCAPE:
            self.on_cancel_dialog(event)
            return
        # Windows can send Enter to the dialog's default button regardless of
        # focus. Space and Enter on Play sample must both play or begin the
        # one-time Kokoro download instead of accepting the dialog.
        if (_is_button_activation_key(code)
                and self._play_button_has_focus()):
            self.on_play(event)
            return
        if keyhelp.consume_arrow_navigation(event, wx.Window.FindFocus()):
            return
        event.Skip()
