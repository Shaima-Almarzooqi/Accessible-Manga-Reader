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
  - Switching the AI service swaps the model list and key list in
    place; per-service keys and models are all preserved.
  - API keys live in a list with Add and Remove buttons rather than a
    text box. Ten keys in one box cannot be told apart by ear, and
    deleting one by hand risks damaging the key on the line above.
    Each entry names its position and last four characters, which is
    what the key test and the quota messages report by.
"""

import os

import wx

from core import api_client, config, diagnostics, series

from . import character_bank

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
            ai_panel, label="Refresh model &list from service")
        self.refresh_button.Bind(wx.EVT_BUTTON, self.on_refresh_models)
        ai_sizer.Add(self.refresh_button, 0, wx.LEFT | wx.BOTTOM, 6)

        self.api_keys = add_labeled(
            ai_panel, ai_sizer,
            "API &keys for this service. When a key runs out of quota "
            "the next one is used automatically. Keys from the same "
            "project share one quota, so only keys from separate "
            "projects add capacity:",
            lambda p: wx.ListBox(p, size=(-1, 90), style=wx.LB_SINGLE))

        self.add_key = wx.Button(ai_panel, label="&Add a key")
        self.add_key.Bind(wx.EVT_BUTTON, self.on_add_key)
        ai_sizer.Add(self.add_key, 0, wx.LEFT | wx.BOTTOM, 6)

        self.edit_key = wx.Button(
            ai_panel, label="Ed&it the selected key")
        self.edit_key.Bind(wx.EVT_BUTTON, self.on_edit_key)
        ai_sizer.Add(self.edit_key, 0, wx.LEFT | wx.BOTTOM, 6)

        self.remove_key = wx.Button(
            ai_panel, label="Remo&ve the selected key")
        self.remove_key.Bind(wx.EVT_BUTTON, self.on_remove_key)
        ai_sizer.Add(self.remove_key, 0, wx.LEFT | wx.BOTTOM, 6)

        self.key_counts = wx.Button(
            ai_panel, label="How man&y keys are saved")
        self.key_counts.Bind(wx.EVT_BUTTON, self.on_key_counts)
        ai_sizer.Add(self.key_counts, 0, wx.LEFT | wx.BOTTOM, 6)

        self.test_button = wx.Button(
            ai_panel, label="&Test these keys")
        self.test_button.Bind(wx.EVT_BUTTON, self.on_test_keys)
        ai_sizer.Add(self.test_button, 0, wx.LEFT | wx.BOTTOM, 6)

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

        self.ask_instructions = wx.CheckBox(
            general_panel,
            label="As&k for AI instructions before processing a book")
        self.ask_instructions.SetValue(bool(
            self.settings.get("ask_instructions_before_processing", True)))
        general_sizer.Add(self.ask_instructions, 0, wx.ALL, 6)

        self.ask_character_bank = wx.CheckBox(
            general_panel,
            label="&Ask to add characters to the series bank after "
                  "processing")
        self.ask_character_bank.SetValue(bool(
            self.settings.get("ask_character_bank_after_processing", True)))
        general_sizer.Add(self.ask_character_bank, 0, wx.ALL, 6)

        self.panel_labels = wx.CheckBox(
            general_panel,
            label="Show panel &numbers and positions in the reader text")
        self.panel_labels.SetValue(
            bool(self.settings.get("show_panel_labels", True)))
        general_sizer.Add(self.panel_labels, 0, wx.ALL, 6)

        self.one_page_converted = wx.CheckBox(
            general_panel,
            label="Show one &page at a time in the processing window")
        self.one_page_converted.SetValue(
            bool(self.settings.get("converted_pages_one_page", True)))
        general_sizer.Add(self.one_page_converted, 0, wx.ALL, 6)

        self.detailed_log = wx.CheckBox(
            general_panel, label="Save a detailed &log")
        self.detailed_log.SetValue(
            bool(self.settings.get("detailed_log", False)))
        general_sizer.Add(self.detailed_log, 0, wx.ALL, 6)

        self.open_logs = wx.Button(general_panel, label="Open the log &folder")
        self.open_logs.Bind(wx.EVT_BUTTON, self.on_open_logs)
        general_sizer.Add(self.open_logs, 0, wx.LEFT | wx.BOTTOM, 6)

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

        # ----- Character bank tab ------------------------------------------
        bank_panel = wx.Panel(self.notebook)
        bank_sizer = wx.BoxSizer(wx.VERTICAL)

        bank_sizer.Add(wx.StaticText(
            bank_panel,
            label="&Series with a character bank. Every book in a series "
                  "uses its bank:"), 0, wx.ALL, 6)
        self.series_list = wx.ListBox(bank_panel, size=(-1, 150),
                                      style=wx.LB_SINGLE)
        bank_sizer.Add(self.series_list, 1,
                       wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

        for label, handler in (
                ("&Characters in the selected series...",
                 self.on_bank_characters),
                ("&Add a series...", self.on_bank_add),
                ("Rena&me the selected series...", self.on_bank_rename),
                ("&Remove the selected series", self.on_bank_remove)):
            button = wx.Button(bank_panel, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            bank_sizer.Add(button, 0, wx.LEFT | wx.TOP, 6)

        bank_panel.SetSizer(bank_sizer)
        self.notebook.AddPage(bank_panel, "Character bank")
        self._show_series()

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
        """Save the visible model and URL into the service they belong to.

        The keys are not read back from the list: Add and Remove change
        service_state directly, so it is already current.
        """
        state = self.service_state[self.current_service]
        model = config.model_from_label(self.model.GetValue())
        if model:
            state["model"] = model
        if self._needs_base_url():
            state["base_url"] = self.base_url.GetValue().strip()

    def _load_service_fields(self):
        state = self.service_state[self.current_service]
        service = self.current_service
        self.model.Set([config.model_label(service, name)
                        for name in state["models"]])
        self.model.SetValue(config.model_label(service,
                                               state["model"]))
        self._show_keys(0 if state["api_keys"] else None)
        self.base_url.SetValue(state.get("base_url", ""))
        # The URL and its presets only apply to a custom endpoint; the
        # other services have fixed addresses.
        needs_url = self._needs_base_url()
        self.base_url.Enable(needs_url)
        self.preset.Enable(needs_url)
        self.preset.SetSelection(0)

    # ----- character bank ---------------------------------------------

    def _series_names(self):
        return [item["name"] for item in series.list_series()]

    def _show_series(self, select=None):
        """Redraw the series list with what each bank holds."""
        listed = series.list_series()
        self.series_list.Set([
            "%s, %d character%s, %d picture%s"
            % (item["name"], item["characters"],
               "" if item["characters"] == 1 else "s",
               item["pictures"], "" if item["pictures"] == 1 else "s")
            for item in listed])
        if listed and select is not None:
            self.series_list.SetSelection(
                max(0, min(select, len(listed) - 1)))

    def _selected_series(self):
        index = self.series_list.GetSelection()
        names = self._series_names()
        if index == wx.NOT_FOUND or index >= len(names):
            wx.MessageBox("Choose a series from the list first.",
                          "Character bank", wx.OK | wx.ICON_INFORMATION,
                          self)
            self.series_list.SetFocus()
            return None
        return names[index]

    def on_bank_add(self, event):
        dialog = wx.TextEntryDialog(self, "Series name:", "Add a series")
        pressed = dialog.ShowModal()
        name = dialog.GetValue().strip()
        dialog.Destroy()
        if pressed != wx.ID_OK or not name:
            self.series_list.SetFocus()
            return
        if series.slug(name) in [series.slug(n)
                                 for n in self._series_names()]:
            wx.MessageBox("%s is already here." % name, "Character bank",
                          wx.OK | wx.ICON_INFORMATION, self)
            self.series_list.SetFocus()
            return
        series.save_series(series.blank_series(name))
        names = self._series_names()
        self._show_series(names.index(name) if name in names else 0)
        self.series_list.SetFocus()

    def on_bank_rename(self, event):
        name = self._selected_series()
        if name is None:
            return
        dialog = wx.TextEntryDialog(self, "Series name:",
                                    "Rename a series", name)
        pressed = dialog.ShowModal()
        new_name = dialog.GetValue().strip()
        dialog.Destroy()
        if pressed != wx.ID_OK or not new_name or new_name == name:
            self.series_list.SetFocus()
            return
        record = series.load_series(name)
        record["name"] = new_name
        series.save_series(record)
        # Renaming moves the folder, so the pictures of the old name
        # are left behind unless the old record goes with it.
        if series.slug(new_name) != series.slug(name):
            series.delete_series(name)
        names = self._series_names()
        self._show_series(names.index(new_name) if new_name in names else 0)
        self.series_list.SetFocus()

    def on_bank_remove(self, event):
        name = self._selected_series()
        if name is None:
            return
        if wx.MessageBox(
                "Remove the character bank for %s? The pictures saved "
                "with it are deleted." % name, "Remove a series",
                wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            self.series_list.SetFocus()
            return
        index = self.series_list.GetSelection()
        series.delete_series(name)
        self._show_series(index)
        self.series_list.SetFocus()

    def on_bank_characters(self, event):
        name = self._selected_series()
        if name is None:
            return
        index = self.series_list.GetSelection()
        dialog = character_bank.CharactersDialog(self, name)
        dialog.ShowModal()
        dialog.Destroy()
        self._show_series(index)
        self.series_list.SetFocus()

    def on_open_logs(self, event):
        """Open the folder holding the log files."""
        folder = diagnostics.logs_dir()
        try:
            os.startfile(folder)
        except Exception:
            wx.MessageBox("The logs are in %s" % folder, "Log folder",
                          wx.OK | wx.ICON_INFORMATION, self)
        self.open_logs.SetFocus()

    def on_preset_chosen(self, event):
        index = self.preset.GetSelection()
        if index > 0:
            _name, url = config.BASE_URL_PRESETS[index - 1]
            self.base_url.SetValue(url)

    def on_service_changed(self, event):
        self._stash_service_fields()
        self.current_service = self._selected_service_key()
        self._load_service_fields()

    def _counts_text(self):
        """How many keys each service has saved, longest form."""
        parts = []
        for key, label in config.SERVICE_LABELS:
            count = len(self.service_state[key]["api_keys"])
            if count:
                parts.append("%s %d" % (label.split()[0], count))
        return ", ".join(parts) if parts else "none"

    def _show_keys(self, select=None):
        """Redraw the key list, then put the selection on one entry.

        Selecting an entry is what tells a screen-reader user what just
        happened: after adding, the new key is read out; after removing,
        whichever key took its place is.
        """
        keys = self.service_state[self.current_service]["api_keys"]
        self.api_keys.Set([config.describe_api_key(position, key)
                           for position, key in enumerate(keys, 1)])
        if keys and select is not None:
            self.api_keys.SetSelection(max(0, min(select, len(keys) - 1)))

    def on_add_key(self, event):
        """Add one key to the end of the list."""
        state = self.service_state[self.current_service]
        dialog = wx.TextEntryDialog(self, "Paste one key:", "Add a key")
        pressed = dialog.ShowModal()
        typed = dialog.GetValue()
        dialog.Destroy()
        if pressed != wx.ID_OK:
            self.add_key.SetFocus()
            return
        # One field, so one key: a second line pasted into a single-line
        # field is not reliably delivered, and silently joining two keys
        # into one would be worse than taking them one at a time.
        key = typed.strip()
        if not key:
            self.add_key.SetFocus()
            return
        if self._already_listed(key, state, None, "Add a key"):
            return
        state["api_keys"].append(key)
        self._show_keys(len(state["api_keys"]) - 1)
        self.api_keys.SetFocus()

    def _selected_key(self, title):
        """The position of the selected key, or None with a message said.

        Add works with nothing selected; Edit and Remove cannot.
        """
        keys = self.service_state[self.current_service]["api_keys"]
        index = self.api_keys.GetSelection()
        if index == wx.NOT_FOUND or index >= len(keys):
            wx.MessageBox("Choose a key from the list first.",
                          title, wx.OK | wx.ICON_INFORMATION, self)
            self.api_keys.SetFocus()
            return None
        return index

    def _already_listed(self, key, state, index, title):
        """True, with a message said, when another entry holds this key."""
        if key in state["api_keys"] and state["api_keys"].index(key) != index:
            wx.MessageBox(
                "That key is already %s in the list."
                % config.describe_api_key(
                    state["api_keys"].index(key) + 1, key),
                title, wx.OK | wx.ICON_INFORMATION, self)
            self.api_keys.SetFocus()
            return True
        return False

    def on_edit_key(self, event):
        """Replace the selected key, starting from what it is now."""
        state = self.service_state[self.current_service]
        index = self._selected_key("Edit a key")
        if index is None:
            return
        dialog = wx.TextEntryDialog(self, "Edit the key:", "Edit a key",
                                    state["api_keys"][index])
        pressed = dialog.ShowModal()
        typed = dialog.GetValue()
        dialog.Destroy()
        if pressed != wx.ID_OK:
            self.api_keys.SetFocus()
            return
        key = typed.strip()
        if not key:
            # Emptying the box would otherwise store a blank key, which
            # the app would then take its turn trying to use.
            wx.MessageBox(
                "A key cannot be empty. Use Remove to take it out of "
                "the list.",
                "Edit a key", wx.OK | wx.ICON_INFORMATION, self)
            self.api_keys.SetFocus()
            return
        if self._already_listed(key, state, index, "Edit a key"):
            return
        state["api_keys"][index] = key
        self._show_keys(index)
        self.api_keys.SetFocus()

    def on_remove_key(self, event):
        """Remove the selected key, after reading back which one it is."""
        state = self.service_state[self.current_service]
        index = self._selected_key("Remove a key")
        if index is None:
            return
        described = config.describe_api_key(
            index + 1, state["api_keys"][index])
        if wx.MessageBox("Remove %s?" % described, "Remove a key",
                         wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            self.api_keys.SetFocus()
            return
        del state["api_keys"][index]
        self._show_keys(index)
        self.api_keys.SetFocus()

    def on_key_counts(self, event):
        """Say how many keys each service has."""
        wx.MessageBox("Keys saved: %s" % self._counts_text(),
                      "Keys saved", wx.OK | wx.ICON_INFORMATION, self)
        self.key_counts.SetFocus()

    def on_test_keys(self, event):
        """Try every key for this service against its model list."""
        self._stash_service_fields()
        service = self.current_service
        state = self.service_state[service]
        busy = wx.BusyCursor()
        results = api_client.check_keys(
            service, state["api_keys"],
            base_url=state.get("base_url", ""))
        del busy
        wx.MessageBox(api_client.describe_key_check(results),
                      "Test these keys", wx.OK | wx.ICON_INFORMATION, self)
        self.test_button.SetFocus()

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
        if (self._needs_base_url()
                and self.service_state[self.current_service]["api_keys"]
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
        self.settings["detailed_log"] = self.detailed_log.GetValue()
        self.settings["ask_character_bank_after_processing"] = (
            self.ask_character_bank.GetValue())
        self.settings["ask_instructions_before_processing"] = (
            self.ask_instructions.GetValue())
        self.settings["converted_pages_one_page"] = (
            self.one_page_converted.GetValue())
        self.settings["check_updates_on_start"] = self.check_updates.GetValue()
        self.settings["include_beta_updates"] = self.include_betas.GetValue()
        event.Skip()  # lets the dialog close with wx.ID_OK
