"""Settings dialog, organized into two categories via a tab control:

  AI engine: service, model (with live Refresh from the service's own
             model-list endpoint), API key, pages per request, delay.
  General:   output language, verbosity, reading direction, reader view.

Accessibility notes that shape this file:
  - Every control is created immediately after its StaticText label,
    with the same parent, so screen readers associate labels correctly.
  - Numeric fields are plain TextCtrls (validated on OK) because spin
    controls are unreliably labeled by screen readers on Windows.
  - OK/Cancel are children of the dialog itself; OK is the default
    button so Enter activates it anywhere in the dialog, and Escape
    cancels via the standard escape ID plus a char hook for safety.
  - Switching the AI service swaps the model list and key field contents
    in place; per-service keys and models are all preserved.
"""

import wx

from core import api_client, config

from . import keys as keyhelp


def add_labeled(parent, sizer, label_text, control_factory):
    """Create label + control in the order screen readers require."""
    row = wx.BoxSizer(wx.HORIZONTAL)
    label = wx.StaticText(parent, label=label_text)
    control = control_factory(parent)
    row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    row.Add(control, 1, wx.EXPAND)
    sizer.Add(row, 0, wx.EXPAND | wx.ALL, 6)
    return control


class SettingsDialog(wx.Dialog):
    def __init__(self, parent, settings):
        super().__init__(parent, title="Settings")
        self.settings = dict(settings)

        # Working copy of each service's key and model, so switching the
        # service in the dialog never loses what was typed.
        self.service_state = {
            key: {
                "api_keys": list(self.settings["%s_api_keys" % key]),
                "model": self.settings["%s_model" % key],
                "models": list(config.SUGGESTED_MODELS[key]),
                "base_url": self.settings.get("%s_base_url" % key, ""),
            }
            for key, _label in config.SERVICE_LABELS
        }
        self.current_service = self.settings["provider"]
        if self.current_service not in self.service_state:
            self.current_service = "gemini"

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        self.notebook = wx.Notebook(self)
        main_sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 8)

        # ----- AI engine tab ---------------------------------------------
        ai_panel = wx.Panel(self.notebook)
        ai_sizer = wx.BoxSizer(wx.VERTICAL)

        self.service = add_labeled(
            ai_panel, ai_sizer, "AI &service:",
            lambda p: wx.Choice(
                p, choices=[label for _k, label in config.SERVICE_LABELS]))
        service_keys = [key for key, _label in config.SERVICE_LABELS]
        self.service.SetSelection(service_keys.index(self.current_service))
        self.service.Bind(wx.EVT_CHOICE, self.on_service_changed)

        self.base_url = add_labeled(
            ai_panel, ai_sizer,
            "&Endpoint URL (only for an OpenAI-compatible service):",
            lambda p: wx.TextCtrl(p))

        self.preset = add_labeled(
            ai_panel, ai_sizer, "Endpoint p&reset:",
            lambda p: wx.Choice(p, choices=["(choose to fill in the URL)"] +
                                [name for name, _url
                                 in config.BASE_URL_PRESETS]))
        self.preset.SetSelection(0)
        self.preset.Bind(wx.EVT_CHOICE, self.on_preset_chosen)

        self.model = add_labeled(
            ai_panel, ai_sizer, "&Model:",
            lambda p: wx.ComboBox(p, style=wx.CB_DROPDOWN))

        self.refresh_button = wx.Button(
            ai_panel, label="&Refresh model list from service")
        self.refresh_button.Bind(wx.EVT_BUTTON, self.on_refresh_models)
        ai_sizer.Add(self.refresh_button, 0, wx.LEFT | wx.BOTTOM, 6)

        self.api_keys = add_labeled(
            ai_panel, ai_sizer,
            "API &keys for this service, one per line (up to %d). When a "
            "key runs out of quota the next one is used automatically. "
            "Keys from the same project or account share one quota, so "
            "only keys from different projects or accounts add capacity:"
            % config.MAX_API_KEYS,
            lambda p: wx.TextCtrl(p, style=wx.TE_MULTILINE,
                                  size=(-1, 90)))

        self.pages_per_request = add_labeled(
            ai_panel, ai_sizer, "&Pages per request:",
            lambda p: wx.TextCtrl(
                p, value=str(int(self.settings["pages_per_request"]))))

        self.request_delay = add_labeled(
            ai_panel, ai_sizer, "&Delay between requests in seconds:",
            lambda p: wx.TextCtrl(
                p, value=str(self.settings["request_delay_seconds"])))

        ai_panel.SetSizer(ai_sizer)
        self.notebook.AddPage(ai_panel, "AI engine")

        # ----- General tab -------------------------------------------------
        general_panel = wx.Panel(self.notebook)
        general_sizer = wx.BoxSizer(wx.VERTICAL)

        self.language = add_labeled(
            general_panel, general_sizer,
            "&Output language (choose one, or type any other):",
            lambda p: wx.ComboBox(
                p, value=self.settings["output_language"],
                choices=config.SUGGESTED_LANGUAGES, style=wx.CB_DROPDOWN))

        self.verbosity = add_labeled(
            general_panel, general_sizer, "&Verbosity:",
            lambda p: wx.Choice(p, choices=[
                "Concise", "Detailed", "Extensive (maximum detail)"]))
        self.verbosity.SetSelection(
            {"concise": 0, "detailed": 1, "extensive": 2}.get(
                self.settings["verbosity"], 1))

        self.comic_types = ["manga", "manhwa", "webtoon", "western"]
        self.comic_type = add_labeled(
            general_panel, general_sizer, "&Comic type:",
            lambda p: wx.Choice(p, choices=[
                "Manga (Japanese, right to left)",
                "Manhwa or Manhua (Korean/Chinese, left to right)",
                "Webtoon (vertical scroll)",
                "Western comic (left to right)"]))
        current_type = self.settings.get("comic_type") or {
            "rtl": "manga", "ltr": "western", "vertical": "webtoon"}.get(
            self.settings.get("reading_direction", "manga"), "manga")
        if current_type not in self.comic_types:
            current_type = "manga"
        self._current_comic_type = current_type
        self.comic_type.SetSelection(self.comic_types.index(current_type))
        self.comic_type.Bind(wx.EVT_CHOICE, self._on_comic_type_change)

        # Per-type custom instructions. The field shows the instructions
        # for the currently selected comic type; each type keeps its own.
        self._custom_prompts = dict(self.settings.get("custom_prompts") or {})
        for key in self.comic_types:
            self._custom_prompts.setdefault(key, "")
        self.custom_prompt = add_labeled(
            general_panel, general_sizer,
            "Custom &instructions for this comic type (optional, applied "
            "to every book of this type):",
            lambda p: wx.TextCtrl(p, style=wx.TE_MULTILINE, size=(-1, 70)))
        self.custom_prompt.SetValue(self._custom_prompts[current_type])

        self.reader_view = add_labeled(
            general_panel, general_sizer, "Reader displays:",
            lambda p: wx.Choice(p, choices=[
                "The entire book as one document",
                "One page at a time",
                "One panel at a time"]))
        self.reader_view.SetSelection({"book": 0, "page": 1, "panel": 2}.get(
            self.settings["reader_view"], 0))

        self.panel_labels = wx.CheckBox(
            general_panel,
            label="Show panel &numbers and positions in the reader text")
        self.panel_labels.SetValue(
            bool(self.settings.get("show_panel_labels", True)))
        general_sizer.Add(self.panel_labels, 0, wx.ALL, 6)

        self.check_updates = wx.CheckBox(
            general_panel,
            label="Check for &updates when the app starts")
        self.check_updates.SetValue(
            bool(self.settings.get("check_updates_on_start", True)))
        general_sizer.Add(self.check_updates, 0, wx.ALL, 6)

        self.include_betas = wx.CheckBox(
            general_panel, label="Include &beta versions")
        self.include_betas.SetValue(
            bool(self.settings.get("include_beta_updates", True)))
        general_sizer.Add(self.include_betas, 0, wx.ALL, 6)

        general_panel.SetSizer(general_sizer)
        self.notebook.AddPage(general_panel, "General")

        # ----- OK / Cancel -------------------------------------------------
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        ok_button = wx.Button(self, wx.ID_OK, "OK")
        cancel_button = wx.Button(self, wx.ID_CANCEL, "Cancel")
        button_sizer.AddStretchSpacer()
        button_sizer.Add(ok_button, 0, wx.RIGHT, 6)
        button_sizer.Add(cancel_button, 0)
        main_sizer.Add(button_sizer, 0, wx.EXPAND | wx.ALL, 8)

        ok_button.SetDefault()
        self.SetAffirmativeId(wx.ID_OK)
        self.SetEscapeId(wx.ID_CANCEL)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)

        self._load_service_fields()
        self.SetSizerAndFit(main_sizer)
        self.SetMinSize((560, -1))
        self.service.SetFocus()

    # ----- service switching ----------------------------------------------

    def _selected_service_key(self):
        return config.SERVICE_LABELS[self.service.GetSelection()][0]

    def _needs_base_url(self):
        return self.current_service in config.SERVICES_NEEDING_BASE_URL

    def _stash_custom_prompt(self):
        """Save the visible custom-prompt text into the type it belongs to."""
        self._custom_prompts[self._current_comic_type] = (
            self.custom_prompt.GetValue().strip())

    def _on_comic_type_change(self, event):
        # Keep what was typed for the old type, then show the new type's.
        self._stash_custom_prompt()
        new_type = self.comic_types[self.comic_type.GetSelection()]
        self._current_comic_type = new_type
        self.custom_prompt.SetValue(self._custom_prompts.get(new_type, ""))

    def _stash_service_fields(self):
        state = self.service_state[self.current_service]
        state["api_keys"] = config.parse_api_keys(self.api_keys.GetValue())
        model = self.model.GetValue().strip()
        if model:
            state["model"] = model
        if self._needs_base_url():
            state["base_url"] = self.base_url.GetValue().strip()

    def _load_service_fields(self):
        state = self.service_state[self.current_service]
        self.model.Set(state["models"])
        self.model.SetValue(state["model"])
        self.api_keys.SetValue("\n".join(state["api_keys"]))
        self.base_url.SetValue(state.get("base_url", ""))
        # The URL and its presets only apply to a custom endpoint; the
        # other services have fixed addresses.
        needs_url = self._needs_base_url()
        self.base_url.Enable(needs_url)
        self.preset.Enable(needs_url)
        self.preset.SetSelection(0)

    def on_preset_chosen(self, event):
        index = self.preset.GetSelection()
        if index > 0:
            _name, url = config.BASE_URL_PRESETS[index - 1]
            self.base_url.SetValue(url)

    def on_service_changed(self, event):
        self._stash_service_fields()
        self.current_service = self._selected_service_key()
        self._load_service_fields()

    def on_refresh_models(self, event):
        self._stash_service_fields()
        service = self.current_service
        state = self.service_state[service]
        service_keys = state["api_keys"]
        key = service_keys[0] if service_keys else ""
        busy = wx.BusyCursor()
        try:
            models = api_client.fetch_models(
                service, key, base_url=state.get("base_url", ""))
        except api_client.ApiError as error:
            del busy
            wx.MessageBox(str(error), "Refresh model list",
                          wx.OK | wx.ICON_ERROR, self)
            return
        del busy
        state = self.service_state[service]
        state["models"] = models
        if state["model"] not in models:
            state["model"] = models[0]
        self._load_service_fields()
        wx.MessageBox(
            "Found %d models for this service. The model box now lists "
            "them." % len(models),
            "Refresh model list", wx.OK | wx.ICON_INFORMATION, self)
        self.model.SetFocus()

    # ----- closing -----------------------------------------------------------

    def on_char_hook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        if keyhelp.consume_arrow_navigation(event, wx.Window.FindFocus()):
            return  # Tab moves between controls; arrows do not
        event.Skip()

    def _validate_number(self, control, name, minimum, maximum, integer):
        text = control.GetValue().strip()
        try:
            value = int(text) if integer else float(text)
            if not (minimum <= value <= maximum):
                raise ValueError
            return value
        except ValueError:
            wx.MessageBox(
                "%s must be a number between %s and %s." %
                (name, minimum, maximum),
                "Settings", wx.OK | wx.ICON_ERROR, self)
            control.SetFocus()
            control.SelectAll()
            return None

    def on_ok(self, event):
        pages = self._validate_number(
            self.pages_per_request, "Pages per request", 1, 20, True)
        if pages is None:
            return
        delay = self._validate_number(
            self.request_delay, "Delay between requests", 0, 120, False)
        if delay is None:
            return

        self._stash_service_fields()
        for service, label in config.SERVICE_LABELS:
            found = len(self.service_state[service]["api_keys"])
            if found > config.MAX_API_KEYS:
                wx.MessageBox(
                    "%s has %d API keys, but at most %d are supported. "
                    "Remove some lines." % (label, found, config.MAX_API_KEYS),
                    "Settings", wx.OK | wx.ICON_ERROR, self)
                self.notebook.SetSelection(0)
                self.api_keys.SetFocus()
                return
        if (self._needs_base_url()
                and not self.service_state[self.current_service]["base_url"]):
            wx.MessageBox(
                "This service needs an endpoint URL. Choose a preset or "
                "type the address, for example "
                "https://api.groq.com/openai/v1",
                "Settings", wx.OK | wx.ICON_ERROR, self)
            self.notebook.SetSelection(0)
            self.base_url.SetFocus()
            return
        self.settings["provider"] = self.current_service
        for key, _label in config.SERVICE_LABELS:
            state = self.service_state[key]
            suggestions = config.SUGGESTED_MODELS[key]
            self.settings["%s_api_keys" % key] = state["api_keys"]
            self.settings["%s_model" % key] = (
                state["model"] or (suggestions[0] if suggestions else ""))
            if key in config.SERVICES_NEEDING_BASE_URL:
                self.settings["%s_base_url" % key] = state["base_url"]
        self.settings["pages_per_request"] = pages
        self.settings["request_delay_seconds"] = delay
        self.settings["output_language"] = (
            self.language.GetValue().strip() or "English")
        self.settings["verbosity"] = (
            ["concise", "detailed", "extensive"]
            [self.verbosity.GetSelection()])
        self._stash_custom_prompt()
        self.settings["comic_type"] = self.comic_types[
            self.comic_type.GetSelection()]
        self.settings["custom_prompts"] = self._custom_prompts
        self.settings.pop("reading_direction", None)
        self.settings["reader_view"] = (
            ["book", "page", "panel"][self.reader_view.GetSelection()])
        self.settings["show_panel_labels"] = self.panel_labels.GetValue()
        self.settings["check_updates_on_start"] = self.check_updates.GetValue()
        self.settings["include_beta_updates"] = self.include_betas.GetValue()
        event.Skip()  # lets the dialog close with wx.ID_OK
