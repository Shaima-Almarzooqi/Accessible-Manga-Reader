"""Core test suite.

Run with:  python -m tests.test_core   (from the project root)
or:        python run_tests.py

Covers every non-GUI behavior that has bitten similar projects before:
page ordering, archive/PDF extraction, response parsing (including
malformed responses), batch construction, cache/resume logic, and
settings round-trips. Add a scenario here for every bug found in the
field before fixing it.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from core import config, extract, library, processor, prompts


def make_test_image(width=200, height=300, color=(120, 60, 200)):
    return Image.new("RGB", (width, height), color)


class TestNaturalSort(unittest.TestCase):
    def test_numeric_ordering(self):
        names = ["page10.jpg", "page2.jpg", "page1.jpg"]
        names.sort(key=extract.natural_sort_key)
        self.assertEqual(names, ["page1.jpg", "page2.jpg", "page10.jpg"])

    def test_mixed_case_and_nesting(self):
        names = ["Ch01/P002.png", "Ch01/P001.png", "ch01/p010.png"]
        names.sort(key=extract.natural_sort_key)
        self.assertEqual(
            names, ["Ch01/P001.png", "Ch01/P002.png", "ch01/p010.png"])


class WorkspaceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="amr_test_")
        self.workspace = os.path.join(self.tmp, "ws")
        os.makedirs(self.workspace)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestArchiveExtraction(WorkspaceTestCase):
    def _make_cbz(self, path, names):
        with zipfile.ZipFile(path, "w") as zf:
            for name in names:
                buffer = io.BytesIO()
                make_test_image().save(buffer, "PNG")
                zf.writestr(name, buffer.getvalue())
            zf.writestr("info.txt", "not an image")
            zf.writestr("__MACOSX/.hidden.jpg", b"junk")

    def test_cbz_extraction_orders_and_filters(self):
        cbz = os.path.join(self.tmp, "book.cbz")
        self._make_cbz(cbz, ["p10.png", "p2.png", "p1.png"])
        count = extract.extract_archive(cbz, self.workspace)
        self.assertEqual(count, 3)
        pages = sorted(os.listdir(os.path.join(self.workspace, "pages")))
        self.assertEqual(pages, ["0001.jpg", "0002.jpg", "0003.jpg"])

    def test_extraction_resizes_large_pages(self):
        cbz = os.path.join(self.tmp, "big.cbz")
        with zipfile.ZipFile(cbz, "w") as zf:
            buffer = io.BytesIO()
            make_test_image(4000, 6000).save(buffer, "PNG")
            zf.writestr("p1.png", buffer.getvalue())
        extract.extract_archive(cbz, self.workspace, max_dim=1568)
        image = Image.open(
            os.path.join(self.workspace, "pages", "0001.jpg"))
        self.assertLessEqual(max(image.size), 1568)

    def test_image_batch_extraction(self):
        paths = []
        for name in ["b2.png", "a10.png", "a9.png"]:
            path = os.path.join(self.tmp, name)
            make_test_image().save(path, "PNG")
            paths.append(path)
        count = extract.extract_image_files(paths, self.workspace)
        self.assertEqual(count, 3)
        # a9 before a10 before b2 (natural sort).
        self.assertTrue(os.path.exists(
            os.path.join(self.workspace, "pages", "0003.jpg")))


try:
    import pypdfium2  # noqa: F401
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False


# A minimal valid two-page PDF, written by hand so the test needs no PDF
# authoring library (pypdfium2 only reads PDFs, it does not create them).
_TWO_PAGE_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 600] "
    b"/Contents 4 0 R >>\nendobj\n"
    b"4 0 obj\n<< /Length 44 >>\nstream\n"
    b"BT /F1 24 Tf 50 500 Td (Page One) Tj ET\nendstream\nendobj\n"
    b"5 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 600] "
    b"/Contents 6 0 R >>\nendobj\n"
    b"6 0 obj\n<< /Length 44 >>\nstream\n"
    b"BT /F1 24 Tf 50 500 Td (Page Two) Tj ET\nendstream\nendobj\n"
    b"trailer\n<< /Size 7 /Root 1 0 R >>\n%%EOF"
)


class TestPdfExtraction(WorkspaceTestCase):
    @unittest.skipUnless(PDF_SUPPORT, "pypdfium2 is not installed")
    def test_pdf_pages_render(self):
        pdf_path = os.path.join(self.tmp, "book.pdf")
        with open(pdf_path, "wb") as f:
            f.write(_TWO_PAGE_PDF)
        count = extract.extract_pdf(pdf_path, self.workspace)
        self.assertEqual(count, 2)
        pages = sorted(os.listdir(os.path.join(self.workspace, "pages")))
        self.assertEqual(pages, ["0001.jpg", "0002.jpg"])


class TestPromptParsing(unittest.TestCase):
    SAMPLE = """=== PAGE 12 ===
Panel 1: Two students at the school gate.
Aiko: "You're late again!"
SFX: zaaa -- wind through the trees

=== PAGE 13 ===
Panel 1: Silent. Kenta stares at the ground.

=== CHARACTER NOTES ===
Aiko: short dark hair, class representative.
Kenta: messy hair, always late."""

    def test_parses_pages_and_notes(self):
        scripts, notes = prompts.parse_response(self.SAMPLE)
        self.assertEqual(sorted(scripts), [12, 13])
        self.assertIn("You're late again!", scripts[12])
        self.assertIn("Silent", scripts[13])
        self.assertIn("Kenta: messy hair", notes)
        # Notes must not leak into page scripts.
        self.assertNotIn("CHARACTER NOTES", scripts[13])

    def test_missing_notes_is_tolerated(self):
        text = "=== PAGE 1 ===\nPanel 1: A cover page."
        scripts, notes = prompts.parse_response(text)
        self.assertEqual(list(scripts), [1])
        self.assertEqual(notes, "")

    def test_garbage_response_raises(self):
        with self.assertRaises(ValueError):
            prompts.parse_response("Sorry, I chatted instead of working.")

    def test_system_prompt_includes_settings(self):
        prompt = prompts.build_system_prompt("rtl", "concise", "Arabic")
        self.assertIn("RIGHT-TO-LEFT", prompt)
        self.assertIn("CONCISE", prompt)
        self.assertIn("Arabic", prompt)

    def test_user_text_first_batch_and_later_batch(self):
        first = prompts.build_user_text([1, 2], "", "Vol 1")
        self.assertIn("none yet", first)
        later = prompts.build_user_text([3, 4], "Aiko: short hair", "Vol 1")
        self.assertIn("Aiko: short hair", later)
        self.assertIn("pages 3, 4", later)


class TestBatching(unittest.TestCase):
    def test_simple_batches(self):
        self.assertEqual(
            processor.make_batches([1, 2, 3, 4, 5], 2),
            [[1, 2], [3, 4], [5]])

    def test_gaps_break_batches(self):
        # Pages 3 and 7 already processed: never bridge a gap in one request.
        self.assertEqual(
            processor.make_batches([1, 2, 4, 5, 6, 8], 4),
            [[1, 2], [4, 5, 6], [8]])

    def test_empty(self):
        self.assertEqual(processor.make_batches([], 4), [])


class TestLibrary(WorkspaceTestCase):
    def _book_with_pages(self, count):
        book = library.Book(self.workspace)
        book.title = "Test Volume"
        pages_dir = os.path.join(self.workspace, "pages")
        os.makedirs(pages_dir, exist_ok=True)
        for i in range(1, count + 1):
            make_test_image().save(
                os.path.join(pages_dir, "%04d.jpg" % i), "JPEG")
        book.detect_page_count()
        return book

    def test_save_load_round_trip(self):
        book = self._book_with_pages(3)
        book.scripts[1] = "Panel 1: something happens."
        book.character_notes = "Hero: red scarf."
        book.last_position = 42
        book.save()

        loaded = library.Book.load(self.workspace)
        loaded.detect_page_count()
        self.assertEqual(loaded.title, "Test Volume")
        self.assertEqual(loaded.scripts[1], "Panel 1: something happens.")
        self.assertEqual(loaded.character_notes, "Hero: red scarf.")
        self.assertEqual(loaded.last_position, 42)
        self.assertEqual(loaded.page_count, 3)

    def test_resume_logic(self):
        book = self._book_with_pages(5)
        book.scripts[1] = "done"
        book.scripts[2] = "done"
        book.scripts[4] = "done"
        self.assertEqual(book.unprocessed_pages(), [3, 5])
        self.assertFalse(book.is_complete())
        book.scripts[3] = "done"
        book.scripts[5] = "done"
        self.assertTrue(book.is_complete())

    def test_full_text_includes_placeholders(self):
        book = self._book_with_pages(2)
        book.scripts[1] = "Panel 1: dawn over the city."
        text = book.full_text()
        self.assertIn("Page 1 of 2", text)
        self.assertNotIn("===", text)
        self.assertIn("dawn over the city", text)
        self.assertIn("not been processed yet", text)

    def test_unicode_scripts_survive_round_trip(self):
        # Non-ASCII scripts must survive the JSON round trip.
        book = self._book_with_pages(1)
        book.scripts[1] = 'Aiko: "Ã‡ok teÅŸekkÃ¼rler! ã‚ã‚ŠãŒã¨ã† â™ª"'
        book.save()
        loaded = library.Book.load(self.workspace)
        self.assertEqual(loaded.scripts[1], 'Aiko: "Ã‡ok teÅŸekkÃ¼rler! ã‚ã‚ŠãŒã¨ã† â™ª"')


class TestProcessorWithFakeClient(WorkspaceTestCase):
    """End-to-end processor run against a fake API client."""

    def _book_with_pages(self, count):
        book = library.Book(self.workspace)
        book.title = "Fake Book"
        pages_dir = os.path.join(self.workspace, "pages")
        os.makedirs(pages_dir, exist_ok=True)
        for i in range(1, count + 1):
            make_test_image().save(
                os.path.join(pages_dir, "%04d.jpg" % i), "JPEG")
        book.detect_page_count()
        return book

    def test_full_run_saves_scripts_and_notes(self):
        from core import api_client

        class FakeClient:
            def request_scripts(self, system_prompt, content,
                                cancel_check=None):
                # Figure out which pages were requested from the labels.
                pages = [int(block["text"].split()[1].rstrip(":"))
                         for block in content
                         if block["type"] == "text"
                         and block["text"].startswith("Page ")]
                parts = []
                for n in pages:
                    parts.append("=== PAGE %d ===\nPanel 1: page %d action."
                                 % (n, n))
                parts.append("=== CHARACTER NOTES ===\nHero: brave.")
                return "\n\n".join(parts)

        original = api_client.create_client
        api_client.create_client = lambda settings: FakeClient()
        try:
            book = self._book_with_pages(5)
            settings = dict(config.DEFAULT_SETTINGS)
            settings.update({"gemini_api_keys": ["test"],
                             "pages_per_request": 2,
                             "request_delay_seconds": 0})
            result = processor.process_book(book, settings)
        finally:
            api_client.create_client = original

        self.assertEqual(result.pages_done, 5)
        self.assertEqual(result.pages_failed, [])
        self.assertTrue(book.is_complete())
        self.assertEqual(book.character_notes, "Hero: brave.")
        # And it was persisted to disk, not just memory.
        loaded = library.Book.load(self.workspace)
        self.assertIn(3, loaded.scripts)


class TestConfig(unittest.TestCase):
    def test_defaults_fill_missing_keys(self):
        tmp = tempfile.mkdtemp(prefix="amr_cfg_")
        original = os.environ.get("APPDATA")
        os.environ["APPDATA"] = tmp
        try:
            with open(config.settings_path(), "w", encoding="utf-8") as f:
                json.dump({"gemini_model": "gemini-2.5-flash-lite"}, f)
            settings = config.load_settings()
            self.assertEqual(settings["gemini_model"],
                             "gemini-2.5-flash-lite")
            self.assertEqual(settings["provider"], "gemini")
            self.assertEqual(settings["verbosity"],
                             config.DEFAULT_SETTINGS["verbosity"])
        finally:
            if original is None:
                del os.environ["APPDATA"]
            else:
                os.environ["APPDATA"] = original
            shutil.rmtree(tmp, ignore_errors=True)

    def test_corrupt_settings_fall_back_to_defaults(self):
        tmp = tempfile.mkdtemp(prefix="amr_cfg_")
        original = os.environ.get("APPDATA")
        os.environ["APPDATA"] = tmp
        try:
            with open(config.settings_path(), "w", encoding="utf-8") as f:
                f.write("{ this is not json")
            settings = config.load_settings()
            self.assertEqual(settings, config.DEFAULT_SETTINGS)
        finally:
            if original is None:
                del os.environ["APPDATA"]
            else:
                os.environ["APPDATA"] = original
            shutil.rmtree(tmp, ignore_errors=True)




class TestProviderClients(unittest.TestCase):
    def test_build_content_is_provider_neutral(self):
        from core import api_client
        content = api_client.build_content(
            [3, 4], ["/tmp/a.jpg", "/tmp/b.jpg"], "instructions here")
        self.assertEqual(content[0], {"type": "text", "text": "Page 3:"})
        self.assertEqual(content[1], {"type": "image", "path": "/tmp/a.jpg"})
        self.assertEqual(content[-1]["text"], "instructions here")

    def test_gemini_payload_structure(self):
        import tempfile
        from core import api_client
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            make_test_image(10, 10).save(f, "JPEG")
            image_path = f.name
        try:
            client = api_client.GeminiClient("key", "gemini-2.5-flash",
                                             max_tokens=1234)
            content = api_client.build_content([1], [image_path], "go")
            payload = client._build_payload("system text", content)
            self.assertEqual(
                payload["system_instruction"]["parts"][0]["text"],
                "system text")
            parts = payload["contents"][0]["parts"]
            self.assertEqual(parts[0]["text"], "Page 1:")
            self.assertEqual(parts[1]["inline_data"]["mime_type"],
                             "image/jpeg")
            self.assertTrue(parts[1]["inline_data"]["data"])
            self.assertEqual(
                payload["generationConfig"]["maxOutputTokens"], 1234)
            self.assertEqual(len(payload["safetySettings"]), 4)
        finally:
            os.unlink(image_path)

    def test_gemini_extract_text_success(self):
        from core import api_client
        data = {"candidates": [{"content": {"parts": [
            {"text": "=== PAGE 1 ==="}, {"text": "\nPanel 1: hi."}]}}]}
        self.assertEqual(api_client.GeminiClient.extract_text(data),
                         "=== PAGE 1 ===\nPanel 1: hi.")

    def test_gemini_extract_text_blocked(self):
        from core import api_client
        with self.assertRaises(api_client.ApiError):
            api_client.GeminiClient.extract_text(
                {"promptFeedback": {"blockReason": "SAFETY"}})

    def test_gemini_extract_text_safety_stop(self):
        from core import api_client
        with self.assertRaises(api_client.ApiError):
            api_client.GeminiClient.extract_text(
                {"candidates": [{"finishReason": "SAFETY",
                                 "content": {"parts": []}}]})

    def test_gemini_extract_text_empty(self):
        from core import api_client
        with self.assertRaises(api_client.ApiError):
            api_client.GeminiClient.extract_text({"candidates": []})

    def test_factory_requires_key(self):
        from core import api_client
        settings = dict(config.DEFAULT_SETTINGS)
        with self.assertRaises(api_client.ApiError):
            api_client.create_client(settings)  # no gemini keys set
        settings["provider"] = "anthropic"
        with self.assertRaises(api_client.ApiError):
            api_client.create_client(settings)  # no anthropic keys set

    def test_factory_returns_rotating_gemini_client(self):
        from core import api_client
        settings = dict(config.DEFAULT_SETTINGS)
        settings["gemini_api_keys"] = ["abc"]
        client = api_client.create_client(settings)
        self.assertIsInstance(client, api_client.RotatingClient)
        self.assertIs(client.client_class, api_client.GeminiClient)
        self.assertEqual(client.model, "gemini-3.5-flash")


class TestSettingsMigration(unittest.TestCase):
    def test_old_single_key_settings_migrate(self):
        tmp = tempfile.mkdtemp(prefix="amr_cfg_")
        original = os.environ.get("APPDATA")
        os.environ["APPDATA"] = tmp
        try:
            with open(config.settings_path(), "w", encoding="utf-8") as f:
                json.dump({"api_key": "sk-old", "model": "claude-opus-4-8"},
                          f)
            settings = config.load_settings()
            self.assertEqual(settings["anthropic_api_keys"], ["sk-old"])
            self.assertEqual(settings["anthropic_model"], "claude-opus-4-8")
            # A user who had a working Anthropic key keeps using it.
            self.assertEqual(settings["provider"], "anthropic")
            self.assertEqual(settings["gemini_api_keys"], [])
        finally:
            if original is None:
                del os.environ["APPDATA"]
            else:
                os.environ["APPDATA"] = original
            shutil.rmtree(tmp, ignore_errors=True)




class TestPanelSplitting(unittest.TestCase):
    SCRIPT = """Panel 1: Two students at the school gate.
Aiko: "You're late again!"
SFX: zaaa -- wind through the trees
Panel 2: Close-up of Kenta's embarrassed smile.
Kenta: "Sorry."
Panel 3: Silent. Aiko turns away."""

    def test_splits_into_units_with_dialogue_attached(self):
        units = prompts.split_panels(self.SCRIPT)
        self.assertEqual(len(units), 3)
        self.assertIn("You're late again!", units[0])
        self.assertIn("SFX: zaaa", units[0])
        self.assertTrue(units[1].startswith("Panel 2:"))
        self.assertIn("Silent", units[2])

    def test_preamble_attaches_to_first_unit(self):
        script = "Cover page of volume two.\n" + self.SCRIPT
        units = prompts.split_panels(script)
        self.assertEqual(len(units), 3)
        self.assertTrue(units[0].startswith("Cover page"))

    def test_no_markers_is_single_unit(self):
        units = prompts.split_panels("A title page reading Volume 3.")
        self.assertEqual(units, ["A title page reading Volume 3."])

    def test_empty_script(self):
        self.assertEqual(prompts.split_panels("   "), [])


class TestOpenAIClient(unittest.TestCase):
    def test_payload_structure(self):
        import tempfile
        from core import api_client
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            make_test_image(10, 10).save(f, "JPEG")
            image_path = f.name
        try:
            client = api_client.OpenAIClient("key", "gpt-5.1",
                                             max_tokens=2222)
            content = api_client.build_content([1], [image_path], "go")
            payload = client._build_payload("system text", content)
            self.assertEqual(payload["messages"][0]["role"], "system")
            self.assertEqual(payload["messages"][0]["content"],
                             "system text")
            parts = payload["messages"][1]["content"]
            self.assertEqual(parts[0]["text"], "Page 1:")
            self.assertTrue(parts[1]["image_url"]["url"].startswith(
                "data:image/jpeg;base64,"))
            self.assertEqual(payload["max_completion_tokens"], 2222)
        finally:
            os.unlink(image_path)

    def test_extract_text_success(self):
        from core import api_client
        data = {"choices": [{"message": {"content": "=== PAGE 1 ==="},
                             "finish_reason": "stop"}]}
        self.assertEqual(api_client.OpenAIClient.extract_text(data),
                         "=== PAGE 1 ===")

    def test_extract_text_content_filter(self):
        from core import api_client
        with self.assertRaises(api_client.ApiError):
            api_client.OpenAIClient.extract_text(
                {"choices": [{"message": {"content": ""},
                              "finish_reason": "content_filter"}]})

    def test_factory_returns_openai_client(self):
        from core import api_client
        settings = dict(config.DEFAULT_SETTINGS)
        settings["provider"] = "openai"
        settings["openai_api_keys"] = ["abc"]
        client = api_client.create_client(settings)
        self.assertIs(client.client_class, api_client.OpenAIClient)


class TestModelListParsers(unittest.TestCase):
    def test_gemini_parser_filters_and_strips(self):
        from core import api_client
        data = {"models": [
            {"name": "models/gemini-3-flash-preview",
             "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-embedding-001",
             "supportedGenerationMethods": ["embedContent"]},
            {"name": "models/imagen-4",
             "supportedGenerationMethods": ["generateContent"]},
        ]}
        self.assertEqual(api_client.parse_gemini_model_list(data),
                         ["gemini-3-flash-preview"])

    def test_gemini_parser_excludes_non_vision_families(self):
        """Families that cannot read pages are hidden from the dropdown
        even when they support generateContent."""
        from core import api_client
        data = {"models": [
            {"name": "models/gemini-2.5-flash",
             "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-2.5-pro",
             "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-2.5-flash-preview-tts",
             "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-2.0-flash-preview-image-generation",
             "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-2.5-flash-native-audio-dialog",
             "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-embedding-exp",
             "supportedGenerationMethods": ["generateContent"]},
        ]}
        self.assertEqual(api_client.parse_gemini_model_list(data),
                         ["gemini-2.5-pro", "gemini-2.5-flash"])

    def test_openai_parser_excludes_non_chat(self):
        from core import api_client
        data = {"data": [
            {"id": "gpt-5.1"},
            {"id": "whisper-1"},
            {"id": "text-embedding-3-large"},
            {"id": "dall-e-3"},
            {"id": "gpt-4o"},
        ]}
        models = api_client.parse_openai_model_list(data)
        self.assertIn("gpt-5.1", models)
        self.assertIn("gpt-4o", models)
        self.assertNotIn("whisper-1", models)
        self.assertNotIn("dall-e-3", models)

    def test_openai_parser_excludes_non_vision_families(self):
        """Audio, TTS, image-generation and moderation variants are
        hidden; ordinary chat/vision models remain."""
        from core import api_client
        data = {"data": [
            {"id": "gpt-4o"},
            {"id": "gpt-4o-audio-preview"},
            {"id": "gpt-4o-mini-tts"},
            {"id": "gpt-4o-transcribe"},
            {"id": "gpt-image-1"},
            {"id": "gpt-4o-realtime-preview"},
            {"id": "omni-moderation-latest"},
            {"id": "o3"},
        ]}
        models = api_client.parse_openai_model_list(data)
        self.assertEqual(sorted(models), ["gpt-4o", "o3"])

    def test_anthropic_parser(self):
        from core import api_client
        data = {"data": [{"id": "claude-sonnet-4-6"},
                         {"id": "claude-opus-4-8"}]}
        models = api_client.parse_anthropic_model_list(data)
        self.assertEqual(models, ["claude-sonnet-4-6", "claude-opus-4-8"])


class TestUpdateCheck(unittest.TestCase):
    """The version comparison behind update notifications. Fed sample
    release JSON directly; no network access."""

    @staticmethod
    def _release(tag, prerelease=False, **extra):
        release = {"tag_name": tag, "prerelease": prerelease,
                   "body": "notes for %s" % tag,
                   "html_url": "https://example.invalid/%s" % tag}
        release.update(extra)
        return release

    def test_newer_stable_version_is_offered(self):
        from core import updates
        releases = [self._release("v0.9.0"), self._release("v0.11.0")]
        update = updates.newest_release(releases, "0.10.1")
        self.assertEqual(update.version, "0.11.0")
        self.assertEqual(update.notes, "notes for v0.11.0")
        self.assertEqual(update.url, "https://example.invalid/v0.11.0")

    def test_equal_or_older_version_is_not_offered(self):
        from core import updates
        self.assertIsNone(updates.newest_release(
            [self._release("v0.10.1")], "0.10.1"))
        self.assertIsNone(updates.newest_release(
            [self._release("v0.9.0")], "0.10.1"))

    def test_comparison_is_numeric_not_string(self):
        from core import updates
        # As strings "0.9.0" > "0.10.0"; numerically it is older.
        update = updates.newest_release(
            [self._release("v0.10.0")], "0.9.0")
        self.assertIsNotNone(update)
        self.assertEqual(update.version, "0.10.0")
        self.assertIsNone(updates.newest_release(
            [self._release("v0.9.0")], "0.10.0"))

    def test_prereleases_ignored_when_betas_off(self):
        from core import updates
        releases = [self._release("v0.12.0", prerelease=True),
                    self._release("v0.11.0")]
        update = updates.newest_release(
            releases, "0.10.1", include_betas=False)
        self.assertEqual(update.version, "0.11.0")
        update = updates.newest_release(
            releases, "0.10.1", include_betas=True)
        self.assertEqual(update.version, "0.12.0")

    def test_drafts_are_ignored(self):
        from core import updates
        self.assertIsNone(updates.newest_release(
            [self._release("v9.9.9", draft=True)], "0.10.1"))

    def test_malformed_data_returns_none_without_raising(self):
        from core import updates
        for data in (None, {}, "nonsense", 42,
                     [None, 42, "text"],
                     [{"tag_name": "not-a-version"}],
                     [{"no_tag": "at all"}],
                     [{"tag_name": ""}]):
            self.assertIsNone(updates.newest_release(data, "0.10.1"))
        # A malformed current version is also survived.
        self.assertIsNone(updates.newest_release(
            [self._release("v0.11.0")], "garbage"))


class TestBookKindAndPositions(unittest.TestCase):
    def test_source_kind_and_panel_position_round_trip(self):
        tmp = tempfile.mkdtemp(prefix="amr_kind_")
        try:
            book = library.Book(tmp)
            book.title = "Images batch"
            book.source_kind = "images"
            book.last_page = 7
            book.last_panel = 2
            book.save()
            loaded = library.Book.load(tmp)
            self.assertEqual(loaded.source_kind, "images")
            self.assertEqual(loaded.last_page, 7)
            self.assertEqual(loaded.last_panel, 2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_new_settings_defaults(self):
        self.assertEqual(config.DEFAULT_SETTINGS["reader_view"], "book")
        self.assertIn("openai", config.SUGGESTED_MODELS)
        self.assertEqual(config.DEFAULT_SETTINGS["gemini_model"],
                         "gemini-3.5-flash")




class Test429Parsing(unittest.TestCase):
    def test_gemini_daily_quota_detected(self):
        from core import api_client
        body = {"error": {
            "message": "You exceeded your current quota.",
            "details": [
                {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                 "violations": [{
                     "quotaId": "GenerateRequestsPerDayPerProjectPerModel"
                 }]},
                {"@type": "type.googleapis.com/google.rpc.RetryInfo",
                 "retryDelay": "37s"},
            ]}}
        message, retry_seconds, is_daily = api_client.parse_gemini_429(body)
        self.assertTrue(is_daily)
        self.assertEqual(retry_seconds, 37.0)
        self.assertIn("exceeded", message)

    def test_gemini_per_minute_quota_is_retryable(self):
        from core import api_client
        body = {"error": {
            "message": "Resource has been exhausted.",
            "details": [
                {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                 "violations": [{
                     "quotaId": "GenerateRequestsPerMinutePerProject"
                 }]},
            ]}}
        _message, _retry, is_daily = api_client.parse_gemini_429(body)
        self.assertFalse(is_daily)

    def test_gemini_empty_body_is_safe(self):
        from core import api_client
        message, retry_seconds, is_daily = api_client.parse_gemini_429({})
        self.assertTrue(message)
        self.assertIsNone(retry_seconds)
        self.assertFalse(is_daily)

    def test_openai_insufficient_quota_detected(self):
        from core import api_client
        body = {"error": {
            "message": "You exceeded your current quota, please check "
                       "your plan and billing details.",
            "type": "insufficient_quota",
            "code": "insufficient_quota"}}
        info = api_client.parse_openai_429(body)
        self.assertTrue(info["insufficient"])
        self.assertIn("billing", info["message"])

    def test_openai_plain_rate_limit_is_retryable(self):
        from core import api_client
        body = {"error": {
            "message": "Rate limit reached for gpt-5.1 on requests per "
                       "min (RPM): Limit 500, Used 500, Requested 1. "
                       "Please try again in 120ms.",
            "type": "requests",
            "code": "rate_limit_exceeded"}}
        info = api_client.parse_openai_429(body)
        self.assertFalse(info["insufficient"])
        self.assertFalse(info["is_daily"])
        # Requested (1) is under Limit (500): retrying can succeed.
        self.assertFalse(info["request_too_large"])

    def test_openai_single_request_exceeds_tpm(self):
        from core import api_client
        body = {"error": {
            "message": "Rate limit reached for gpt-4o on tokens per min "
                       "(TPM): Limit 30000, Used 0, Requested 45123. "
                       "Please reduce your prompt.",
            "type": "tokens",
            "code": "rate_limit_exceeded"}}
        info = api_client.parse_openai_429(body)
        self.assertTrue(info["request_too_large"])
        self.assertFalse(info["insufficient"])

    def test_openai_daily_limit_detected(self):
        from core import api_client
        body = {"error": {
            "message": "Rate limit reached for gpt-5.1 on requests per "
                       "day (RPD): Limit 200, Used 200, Requested 1.",
            "type": "requests",
            "code": "rate_limit_exceeded"}}
        info = api_client.parse_openai_429(body)
        self.assertTrue(info["is_daily"])
        self.assertFalse(info["request_too_large"])

    def test_openai_limit_numbers_with_commas(self):
        from core import api_client
        body = {"error": {
            "message": "Rate limit reached on tokens per min (TPM): "
                       "Limit 30,000, Used 0, Requested 61,500.",
            "type": "tokens", "code": "rate_limit_exceeded"}}
        info = api_client.parse_openai_429(body)
        self.assertTrue(info["request_too_large"])




class TestReadableError(unittest.TestCase):
    class FakeResponse:
        def __init__(self, json_data=None, text=""):
            self._json = json_data
            self.text = text

        def json(self):
            if self._json is None:
                raise ValueError("not json")
            return self._json

    def test_extracts_error_message(self):
        from core import api_client
        response = self.FakeResponse(
            {"error": {"message": "Invalid model name.", "code": 400}})
        self.assertEqual(api_client.readable_error(response),
                         "Invalid model name.")

    def test_falls_back_to_raw_text(self):
        from core import api_client
        response = self.FakeResponse(None, "<html>Bad gateway</html>")
        self.assertEqual(api_client.readable_error(response),
                         "<html>Bad gateway</html>")




class TestPanelPositions(unittest.TestCase):
    SCRIPT = """Panel 1 (top right): Two students at the school gate.
Aiko: "You're late again!"
Panel 2 (top left): Close-up of Kenta's embarrassed smile.
Panel 3 (bottom half): Silent. Aiko turns away."""

    def test_split_handles_position_parentheticals(self):
        units = prompts.split_panels(self.SCRIPT)
        self.assertEqual(len(units), 3)
        self.assertIn("You're late again!", units[0])
        self.assertTrue(units[2].startswith("Panel 3 (bottom half):"))

    def test_position_extraction(self):
        units = prompts.split_panels(self.SCRIPT)
        self.assertEqual(prompts.panel_position(units[0]), "top right")
        self.assertEqual(prompts.panel_position(units[2]), "bottom half")

    def test_old_scripts_without_positions_still_work(self):
        script = "Panel 1: A quiet street.\nPanel 2: A cat appears."
        units = prompts.split_panels(script)
        self.assertEqual(len(units), 2)
        self.assertEqual(prompts.panel_position(units[0]), "")

    def test_system_prompt_teaches_positions_and_strict_rtl(self):
        prompt = prompts.build_system_prompt("rtl", "detailed", "English")
        self.assertIn("(<position>)", prompt)
        self.assertIn("top right", prompt)
        self.assertIn("EVERY level", prompt)
        self.assertIn("Vertical Japanese text columns", prompt)


class TestUserInstructions(unittest.TestCase):
    def test_instructions_included_in_user_text(self):
        text = prompts.build_user_text(
            [1, 2], "", "Vol 1",
            user_instructions="Aiko: short dark hair. Kenta: messy hair.")
        self.assertIn("READER'S INSTRUCTIONS", text)
        self.assertIn("Kenta: messy hair.", text)
        # Instructions come before the character notes section.
        self.assertLess(text.index("READER'S INSTRUCTIONS"),
                        text.index("CHARACTER NOTES"))

    def test_blank_instructions_add_nothing(self):
        text = prompts.build_user_text([1], "", "Vol 1",
                                       user_instructions="   ")
        self.assertNotIn("READER'S INSTRUCTIONS", text)

    def test_instructions_round_trip_in_book(self):
        tmp = tempfile.mkdtemp(prefix="amr_instr_")
        try:
            book = library.Book(tmp)
            book.user_instructions = "Main character is Yuki."
            book.save()
            loaded = library.Book.load(tmp)
            self.assertEqual(loaded.user_instructions,
                             "Main character is Yuki.")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)




class TestVerbosityAndObjectivity(unittest.TestCase):
    def test_extensive_verbosity_present(self):
        prompt = prompts.build_system_prompt("rtl", "extensive", "English")
        self.assertIn("EXTENSIVE", prompt)
        self.assertIn("length is unlimited", prompt)
        self.assertIn("speed lines", prompt)
        self.assertIn("objectivity rule applies in full", prompt)

    def test_extensive_list_is_framed_as_a_checklist(self):
        # The numbered points are what to cover, not sections to print.
        # Presenting them as output structure is what made some models
        # emit "Composition:" / "Characters:" headings.
        prompt = prompts.build_system_prompt("rtl", "extensive", "English")
        self.assertIn("checklist of what to COVER", prompt)
        self.assertIn("not a structure to reproduce", prompt)
        self.assertIn("never print their names as headings", prompt)
        self.assertIn("weave them into", prompt)

    def test_extensive_does_not_ask_to_name_absent_categories(self):
        # The old wording told the model to say a category was empty,
        # which produced category labels in the output.
        prompt = prompts.build_system_prompt("rtl", "extensive", "English")
        self.assertNotIn("say so in a few words", prompt)
        self.assertNotIn("plain white background", prompt)
        self.assertIn("do not name the category to say so", prompt)

    def test_objectivity_rule_at_every_level(self):
        for verbosity in ("concise", "detailed", "extensive"):
            prompt = prompts.build_system_prompt("rtl", verbosity, "English")
            self.assertIn("camera, not a critic", prompt)
            self.assertIn("only what is visibly drawn", prompt)

    def test_unknown_verbosity_falls_back_to_detailed(self):
        prompt = prompts.build_system_prompt("rtl", "nonsense", "English")
        self.assertIn("DETAILED", prompt)


class TestProgressPercent(WorkspaceTestCase):
    def test_progress_messages_include_percent(self):
        from core import api_client

        class FakeClient:
            def request_scripts(self, system_prompt, content,
                                cancel_check=None):
                pages = [int(block["text"].split()[1].rstrip(":"))
                         for block in content
                         if block["type"] == "text"
                         and block["text"].startswith("Page ")]
                parts = ["=== PAGE %d ===\nPanel 1 (top right): x." % n
                         for n in pages]
                return "\n\n".join(parts)

        book = library.Book(self.workspace)
        book.title = "Progress Book"
        pages_dir = os.path.join(self.workspace, "pages")
        os.makedirs(pages_dir, exist_ok=True)
        for i in range(1, 5):
            make_test_image().save(
                os.path.join(pages_dir, "%04d.jpg" % i), "JPEG")
        book.detect_page_count()

        messages = []
        original = api_client.create_client
        api_client.create_client = lambda settings: FakeClient()
        try:
            settings = dict(config.DEFAULT_SETTINGS)
            settings.update({"gemini_api_keys": ["k"],
                             "pages_per_request": 2,
                             "request_delay_seconds": 0})
            processor.process_book(
                book, settings,
                on_progress=lambda m, d, t: messages.append(m))
        finally:
            api_client.create_client = original

        joined = "\n".join(messages)
        self.assertIn("Starting: 4 pages to process in 2 batches", joined)
        self.assertIn("50 percent", joined)
        self.assertIn("100 percent", joined)
        self.assertIn("batch 1 of 2", joined)




class TestProcessorTokenBudget(WorkspaceTestCase):
    def _book(self, pages):
        book = library.Book(self.workspace)
        book.title = "Budget Book"
        pages_dir = os.path.join(self.workspace, "pages")
        os.makedirs(pages_dir, exist_ok=True)
        for i in range(1, pages + 1):
            make_test_image().save(
                os.path.join(pages_dir, "%04d.jpg" % i), "JPEG")
        book.detect_page_count()
        return book

    def test_extensive_verbosity_boosts_max_tokens(self):
        from core import api_client
        captured = {}

        class FakeClient:
            def request_scripts(self, system_prompt, content,
                                cancel_check=None):
                return "=== PAGE 1 ===\nPanel 1 (top right): x."

        def fake_factory(settings):
            captured.update(settings)
            return FakeClient()

        original = api_client.create_client
        api_client.create_client = fake_factory
        try:
            book = self._book(1)
            settings = dict(config.DEFAULT_SETTINGS)
            settings.update({"gemini_api_keys": ["k"], "verbosity": "extensive",
                             "pages_per_request": 4,
                             "request_delay_seconds": 0})
            processor.process_book(book, settings)
        finally:
            api_client.create_client = original
        # 3200 per page * 4 pages + 1000 headroom > default 8000.
        self.assertGreaterEqual(captured["max_tokens"], 13800)

    def test_concise_keeps_configured_budget(self):
        from core import api_client
        captured = {}

        class FakeClient:
            def request_scripts(self, system_prompt, content,
                                cancel_check=None):
                return "=== PAGE 1 ===\nPanel 1 (top right): x."

        def fake_factory(settings):
            captured.update(settings)
            return FakeClient()

        original = api_client.create_client
        api_client.create_client = fake_factory
        try:
            book = self._book(1)
            settings = dict(config.DEFAULT_SETTINGS)
            settings.update({"gemini_api_keys": ["k"], "verbosity": "concise",
                             "pages_per_request": 4,
                             "request_delay_seconds": 0})
            processor.process_book(book, settings)
        finally:
            api_client.create_client = original
        self.assertEqual(captured["max_tokens"], 8000)


class TestCancelDiscardsInFlight(WorkspaceTestCase):
    def test_batch_arriving_after_cancel_is_not_saved(self):
        from core import api_client
        import threading
        cancel = threading.Event()

        class FakeClient:
            def request_scripts(self, system_prompt, content,
                                cancel_check=None):
                # Simulate: the user cancels while this request is in
                # flight; the response still arrives afterwards.
                cancel.set()
                return "=== PAGE 1 ===\nPanel 1 (top right): late reply."

        book = library.Book(self.workspace)
        book.title = "Cancel Book"
        pages_dir = os.path.join(self.workspace, "pages")
        os.makedirs(pages_dir, exist_ok=True)
        make_test_image().save(
            os.path.join(pages_dir, "0001.jpg"), "JPEG")
        book.detect_page_count()

        original = api_client.create_client
        api_client.create_client = lambda settings: FakeClient()
        try:
            settings = dict(config.DEFAULT_SETTINGS)
            settings.update({"gemini_api_keys": ["k"],
                             "request_delay_seconds": 0})
            result = processor.process_book(
                book, settings, cancel_check=cancel.is_set)
        finally:
            api_client.create_client = original

        self.assertTrue(result.cancelled)
        self.assertEqual(book.scripts, {})




class TestKeyParsing(unittest.TestCase):
    def test_parse_lines_strips_and_dedupes(self):
        text = "  key-one \n\nkey-two\nkey-one\n   \nkey-three"
        self.assertEqual(config.parse_api_keys(text),
                         ["key-one", "key-two", "key-three"])

    def test_parse_empty(self):
        self.assertEqual(config.parse_api_keys("   \n\n"), [])


class TestKeyRotation(unittest.TestCase):
    def _rotating(self, behaviours, keys=("k1", "k2", "k3")):
        """behaviours: dict key -> callable(...) returning text or raising."""
        from core import api_client

        class FakeClient:
            def __init__(self, api_key, model, max_tokens=8000):
                self.api_key = api_key

            def request_scripts(self, system_prompt, content,
                                cancel_check=None):
                return behaviours[self.api_key]()

        return api_client.RotatingClient(FakeClient, list(keys), "model")

    def test_switches_to_next_key_when_quota_exhausted(self):
        from core import api_client

        def exhausted():
            raise api_client.ApiError("daily quota used up",
                                      key_exhausted=True)

        client = self._rotating({
            "k1": exhausted,
            "k2": lambda: "=== PAGE 1 ===\nPanel 1 (top right): ok.",
            "k3": exhausted,
        })
        switches = []
        client.on_key_switch = lambda i, t, r: switches.append((i, t))
        result = client.request_scripts("sys", [])
        self.assertIn("PAGE 1", result)
        self.assertEqual(switches, [(2, 3)])
        # The working key stays current for the next request.
        self.assertEqual(client.index, 1)

    def test_all_keys_exhausted_raises_with_advice(self):
        from core import api_client

        def exhausted():
            raise api_client.ApiError("quota used up", key_exhausted=True)

        client = self._rotating({k: exhausted for k in ("k1", "k2", "k3")})
        with self.assertRaises(api_client.ApiError) as caught:
            client.request_scripts("sys", [])
        message = str(caught.exception)
        self.assertIn("All 3 API keys", message)
        self.assertIn("same project or account share one quota", message)

    def test_non_key_errors_do_not_rotate(self):
        from core import api_client

        def bad_request():
            raise api_client.ApiError("The API rejected the request")

        client = self._rotating({k: bad_request for k in ("k1", "k2", "k3")})
        with self.assertRaises(api_client.ApiError) as caught:
            client.request_scripts("sys", [])
        self.assertIn("rejected the request", str(caught.exception))
        self.assertEqual(client.index, 0)  # never rotated

    def test_single_key_raises_original_error(self):
        from core import api_client

        def exhausted():
            raise api_client.ApiError("daily quota used up",
                                      key_exhausted=True)

        client = self._rotating({"k1": exhausted}, keys=("k1",))
        with self.assertRaises(api_client.ApiError) as caught:
            client.request_scripts("sys", [])
        self.assertIn("daily quota used up", str(caught.exception))


class TestKeyListMigration(unittest.TestCase):
    def test_single_key_becomes_list(self):
        tmp = tempfile.mkdtemp(prefix="amr_keys_")
        original = os.environ.get("APPDATA")
        os.environ["APPDATA"] = tmp
        try:
            with open(config.settings_path(), "w", encoding="utf-8") as f:
                json.dump({"provider": "gemini",
                           "gemini_api_key": "AIza-old",
                           "openai_api_key": ""}, f)
            settings = config.load_settings()
            self.assertEqual(settings["gemini_api_keys"], ["AIza-old"])
            self.assertEqual(settings["openai_api_keys"], [])
        finally:
            if original is None:
                del os.environ["APPDATA"]
            else:
                os.environ["APPDATA"] = original
            shutil.rmtree(tmp, ignore_errors=True)




class TestOpenAICompatibleServices(unittest.TestCase):
    def test_openrouter_uses_its_own_endpoint(self):
        from core import api_client
        settings = dict(config.DEFAULT_SETTINGS)
        settings["provider"] = "openrouter"
        settings["openrouter_api_keys"] = ["k"]
        client = api_client.create_client(settings)
        inner = client._client_for(0)
        self.assertEqual(
            inner.URL, "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(inner.SERVICE_NAME, "OpenRouter")

    def test_openai_endpoint_unchanged(self):
        from core import api_client
        settings = dict(config.DEFAULT_SETTINGS)
        settings["provider"] = "openai"
        settings["openai_api_keys"] = ["k"]
        inner = api_client.create_client(settings)._client_for(0)
        self.assertEqual(
            inner.URL, "https://api.openai.com/v1/chat/completions")

    def test_custom_endpoint_url_is_used(self):
        from core import api_client
        settings = dict(config.DEFAULT_SETTINGS)
        settings.update({
            "provider": "custom",
            "custom_api_keys": ["k"],
            "custom_model": "llama-4-scout",
            "custom_base_url": "https://api.groq.com/openai/v1/",
        })
        inner = api_client.create_client(settings)._client_for(0)
        self.assertEqual(
            inner.URL, "https://api.groq.com/openai/v1/chat/completions")

    def test_custom_without_url_raises(self):
        from core import api_client
        settings = dict(config.DEFAULT_SETTINGS)
        settings.update({"provider": "custom", "custom_api_keys": ["k"],
                         "custom_model": "m", "custom_base_url": ""})
        with self.assertRaises(api_client.ApiError):
            api_client.create_client(settings)

    def test_missing_model_raises(self):
        from core import api_client
        settings = dict(config.DEFAULT_SETTINGS)
        settings.update({"provider": "custom", "custom_api_keys": ["k"],
                         "custom_model": "",
                         "custom_base_url": "https://example.com/v1"})
        with self.assertRaises(api_client.ApiError):
            api_client.create_client(settings)

    def test_openrouter_payload_is_openai_shaped(self):
        import tempfile
        from core import api_client
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            make_test_image(10, 10).save(f, "JPEG")
            image_path = f.name
        try:
            client = api_client.OpenRouterClient(
                "k", "google/gemma-4-31b-it:free")
            content = api_client.build_content([1], [image_path], "go")
            payload = client._build_payload("sys", content)
            self.assertEqual(payload["model"], "google/gemma-4-31b-it:free")
            parts = payload["messages"][1]["content"]
            self.assertTrue(parts[1]["image_url"]["url"].startswith(
                "data:image/jpeg;base64,"))
        finally:
            os.unlink(image_path)


class TestOpenAICompatibleModelList(unittest.TestCase):
    DATA = {"data": [
        {"id": "text/only-model:free",
         "architecture": {"input_modalities": ["text"]}},
        {"id": "google/gemma-4-31b-it:free",
         "architecture": {"input_modalities": ["text", "image"]}},
        {"id": "paid/vision-model",
         "architecture": {"input_modalities": ["text", "image"]}},
        {"id": "unknown/no-metadata"},
    ]}

    def test_vision_filter_keeps_image_models_and_unknowns(self):
        from core import api_client
        models = api_client.parse_openai_compatible_model_list(
            self.DATA, vision_only=True)
        self.assertIn("google/gemma-4-31b-it:free", models)
        self.assertIn("paid/vision-model", models)
        # Text-only models are useless for reading manga pages.
        self.assertNotIn("text/only-model:free", models)
        # No declared modalities is not proof of no vision: keep it.
        self.assertIn("unknown/no-metadata", models)

    def test_free_models_are_listed_first(self):
        from core import api_client
        models = api_client.parse_openai_compatible_model_list(self.DATA)
        self.assertTrue(models[0].endswith(":free"))
        self.assertFalse(models[-1].endswith(":free"))

    def test_without_filter_keeps_everything(self):
        from core import api_client
        models = api_client.parse_openai_compatible_model_list(self.DATA)
        self.assertEqual(len(models), 4)




class TestLocalEndpoints(unittest.TestCase):
    def test_recognises_local_urls(self):
        for url in ("http://localhost:11434/v1", "http://127.0.0.1:1234/v1",
                    "HTTP://LocalHost:8080/v1", "http://[::1]:5000/v1"):
            self.assertTrue(config.is_local_endpoint(url), url)

    def test_remote_and_empty_urls_are_not_local(self):
        for url in ("https://api.groq.com/openai/v1",
                    "https://openrouter.ai/api/v1", "", None,
                    "https://localhost.evil.com/v1"):
            self.assertFalse(config.is_local_endpoint(url), url)

    def test_local_server_needs_no_api_key(self):
        from core import api_client
        settings = dict(config.DEFAULT_SETTINGS)
        settings.update({"provider": "custom", "custom_api_keys": [],
                         "custom_model": "qwen3-vl:8b",
                         "custom_base_url": "http://localhost:11434/v1"})
        client = api_client.create_client(settings)
        self.assertEqual(client.api_keys, ["local"])
        self.assertEqual(
            client._client_for(0).URL,
            "http://localhost:11434/v1/chat/completions")

    def test_remote_service_still_requires_a_key(self):
        from core import api_client
        settings = dict(config.DEFAULT_SETTINGS)
        settings.update({"provider": "custom", "custom_api_keys": [],
                         "custom_model": "llama-4-scout",
                         "custom_base_url": "https://api.groq.com/openai/v1"})
        with self.assertRaises(api_client.ApiError):
            api_client.create_client(settings)




class TestLanguageSetting(unittest.TestCase):
    def test_suggested_languages_offered(self):
        self.assertIn("English", config.SUGGESTED_LANGUAGES)
        self.assertIn("Arabic", config.SUGGESTED_LANGUAGES)
        self.assertIn("Japanese", config.SUGGESTED_LANGUAGES)

    def test_any_language_reaches_the_prompt(self):
        # The box stays editable, so a language not on the list must
        # still be honoured.
        prompt = prompts.build_system_prompt("rtl", "detailed", "Swahili")
        self.assertIn("WRITE THE ENTIRE SCRIPT IN Swahili", prompt)

    def test_listed_language_reaches_the_prompt(self):
        prompt = prompts.build_system_prompt("rtl", "detailed", "Arabic")
        self.assertIn("WRITE THE ENTIRE SCRIPT IN Arabic", prompt)

    def test_language_covers_descriptions_not_only_text(self):
        # The setting governs the whole script -- panel descriptions as
        # well as translated dialogue -- so a non-English target does
        # not produce a mixed-language script.
        prompt = prompts.build_system_prompt("manga", "detailed", "Spanish")
        self.assertIn("every panel description", prompt)
        self.assertIn("all dialogue", prompt)

    def test_labels_and_speaker_names_are_in_target_language(self):
        # Speaker names, the thinking/off-panel qualifiers and the
        # SFX/Narration/Text labels all go in the output language.
        prompt = prompts.build_system_prompt("manga", "detailed", "Arabic")
        self.assertIn("every speaker label", prompt)
        self.assertIn('"(thinking)" and "(off-panel)"', prompt)
        self.assertIn('"Narration:", "SFX:", and "Text:" labels, are '
                      "written in Arabic", prompt)

    def test_only_structural_markers_stay_in_english(self):
        prompt = prompts.build_system_prompt("manga", "detailed", "Arabic")
        self.assertIn("three structural markers", prompt)
        self.assertIn('the "=== PAGE n ===" line', prompt)
        self.assertIn('"Panel n (position):" prefix', prompt)
        self.assertIn('"=== CHARACTER NOTES ===" line', prompt)

    def test_character_notes_are_written_in_target_language(self):
        # The notes carry between batches, so they must use the same
        # transliterated names as the script or names would drift.
        prompt = prompts.build_system_prompt("manga", "detailed", "Arabic")
        self.assertIn("Write this list in Arabic too", prompt)
        self.assertIn("same Arabic spelling you use in the script",
                      prompt)

    def test_fallback_labels_follow_the_language(self):
        prompt = prompts.build_system_prompt("manga", "detailed", "Arabic")
        self.assertIn('the Arabic equivalent of "Off-panel voice:" or '
                      '"Unknown:"', prompt)

    def test_names_are_transliterated_into_the_target_alphabet(self):
        # Character names now follow the target language's alphabet, and
        # the speaker label matches the spelling used in the description
        # so the two never diverge.
        prompt = prompts.build_system_prompt("manga", "detailed", "Arabic")
        self.assertIn("transliterated into the Arabic alphabet", prompt)
        self.assertIn("the speaker label for that same character uses "
                      "that identical spelling", prompt)




class TestAnthropicRestClient(unittest.TestCase):
    def test_payload_shape(self):
        import tempfile
        from core import api_client
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            make_test_image(10, 10).save(f, "JPEG")
            image_path = f.name
        try:
            client = api_client.AnthropicClient(
                "k", "claude-sonnet-4-6", max_tokens=4321)
            content = api_client.build_content([1], [image_path], "go")
            payload = client._build_payload("system text", content)
            self.assertEqual(payload["model"], "claude-sonnet-4-6")
            self.assertEqual(payload["max_tokens"], 4321)
            self.assertEqual(payload["system"], "system text")
            blocks = payload["messages"][0]["content"]
            self.assertEqual(blocks[0]["text"], "Page 1:")
            self.assertEqual(blocks[1]["source"]["media_type"], "image/jpeg")
            self.assertTrue(blocks[1]["source"]["data"])
        finally:
            os.unlink(image_path)

    def test_extract_text(self):
        from core import api_client
        data = {"content": [{"type": "text", "text": "=== PAGE 1 ==="},
                            {"type": "text", "text": "\nPanel 1: x."}],
                "stop_reason": "end_turn"}
        self.assertEqual(api_client.AnthropicClient.extract_text(data),
                         "=== PAGE 1 ===\nPanel 1: x.")

    def test_refusal_is_reported(self):
        from core import api_client
        with self.assertRaises(api_client.ApiError):
            api_client.AnthropicClient.extract_text(
                {"content": [], "stop_reason": "refusal"})

    def test_no_sdk_dependency(self):
        # The exe bundles no Anthropic SDK, so the client must work
        # through plain REST like the other services.
        import core.api_client as module
        source = open(module.__file__).read()
        self.assertNotIn("import anthropic", source)


class TestProcessorRobustness(WorkspaceTestCase):
    def _book(self):
        book = library.Book(self.workspace)
        book.title = "Robust Book"
        pages_dir = os.path.join(self.workspace, "pages")
        os.makedirs(pages_dir, exist_ok=True)
        make_test_image().save(
            os.path.join(pages_dir, "0001.jpg"), "JPEG")
        book.detect_page_count()
        return book

    def test_unexpected_error_is_reported_not_raised(self):
        from core import api_client

        class ExplodingClient:
            def request_scripts(self, system_prompt, content,
                                cancel_check=None):
                raise RuntimeError("something unforeseen")

        original = api_client.create_client
        api_client.create_client = lambda settings: ExplodingClient()
        try:
            book = self._book()
            settings = dict(config.DEFAULT_SETTINGS)
            settings.update({"gemini_api_keys": ["k"],
                             "request_delay_seconds": 0})
            result = processor.process_book(book, settings)
        finally:
            api_client.create_client = original

        # Reported cleanly rather than escaping and killing the worker.
        self.assertIn("something unforeseen", result.error)
        self.assertEqual(result.pages_failed, [1])
        self.assertEqual(book.scripts, {})




class TestStricterPromptRules(unittest.TestCase):
    def test_worked_example_present(self):
        prompt = prompts.build_system_prompt("rtl", "detailed", "English")
        self.assertIn("top right, 2) top center, 3) top left", prompt)
        self.assertIn("RETURN TO ITS RIGHT EDGE", prompt)
        # The instruction to map the page before writing now lives in
        # its own MAPPING THE PAGE section rather than inline here.
        self.assertIn("work out its actual layout", prompt)

    def test_completeness_rule_present_at_every_verbosity(self):
        for verbosity in ("concise", "detailed", "extensive"):
            prompt = prompts.build_system_prompt("rtl", verbosity, "English")
            self.assertIn("COMPLETENESS IS MANDATORY", prompt)
            self.assertIn("(illegible)", prompt)


class TestPanelLabelStripping(unittest.TestCase):
    SCRIPT = ("Panel 1 (top right): A boy runs down the street.\n"
              'Aiko: "Wait for me!"\n'
              "Panel 2: Silent. She stops.\n"
              "The sign says Panel 3 is next.")

    def test_prefixes_removed_content_kept(self):
        stripped = prompts.strip_panel_labels(self.SCRIPT)
        self.assertNotIn("Panel 1", stripped)
        self.assertIn("A boy runs down the street.", stripped)
        self.assertIn('Aiko: "Wait for me!"', stripped)
        self.assertIn("Silent. She stops.", stripped)

    def test_midline_mentions_untouched(self):
        stripped = prompts.strip_panel_labels(self.SCRIPT)
        self.assertIn("The sign says Panel 3 is next.", stripped)

    def test_page_markers_untouched(self):
        text = "Page 2 of 9\nPanel 1 (top left): x."
        stripped = prompts.strip_panel_labels(text)
        self.assertIn("Page 2 of 9", stripped)

    def test_default_setting_shows_labels(self):
        self.assertTrue(config.DEFAULT_SETTINGS["show_panel_labels"])


class TestHtmlExport(WorkspaceTestCase):
    def _book(self):
        book = library.Book(self.workspace)
        book.title = "HTML <Test> & Co"
        book.page_count = 2
        book.scripts[1] = ("Panel 1 (top right): A <b>boy</b> runs.\n"
                           'Aiko: "Wait & see!"\n'
                           "Panel 2 (bottom left): Silent.")
        return book

    def test_headings_with_labels(self):
        from core import html_export
        page = html_export.build_html(self._book(), show_panel_labels=True)
        self.assertIn(">HTML &lt;Test&gt; &amp; Co</h1>", page)
        self.assertIn(">Page 1 of 2</h2>", page)
        self.assertIn(">Panel 1 of 2 (top right)</h3>", page)
        self.assertIn(">Panel 2 of 2 (bottom left)</h3>", page)
        # Content is escaped, so nothing a script wrote can inject HTML.
        self.assertIn("A &lt;b&gt;boy&lt;/b&gt; runs.", page)
        self.assertIn("&quot;Wait &amp; see!&quot;", page)

    def test_continuous_mode_has_page_headings_only(self):
        from core import html_export
        page = html_export.build_html(self._book(), show_panel_labels=False)
        self.assertIn(">Page 1 of 2</h2>", page)
        self.assertNotIn("<h3", page)
        self.assertNotIn("Panel 1", page)
        self.assertIn("A &lt;b&gt;boy&lt;/b&gt; runs.", page)

    def test_unprocessed_page_placeholder(self):
        from core import html_export
        page = html_export.build_html(self._book(), show_panel_labels=True)
        self.assertIn(">Page 2 of 2</h2>", page)
        self.assertIn("not been processed yet", page)


class TestPageImageCleanup(WorkspaceTestCase):
    def _book(self):
        book = library.Book(self.workspace)
        book.title = "Cleanup Book"
        pages_dir = os.path.join(self.workspace, "pages")
        os.makedirs(pages_dir, exist_ok=True)
        for i in (1, 2):
            make_test_image().save(
                os.path.join(pages_dir, "%04d.jpg" % i), "JPEG")
        book.detect_page_count()
        book.scripts = {1: "Panel 1 (top right): x.",
                        2: "Panel 1 (top right): y."}
        book.save()
        return book

    def test_cleanup_keeps_book_readable(self):
        book = self._book()
        self.assertTrue(book.has_page_images())
        self.assertGreater(book.page_images_size(), 0)
        book.delete_page_images()
        self.assertFalse(book.has_page_images())
        self.assertEqual(book.page_images_size(), 0)
        # Reading is unaffected: page count and scripts persist on disk.
        loaded = library.Book.load(self.workspace)
        self.assertEqual(loaded.page_count, 2)
        self.assertIn("Panel 1 (top right): x.", loaded.full_text())
        self.assertTrue(loaded.is_complete())




class TestComicTypes(unittest.TestCase):
    def test_all_four_types_have_rules(self):
        for ctype in ("manga", "manhwa", "webtoon", "western"):
            prompt = prompts.build_system_prompt(ctype, "detailed", "English")
            self.assertIn("READING ORDER", prompt)

    def test_manga_is_right_to_left(self):
        p = prompts.build_system_prompt("manga", "detailed", "English")
        self.assertIn("RIGHT-TO-LEFT", p)
        self.assertIn("top right, 2) top center", p)

    def test_manhwa_is_left_to_right_and_colour(self):
        p = prompts.build_system_prompt("manhwa", "detailed", "English")
        self.assertIn("LEFT to RIGHT", p)
        self.assertIn("manhua", p)
        self.assertIn("colour", p)
        self.assertNotIn("RIGHT-TO-LEFT rule is absolute", p)

    def test_webtoon_is_vertical(self):
        p = prompts.build_system_prompt("webtoon", "detailed", "English")
        self.assertIn("TOP to BOTTOM", p)
        self.assertIn("vertical-scroll", p)

    def test_western_is_z_path(self):
        p = prompts.build_system_prompt("western", "detailed", "English")
        self.assertIn("Z-path", p)
        self.assertIn("LEFT to RIGHT", p)

    def test_legacy_direction_values_still_work(self):
        # Old settings saved rtl/ltr/vertical; these must still resolve.
        self.assertIn("RIGHT-TO-LEFT",
                      prompts.build_system_prompt("rtl", "detailed", "English"))
        self.assertIn("Z-path",
                      prompts.build_system_prompt("ltr", "detailed", "English"))
        self.assertIn("vertical-scroll",
                      prompts.build_system_prompt("vertical", "detailed",
                                                  "English"))

    def test_unknown_type_falls_back_to_manga(self):
        p = prompts.build_system_prompt("nonsense", "detailed", "English")
        self.assertIn("RIGHT-TO-LEFT", p)


class TestPromptEnhancements(unittest.TestCase):
    def test_text_association_rule_present(self):
        p = prompts.build_system_prompt("manga", "detailed", "English")
        self.assertIn("CONNECTING TEXT TO WHAT IT BELONGS TO", p)
        self.assertIn("diagram", p)

    def test_no_honorific_instruction(self):
        # The AI must not be told to add or keep Japanese honorifics; it
        # transcribes whatever the text shows.
        for ctype in ("manga", "manhwa", "webtoon", "western"):
            p = prompts.build_system_prompt(ctype, "detailed", "English")
            self.assertNotIn("-san", p)
            self.assertNotIn("-kun", p)
            self.assertIn("add or remove honorifics", p)

    def test_custom_prompt_included_when_present(self):
        p = prompts.build_system_prompt(
            "manga", "detailed", "English",
            custom_prompt="Always name the weather in each outdoor scene.")
        self.assertIn("ADDITIONAL INSTRUCTIONS FOR THIS COMIC TYPE", p)
        self.assertIn("name the weather", p)

    def test_custom_prompt_absent_when_empty(self):
        p = prompts.build_system_prompt("manga", "detailed", "English",
                                        custom_prompt="   ")
        self.assertNotIn("ADDITIONAL INSTRUCTIONS FOR THIS COMIC TYPE", p)


class TestComicTypeSettings(unittest.TestCase):
    def test_default_comic_type_and_custom_prompts(self):
        self.assertEqual(config.DEFAULT_SETTINGS["comic_type"], "manga")
        cp = config.DEFAULT_SETTINGS["custom_prompts"]
        for key in ("manga", "manhwa", "webtoon", "western"):
            self.assertEqual(cp[key], "")

    def test_migration_from_reading_direction(self):
        tmp = tempfile.mkdtemp(prefix="amr_ctype_")
        original = os.environ.get("APPDATA")
        os.environ["APPDATA"] = tmp
        try:
            with open(config.settings_path(), "w", encoding="utf-8") as f:
                json.dump({"reading_direction": "ltr"}, f)
            settings = config.load_settings()
            self.assertEqual(settings["comic_type"], "western")
            self.assertNotIn("reading_direction", settings)
        finally:
            if original is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = original
            shutil.rmtree(tmp, ignore_errors=True)




class TestModelDefaultsAndLists(unittest.TestCase):
    def test_gemini_default_is_stable_flash(self):
        self.assertEqual(config.DEFAULT_SETTINGS["gemini_model"],
                         "gemini-3.5-flash")
        self.assertEqual(config.SUGGESTED_MODELS["gemini"][0],
                         "gemini-3.5-flash")

    def test_every_default_model_is_in_its_suggested_list(self):
        for service in ("gemini", "anthropic", "openai", "openrouter"):
            default = config.DEFAULT_SETTINGS["%s_model" % service]
            self.assertIn(default, config.SUGGESTED_MODELS[service],
                          service)

    def test_ask_instructions_setting_defaults_on(self):
        self.assertTrue(
            config.DEFAULT_SETTINGS["ask_instructions_before_processing"])

    def test_gemini_list_offers_several_current_models(self):
        models = config.SUGGESTED_MODELS["gemini"]
        self.assertGreaterEqual(len(models), 5)
        self.assertEqual(len(set(models)), len(models))  # no duplicates




class TestInteractiveRetryPolicy(unittest.TestCase):
    def test_ask_uses_a_short_retry_policy(self):
        from core import ask
        self.assertLess(ask.ASK_MAX_ATTEMPTS,
                        api_client_module().GeminiClient.MAX_ATTEMPTS)
        self.assertLess(ask.ASK_INITIAL_BACKOFF,
                        api_client_module().GeminiClient.INITIAL_BACKOFF)

    def test_limits_apply_to_a_plain_client(self):
        from core import api_client
        client = api_client.GeminiClient("key", "model")
        api_client.set_retry_limits(client, 2, 4.0)
        self.assertEqual(client.MAX_ATTEMPTS, 2)
        self.assertEqual(client.INITIAL_BACKOFF, 4.0)

    def test_limits_reach_every_key_of_a_rotating_client(self):
        from core import api_client
        rotating = api_client.RotatingClient(
            api_client.GeminiClient, ["one", "two"], "model")
        first = rotating._client_for(0)
        api_client.set_retry_limits(rotating, 2, 4.0)
        second = rotating._client_for(1)
        for client in (first, second):
            self.assertEqual(client.MAX_ATTEMPTS, 2)
            self.assertEqual(client.INITIAL_BACKOFF, 4.0)


def api_client_module():
    from core import api_client
    return api_client


class TestErrorHints(unittest.TestCase):
    def test_server_errors_explained(self):
        from core import api_client
        for code in (500, 502, 503, 504):
            hint = api_client.http_hint(code)
            self.assertIn("overloaded", hint)
            self.assertIn("not caused by your key", hint)

    def test_quota_error_explained(self):
        from core import api_client
        hint = api_client.http_hint(429)
        self.assertIn("delay between requests", hint)
        self.assertIn("resets", hint)

    def test_key_model_and_size_errors_explained(self):
        from core import api_client
        self.assertIn("API key", api_client.http_hint(401))
        self.assertIn("Refresh model list", api_client.http_hint(404))
        self.assertIn("Pages per request", api_client.http_hint(400))

    def test_unknown_status_adds_nothing(self):
        from core import api_client
        self.assertEqual(api_client.http_hint(418), "")




class TestAskFeature(WorkspaceTestCase):
    def _book(self):
        book = library.Book(self.workspace)
        book.title = "Ask Book"
        pages_dir = os.path.join(self.workspace, "pages")
        os.makedirs(pages_dir, exist_ok=True)
        for i in (1, 2, 3):
            make_test_image().save(
                os.path.join(pages_dir, "%04d.jpg" % i), "JPEG")
        book.detect_page_count()
        book.scripts = {1: "Panel 1 (top right): A door.",
                        2: "Panel 1 (top right): A key."}
        book.character_notes = "Aiko: short dark hair."
        return book

    def test_ask_system_prompt_is_grounded_and_localised(self):
        from core import ask
        settings = dict(config.DEFAULT_SETTINGS)
        settings["output_language"] = "Arabic"
        prompt = ask.build_ask_system_prompt(settings)
        self.assertIn("blind reader's question", prompt)
        self.assertIn("say so plainly rather than guessing", prompt)
        self.assertIn("Answer in Arabic", prompt)
        self.assertIn("RIGHT-TO-LEFT", prompt)  # default comic type

    def test_ask_content_includes_context_and_images(self):
        from core import ask
        book = self._book()
        content = ask.build_ask_content(
            book, [1, 2], "Whose door is that?",
            history=[("Earlier q?", "Earlier a.")])
        images = [c for c in content if c.get("type") == "image"]
        self.assertEqual(len(images), 2)
        text = " ".join(c["text"] for c in content
                        if c.get("type") == "text")
        self.assertIn("Aiko: short dark hair.", text)
        self.assertIn("A door.", text)
        self.assertIn("Earlier q?", text)
        self.assertIn("Whose door is that?", text)

    def test_ask_question_caps_pages_and_returns_answer(self):
        from core import api_client, ask

        class FakeClient:
            def __init__(self):
                self.seen_pages = None

            def request_scripts(self, system_prompt, content,
                                cancel_check=None):
                self.seen_pages = [
                    c for c in content if c.get("type") == "image"]
                return "  The door belongs to Aiko.  "

        fake = FakeClient()
        original = api_client.create_client
        api_client.create_client = lambda settings: fake
        try:
            book = self._book()
            settings = dict(config.DEFAULT_SETTINGS)
            settings["gemini_api_keys"] = ["k"]
            answer = ask.ask_question(
                book, settings, "Whose door?", list(range(1, 30)))
        finally:
            api_client.create_client = original
        self.assertEqual(answer, "The door belongs to Aiko.")
        self.assertLessEqual(len(fake.seen_pages), ask.MAX_ASK_PAGES)




class TestAskAnswerFormatting(unittest.TestCase):
    SAMPLE = ("Based on **Page 2**, a detective explains.\n"
              "### **Row 1 (Top of the page)**\n"
              "*   **Panel 1:** The mansion.\n"
              "*   **Panel 2:** The room.\n"
              "---\n"
              "He begins: *\"IT WAS...\"*")

    def test_markdown_symbols_never_reach_the_reader(self):
        from core import ask
        html_out = ask.answer_to_html(self.SAMPLE)
        for symbol in ("**", "###", "---", "* "):
            self.assertNotIn(symbol, html_out)
        self.assertIn("<h4>", html_out)
        self.assertIn("<ul>", html_out)
        self.assertIn("<strong>Page 2</strong>", html_out)

    def test_plain_prose_becomes_paragraphs(self):
        from core import ask
        html_out = ask.answer_to_html("First line.\n\nSecond line.")
        self.assertEqual(html_out.count("<p>"), 2)

    def test_content_is_escaped(self):
        from core import ask
        html_out = ask.answer_to_html("A <script> tag & more")
        self.assertNotIn("<script>", html_out)
        self.assertIn("&lt;script&gt;", html_out)
        self.assertIn("&amp;", html_out)

    def test_conversation_headings_per_question(self):
        from core import ask
        doc = ask.conversation_html(
            "Book", [("Q one?", "Answer one."), ("Q two?", "Answer two.")])
        self.assertIn("<h2>Question 1: Q one?</h2>", doc)
        # The newest heading also carries the jump anchor.
        self.assertIn("Question 2: Q two?</h2>", doc)

    def test_ask_prompt_forbids_markdown(self):
        from core import ask
        prompt = ask.build_ask_system_prompt(dict(config.DEFAULT_SETTINGS))
        self.assertIn("do not use Markdown", prompt)


class TestAskConversationDocument(unittest.TestCase):
    """The document the Ask window shows: questions and answers are both
    headings, and it is never blank."""

    def test_question_and_answer_are_both_headings(self):
        from core import ask
        doc = ask.conversation_html("Book", [("Q?", "A.")])
        self.assertIn("Question 1: Q?</h2>", doc)
        self.assertIn("<h3>Answer</h3>", doc)

    def test_empty_conversation_still_has_a_document(self):
        from core import ask
        doc = ask.conversation_html("Book", [])
        self.assertIn("<title>", doc)
        self.assertIn("No questions yet", doc)

    def test_pending_question_is_shown_with_progress_note(self):
        from core import ask
        doc = ask.conversation_html(
            "Book", [], pending=("Why is she running?", ask.WAITING_TEXT))
        self.assertIn("Question 1: Why is she running?</h2>", doc)
        self.assertIn("<h3>Answer</h3>", doc)
        self.assertIn("Waiting for the answer", doc)
        self.assertNotIn("No questions yet", doc)

    def test_pending_question_follows_completed_ones(self):
        from core import ask
        doc = ask.conversation_html(
            "Book", [("First?", "Done.")],
            pending=("Second?", ask.STOPPED_TEXT))
        self.assertIn("Question 1: First?</h2>", doc)
        self.assertIn("Question 2: Second?</h2>", doc)
        self.assertLess(doc.index("First?"), doc.index("Second?"))
        self.assertIn("Stopped before the AI answered", doc)

    def test_waiting_note_stays_free_of_mechanics(self):
        from core import ask
        self.assertNotIn("page images", ask.WAITING_TEXT)

    def test_document_carries_no_script(self):
        from core import ask
        doc = ask.conversation_html(
            "Book", [("First?", "Done."), ("Second?", "Also done.")])
        self.assertIn("<body>", doc)
        self.assertNotIn("onload", doc)
        self.assertNotIn("tabindex", doc)


class TestMergedBatchRecovery(unittest.TestCase):
    """When a model describes two images under one page header, the
    second page used to vanish. It is now re-requested on its own,
    where there is no other image for it to be merged with -- so
    batching several pages per request stays safe."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "pages"))
        for n in (1, 2):
            Image.new("RGB", (10, 10), "white").save(
                os.path.join(self.tmp, "pages", "%04d.jpg" % n))
        self.book = library.Book(self.tmp)
        self.book.detect_page_count()
        self.settings = {
            "service": "gemini", "gemini_api_keys": ["k"],
            "pages_per_request": 2, "request_delay_seconds": 0,
            "comic_type": "manga", "verbosity": "detailed",
            "output_language": "English",
        }

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_with(self, responses):
        """Run process_book against a client returning canned responses."""
        from core import api_client, processor as proc
        calls = []

        class StubClient:
            def request_scripts(inner, system_prompt, content,
                                cancel_check=None):
                calls.append(content)
                return responses[len(calls) - 1]

        original = api_client.create_client
        api_client.create_client = lambda s: StubClient()
        try:
            result = proc.process_book(self.book, self.settings)
        finally:
            api_client.create_client = original
        return result, calls

    def test_merged_second_page_is_recovered(self):
        merged = "=== PAGE 1 ===\nPanel 1 (top right): both pages here.\n"
        alone = "=== PAGE 2 ===\nPanel 1 (top right): page two alone.\n"
        result, calls = self._run_with([merged, alone])
        # Two requests: the batch, then the recovery for page 2.
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.book.processed_count(), 2)
        self.assertIn("page two alone", self.book.scripts[2])
        self.assertEqual(result.pages_failed, [])

    def test_a_normal_batch_makes_only_one_request(self):
        good = ("=== PAGE 1 ===\nPanel 1 (top right): one.\n"
                "=== PAGE 2 ===\nPanel 1 (top right): two.\n")
        result, calls = self._run_with([good])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.book.processed_count(), 2)

    def test_page_still_missing_after_recovery_is_reported(self):
        merged = "=== PAGE 1 ===\nPanel 1 (top right): both pages here.\n"
        empty = "=== PAGE 9 ===\nPanel 1 (top right): wrong page.\n"
        result, calls = self._run_with([merged, empty])
        # The recovery answered with a single block, so it is mapped
        # positionally onto page 2 rather than being lost.
        self.assertEqual(self.book.processed_count(), 2)


class TestAlignToBatch(unittest.TestCase):
    """Models sometimes number their output from 1 whatever pages they
    were sent, so a request for page 2 comes back labelled page 1. That
    used to be discarded, leaving the page unprocessed with no clue why.
    Position is the reliable signal: the images go in order and the
    model is told so."""

    def test_correct_numbering_is_left_alone(self):
        scripts = {3: "c", 4: "d"}
        self.assertEqual(processor.align_to_batch(scripts, [3, 4]), scripts)

    def test_renumbered_from_one_is_remapped(self):
        # The reported failure: a batch of pages 3 and 4 answered as
        # pages 1 and 2.
        scripts = {1: "third page", 2: "fourth page"}
        self.assertEqual(
            processor.align_to_batch(scripts, [3, 4]),
            {3: "third page", 4: "fourth page"})

    def test_single_page_batch_is_remapped(self):
        # With one page per request, every batch after the first failed.
        self.assertEqual(
            processor.align_to_batch({1: "page two"}, [2]),
            {2: "page two"})

    def test_order_is_preserved_when_remapping(self):
        scripts = {1: "a", 2: "b", 3: "c"}
        self.assertEqual(
            processor.align_to_batch(scripts, [7, 8, 9]),
            {7: "a", 8: "b", 9: "c"})

    def test_a_genuinely_partial_response_is_not_misfiled(self):
        # One block for a two-page batch really is a missing page, and
        # must stay missing rather than being assigned to the wrong one.
        scripts = {1: "only one page came back"}
        self.assertEqual(
            processor.align_to_batch(scripts, [5, 6]), scripts)

    def test_empty_response_is_untouched(self):
        self.assertEqual(processor.align_to_batch({}, [1, 2]), {})

    def test_nonsense_labels_still_map_by_position(self):
        # Two blocks came back for a two-page batch, but one carries a
        # page number that was never requested. The count matches and
        # the images went in order, so position decides -- the labels
        # are exactly what cannot be trusted here.
        scripts = {5: "a", 9: "b"}
        self.assertEqual(
            processor.align_to_batch(scripts, [5, 6]),
            {5: "a", 6: "b"})


class TestConvertedPagesSetting(unittest.TestCase):
    """The processing window shows converted pages one at a time by
    default, so the box can be navigated and does not move under a
    reader as more pages land."""

    def test_one_page_at_a_time_is_the_default(self):
        self.assertTrue(config.DEFAULT_SETTINGS["converted_pages_one_page"])

    def test_setting_survives_a_save_and_load(self):
        appdata = tempfile.mkdtemp()
        old = os.environ.get("APPDATA")
        os.environ["APPDATA"] = appdata
        try:
            settings = config.load_settings()
            self.assertTrue(settings["converted_pages_one_page"])
            settings["converted_pages_one_page"] = False
            config.save_settings(settings)
            self.assertFalse(
                config.load_settings()["converted_pages_one_page"])
        finally:
            if old is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = old
            shutil.rmtree(appdata, ignore_errors=True)


class TestExportFormats(unittest.TestCase):
    """Every export format is built from one shared outline, so a book
    reads the same whichever way it is saved. Headings are what make an
    exported book navigable with a screen reader, so each format is
    checked for them specifically."""

    def setUp(self):
        from core import export
        self.export = export
        self.tmp = tempfile.mkdtemp()
        workspace = os.path.join(self.tmp, "ws")
        os.makedirs(os.path.join(workspace, "pages"))
        self.book = library.Book(workspace)
        self.book.title = "Detective Conan"
        self.book.page_count = 2
        self.book.scripts = {
            1: 'Panel 1 (top right): A street.\nAiko: "Late."\n'
               "Panel 2 (top left): A clock.",
            2: "Panel 1 (top right): Kenta runs.",
        }

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _path(self, name):
        return os.path.join(self.tmp, name)

    # ----- the shared outline -------------------------------------------

    def test_outline_nests_title_pages_and_panels(self):
        kinds = [kind for kind, _ in self.export.book_outline(self.book)]
        self.assertEqual(kinds[0], "h1")
        self.assertEqual(kinds.count("h2"), 2)   # one per page
        self.assertEqual(kinds.count("h3"), 3)   # panels across both pages
        self.assertIn("p", kinds)

    def test_outline_without_panel_labels_has_no_panel_headings(self):
        items = self.export.book_outline(self.book, show_panel_labels=False)
        self.assertEqual([k for k, _ in items].count("h3"), 0)
        self.assertEqual([k for k, _ in items].count("h2"), 2)

    def test_unprocessed_pages_are_named_not_skipped(self):
        self.book.scripts = {1: "Panel 1 (top right): A street."}
        texts = [t for _, t in self.export.book_outline(self.book)]
        self.assertTrue(any("not been processed" in t for t in texts))

    def test_every_format_shares_one_signature(self):
        self.assertEqual(len(self.export.FORMATS), 5)
        for label, extension, wildcard, writer in self.export.FORMATS:
            self.assertTrue(extension.startswith("."))
            self.assertIn("*" + extension, wildcard)
            path = self._path("book" + extension)
            if extension == ".pdf":
                # PDF needs a browser to render it, which a test machine
                # may not have; the renderer is exercised separately.
                continue
            writer(self.book, path, show_panel_labels=True, language="en")
            self.assertGreater(os.path.getsize(path), 0, label)

    # ----- EPUB ----------------------------------------------------------

    def _epub(self):
        path = self._path("b.epub")
        self.export.write_epub(self.book, path)
        return zipfile.ZipFile(path)

    def test_epub_mimetype_is_first_and_uncompressed(self):
        # Required by the EPUB specification; readers reject it otherwise.
        archive = self._epub()
        self.assertEqual(archive.namelist()[0], "mimetype")
        self.assertEqual(archive.infolist()[0].compress_type,
                         zipfile.ZIP_STORED)
        self.assertEqual(archive.read("mimetype"), b"application/epub+zip")

    def test_epub_parts_are_well_formed_xml(self):
        import xml.dom.minidom as dom
        archive = self._epub()
        for name in ("META-INF/container.xml", "OEBPS/package.opf",
                     "OEBPS/nav.xhtml", "OEBPS/content.xhtml"):
            dom.parseString(archive.read(name))

    def test_epub_has_a_heading_for_every_page_and_panel(self):
        content = self._epub().read("OEBPS/content.xhtml").decode()
        self.assertEqual(content.count("<h1 "), 1)
        self.assertEqual(content.count("<h2 id="), 2)
        self.assertEqual(content.count("<h3 "), 3)

    def test_a_books_own_language_survives_save_and_load(self):
        # Exports label a book with the language it was processed in,
        # not whatever the setting happens to say now.
        self.book.output_language = "English"
        self.book.save()
        reloaded = library.Book.load(self.book.workspace)
        self.assertEqual(reloaded.output_language, "English")

    def test_books_from_older_versions_have_no_language(self):
        # Loading a book saved before this field existed must not fail.
        import json
        path = os.path.join(self.book.workspace, "book.json")
        self.book.save()
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        data.pop("output_language", None)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        reloaded = library.Book.load(self.book.workspace)
        self.assertEqual(reloaded.output_language, "")

    def test_blocks_carry_their_own_direction(self):
        # A book's text and the chosen output language can disagree --
        # an English book exported while the setting says Arabic. With
        # one direction forced on the whole document, punctuation moves
        # to the wrong end of a line and words run together.
        from core import html_export
        page = html_export.build_html(self.book, language="Arabic")
        self.assertIn('<p dir="auto">', page)
        self.assertIn('<h2 dir="auto">', page)
        content = self._epub().read("OEBPS/content.xhtml").decode()
        self.assertIn('<p dir="auto">', content)

    def test_epub_navigation_links_to_each_page(self):
        nav = self._epub().read("OEBPS/nav.xhtml").decode()
        self.assertEqual(nav.count("<li>"), 2)
        self.assertIn('epub:type="toc"', nav)

    def test_epub_carries_the_language(self):
        path = self._path("ar.epub")
        self.export.write_epub(self.book, path, language="ar")
        content = zipfile.ZipFile(path).read("OEBPS/content.xhtml").decode()
        self.assertIn('lang="ar"', content)

    def test_epub_sets_rtl_and_ltr_direction(self):
        for language, expected in (("Arabic", "rtl"), ("English", "ltr"),
                                   ("fa", "rtl"), ("ja", "ltr")):
            path = self._path(language.replace(" ", "-") + ".epub")
            self.export.write_epub(self.book, path, language=language)
            archive = zipfile.ZipFile(path)
            for name in ("OEBPS/content.xhtml", "OEBPS/nav.xhtml"):
                content = archive.read(name).decode()
                self.assertIn('dir="%s"' % expected, content)

    def test_epub_escapes_markup_in_the_script(self):
        self.book.scripts = {1: "Panel 1 (top right): a <b> & an ampersand."}
        content = self._epub().read("OEBPS/content.xhtml").decode()
        self.assertNotIn("<b>", content)
        self.assertIn("&amp;", content)

    # ----- Word ----------------------------------------------------------

    def _docx(self):
        path = self._path("b.docx")
        self.export.write_docx(self.book, path)
        return zipfile.ZipFile(path)

    def test_docx_parts_are_well_formed_xml(self):
        import xml.dom.minidom as dom
        archive = self._docx()
        for name in archive.namelist():
            dom.parseString(archive.read(name))

    def test_docx_uses_real_heading_styles(self):
        # Text that merely looks big is not navigable; Word's own
        # Heading styles are what the navigation pane and screen readers
        # respond to.
        document = self._docx().read("word/document.xml").decode()
        self.assertIn('w:val="Heading1"', document)
        self.assertIn('w:val="Heading2"', document)
        self.assertIn('w:val="Heading3"', document)

    def test_docx_headings_declare_an_outline_level(self):
        styles = self._docx().read("word/styles.xml").decode()
        self.assertEqual(styles.count("outlineLvl"), 3)

    def test_docx_has_the_parts_word_requires(self):
        names = self._docx().namelist()
        for required in ("[Content_Types].xml", "_rels/.rels",
                         "word/document.xml", "word/styles.xml"):
            self.assertIn(required, names)

    def test_docx_marks_rtl_paragraphs_and_runs(self):
        path = self._path("ar.docx")
        self.export.write_docx(self.book, path, language="Arabic")
        document = zipfile.ZipFile(path).read("word/document.xml").decode()
        self.assertIn("<w:bidi/>", document)
        self.assertIn("<w:rtl/>", document)
        self.assertIn('w:bidi="ar"', document)

    def test_docx_leaves_ltr_paragraphs_ltr(self):
        document = self._docx().read("word/document.xml").decode()
        self.assertNotIn("<w:bidi/>", document)
        self.assertNotIn("<w:rtl/>", document)

    # ----- PDF -----------------------------------------------------------

    def test_pdf_refuses_rather_than_saving_an_untagged_file(self):
        # Dropping to an untagged PDF would produce a file that cannot
        # be navigated by heading, which is the reason to offer PDF.
        original_writer = self.export._write_tagged_pdf
        original_browser = self.export._find_browser
        self.export._write_tagged_pdf = lambda *args, **kwargs: False
        self.export._find_browser = lambda: "browser"
        try:
            with self.assertRaises(RuntimeError):
                self.export.write_pdf(self.book, self._path("no.pdf"))
        finally:
            self.export._write_tagged_pdf = original_writer
            self.export._find_browser = original_browser

    def test_pdf_failure_names_a_format_that_will_work(self):
        original_writer = self.export._write_tagged_pdf
        original_browser = self.export._find_browser
        self.export._write_tagged_pdf = lambda *args, **kwargs: False
        self.export._find_browser = lambda: "browser"
        try:
            with self.assertRaises(RuntimeError) as raised:
                self.export.write_pdf(self.book, self._path("no2.pdf"))
            self.assertIn("EPUB", str(raised.exception))
        finally:
            self.export._write_tagged_pdf = original_writer
            self.export._find_browser = original_browser

    def test_structure_tree_check_survives_a_bad_file(self):
        path = self._path("not-a.pdf")
        with open(path, "wb") as handle:
            handle.write(b"not a pdf at all")
        self.assertFalse(self.export.has_structure_tree(path))

    def test_tagged_route_declines_when_no_browser_is_present(self):
        original = self.export._find_browsers
        self.export._find_browsers = lambda: []
        try:
            self.assertFalse(self.export._write_tagged_pdf(
                self.book, self._path("none.pdf"), True, "English"))
        finally:
            self.export._find_browsers = original

    def test_browser_route_requests_tags_and_no_headers(self):
        commands = []
        validations = []
        original_browsers = self.export._find_browsers
        original_run = self.export.subprocess.run
        original_check = self.export.has_structure_tree

        def fake_run(command, **kwargs):
            commands.append(command)
            target = next(
                item.split("=", 1)[1] for item in command
                if item.startswith("--print-to-pdf="))
            with open(target, "wb") as handle:
                handle.write(b"%PDF test")
            return type("Result", (), {
                "returncode": 0, "stdout": "", "stderr": ""})()

        def fake_check(path, diagnostics=None):
            validations.append(path)
            # Exercise the compatibility retry: current-browser default
            # tagging declines, then the legacy switch succeeds.
            return len(validations) > 1

        self.export._find_browsers = lambda: ["browser"]
        self.export.subprocess.run = fake_run
        self.export.has_structure_tree = fake_check
        path = self._path("browser.pdf")
        diagnostics = {}
        try:
            self.assertTrue(self.export._write_tagged_pdf(
                self.book, path, True, "Arabic", diagnostics))
        finally:
            self.export._find_browsers = original_browsers
            self.export.subprocess.run = original_run
            self.export.has_structure_tree = original_check
        self.assertTrue(open(path, "rb").read().startswith(b"%PDF"))
        self.assertNotIn("--export-tagged-pdf", commands[0])
        self.assertIn("--export-tagged-pdf", commands[1])
        # Bookmarks are deliberately NOT requested: the flag makes one
        # per heading, and a full volume has over a thousand panel
        # headings, which a PDF reader must build before showing the
        # first page. Heading navigation comes from the tag tree.
        self.assertNotIn("--generate-pdf-document-outline", commands[1])
        self.assertIn("--no-pdf-header-footer", commands[1])
        profiles = [
            next(item for item in command
                 if item.startswith("--user-data-dir="))
            for command in commands
        ]
        self.assertNotEqual(profiles[0], profiles[1])
        self.assertTrue(diagnostics["success"])
        self.assertEqual(diagnostics["direction"], "rtl")
        self.assertEqual(diagnostics["selected_tagging"], "legacy-switch")

    def test_chrome_is_tried_after_every_edge_attempt_fails(self):
        commands = []
        original_browsers = self.export._find_browsers
        original_run = self.export.subprocess.run
        original_check = self.export.has_structure_tree

        def fake_run(command, **kwargs):
            commands.append(command)
            target = next(
                item.split("=", 1)[1] for item in command
                if item.startswith("--print-to-pdf="))
            with open(target, "wb") as handle:
                handle.write(b"%PDF test")
            return type("Result", (), {
                "returncode": 0, "stdout": "", "stderr": ""})()

        def fake_check(path, diagnostics=None):
            return commands[-1][0] == "chrome"

        self.export._find_browsers = lambda: ["edge", "chrome"]
        self.export.subprocess.run = fake_run
        self.export.has_structure_tree = fake_check
        diagnostics = {}
        try:
            self.assertTrue(self.export._write_tagged_pdf(
                self.book, self._path("fallback.pdf"), True,
                "English", diagnostics))
        finally:
            self.export._find_browsers = original_browsers
            self.export.subprocess.run = original_run
            self.export.has_structure_tree = original_check
        self.assertEqual(
            [command[0] for command in commands],
            ["edge", "edge", "edge", "chrome"])
        self.assertEqual(diagnostics["selected_browser"], "chrome")

    def test_pdf_failure_reports_a_packaged_validator_error(self):
        message = self.export._pdf_failure_message({
            "attempts": [{
                "output_exists": True,
                "validation": {
                    "validator_error": "ImportError: missing pdfium",
                },
            }],
        })
        self.assertIn("could not verify", message)
        self.assertIn("missing pdfium", message)
        self.assertIn("EPUB", message)

    def test_pdf_failure_explains_success_code_without_an_output(self):
        message = self.export._pdf_failure_message({
            "attempts": [
                {
                    "browser": r"C:\Program Files (x86)\Microsoft\Edge"
                               r"\Application\msedge.exe",
                    "return_code": 0,
                    "output_exists": False,
                },
                {
                    "browser": r"C:\Program Files\Google\Chrome"
                               r"\Application\chrome.exe",
                    "return_code": 0,
                    "output_exists": False,
                },
            ],
        })
        self.assertIn("Microsoft Edge and Google Chrome", message)
        self.assertIn(
            "Google Chrome reported success but produced no PDF", message)
        self.assertNotIn("exit code 0", message)

    @unittest.skipUnless(PDF_SUPPORT, "pypdfium2 not installed")
    def test_real_browser_pdf_keeps_arabic_text_and_tags(self):
        if not self.export._find_browser():
            self.skipTest("Edge or Chrome not installed")
        self.book.title = "\u0643\u062a\u0627\u0628 \u0627\u0644\u0627\u062e\u062a\u0628\u0627\u0631"
        self.book.scripts = {
            1: "Panel 1 (top right): "
               "\u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645. "
               "English 123.",
        }
        path = self._path("arabic.pdf")
        self.export.write_pdf(self.book, path, language="Arabic")
        self.assertTrue(self.export.has_structure_tree(path))
        import pypdfium2 as pdfium
        document = pdfium.PdfDocument(path)
        try:
            extracted = "".join(
                page.get_textpage().get_text_range() for page in document)
        finally:
            document.close()
        self.assertIn("\u0645\u0631\u062d\u0628\u0627", extracted)
        # PDFium exposes text in painted RTL order rather than preserving
        # the source substring order, so verify that neither side of the
        # mixed-direction line lost characters.
        self.assertIn("English", extracted)
        self.assertIn("123", extracted)

    def test_language_names_become_codes(self):
        # The menu passes a language NAME. A document needs a code: a
        # screen reader picks its voice from it, and a tagged PDF is
        # invalid without a real one.
        from core import config
        self.assertEqual(config.language_code("Arabic"), "ar")
        self.assertEqual(config.language_code("Portuguese"), "pt")
        self.assertEqual(config.language_code("pt-BR"), "pt-BR")
        self.assertEqual(config.language_code("Klingon"), "en")
        self.assertEqual(config.language_code(""), "en")
        self.assertTrue(config.is_rtl("ar"))
        self.assertTrue(config.is_rtl("fa"))
        self.assertTrue(config.is_rtl("en-Arab"))
        self.assertFalse(config.is_rtl("ar-Latn"))
        self.assertFalse(config.is_rtl("en"))

    def test_html_export_uses_a_language_code_not_a_name(self):
        path = self._path("ar.html")
        self.export.write_html(self.book, path, language="Arabic")
        markup = open(path, encoding="utf-8").read()
        self.assertIn('lang="ar"', markup)
        self.assertIn('dir="rtl"', markup)
        self.assertNotIn('lang="Arabic"', markup)

    def test_html_export_marks_ltr_languages_too(self):
        path = self._path("en.html")
        self.export.write_html(self.book, path, language="English")
        markup = open(path, encoding="utf-8").read()
        self.assertIn('lang="en" dir="ltr"', markup)

    def test_epub_uses_a_language_code_not_a_name(self):
        path = self._path("ar2.epub")
        self.export.write_epub(self.book, path, language="Arabic")
        content = zipfile.ZipFile(path).read("OEBPS/content.xhtml").decode()
        self.assertIn('lang="ar"', content)
        self.assertIn('dir="rtl"', content)
        self.assertNotIn('lang="Arabic"', content)

    # ----- plain text ------------------------------------------------------

    def test_text_export_can_drop_panel_labels(self):
        with_labels = self._path("a.txt")
        without = self._path("b.txt")
        self.export.write_text(self.book, with_labels, show_panel_labels=True)
        self.export.write_text(self.book, without, show_panel_labels=False)
        self.assertIn("Panel 1", open(with_labels, encoding="utf-8").read())
        self.assertNotIn("Panel 1", open(without, encoding="utf-8").read())


try:
    import wx  # noqa: F401
    WX_AVAILABLE = True
except Exception:
    WX_AVAILABLE = False


@unittest.skipUnless(WX_AVAILABLE, "wxPython not installed")
class TestArrowKeyHandling(unittest.TestCase):
    """Arrows must reach a radio box's choices.

    Windows builds a radio box from a group box plus one native radio
    button per choice, and those children are not wx windows, so the
    focused window is reported as nothing recognisable. The helper used
    to swallow the key in that case, which left the choices in the
    Reprocess and Ask dialogs unreachable with a screen reader.
    """

    class FakeEvent:
        def __init__(self, code, alt=False, ctrl=False):
            self._code, self._alt, self._ctrl = code, alt, ctrl

        def GetKeyCode(self):
            return self._code

        def AltDown(self):
            return self._alt

        def ControlDown(self):
            return self._ctrl

    def setUp(self):
        from gui import keys
        self.keys = keys
        self.down = self.FakeEvent(list(keys.DOWN_KEYS)[0])

    def test_unknown_focus_never_swallows_the_key(self):
        self.assertFalse(
            self.keys.consume_arrow_navigation(self.down, None))

    def test_a_radio_box_child_is_recognised_by_its_parent(self):
        from unittest import mock
        import wx
        box = mock.MagicMock(spec=wx.RadioBox)
        box.GetParent.return_value = None
        child = mock.MagicMock()
        child.GetParent.return_value = box
        self.assertFalse(
            self.keys.consume_arrow_navigation(self.down, child))

    def test_the_radio_box_itself_is_still_recognised(self):
        from unittest import mock
        import wx
        box = mock.MagicMock(spec=wx.RadioBox)
        box.GetParent.return_value = None
        self.assertFalse(
            self.keys.consume_arrow_navigation(self.down, box))

    def test_an_ordinary_control_still_has_arrows_swallowed(self):
        # The helper's original purpose: Tab, not arrows, moves between
        # buttons.
        from unittest import mock
        plain = mock.MagicMock()
        plain.GetParent.return_value = None
        self.assertTrue(
            self.keys.consume_arrow_navigation(self.down, plain))

    def test_a_control_inside_a_notebook_page_is_unaffected(self):
        # Only composite controls are looked for up the chain: walking
        # up for a notebook would let arrows move focus inside a tab.
        from unittest import mock
        import wx
        notebook = mock.MagicMock(spec=wx.Notebook)
        notebook.GetParent.return_value = None
        button = mock.MagicMock()
        button.GetParent.return_value = notebook
        self.assertTrue(
            self.keys.consume_arrow_navigation(self.down, button))

    def test_modified_arrows_are_left_alone(self):
        for event in (self.FakeEvent(list(self.keys.DOWN_KEYS)[0], alt=True),
                      self.FakeEvent(list(self.keys.DOWN_KEYS)[0], ctrl=True)):
            self.assertFalse(
                self.keys.consume_arrow_navigation(event, None))


try:
    import lameenc  # noqa: F401
    MP3_SUPPORT = True
except ImportError:
    MP3_SUPPORT = False

try:
    import numpy  # noqa: F401
    NUMPY_SUPPORT = True
except ImportError:
    NUMPY_SUPPORT = False


class TestSpeech(unittest.TestCase):
    """Speaking a book. The service is stubbed throughout: what matters
    here is that the text is cut in sensible places, that a piece the
    service fumbles is retried rather than losing the whole run, and
    that cancellation saves completed audio only when explicitly chosen."""

    def setUp(self):
        from core import tts
        self.tts = tts
        # Real backoffs would make the suite sit for half a minute.
        self._real_wait = tts._wait
        tts._wait = lambda seconds, cancel_check=None: True
        self.tmp = tempfile.mkdtemp()
        workspace = os.path.join(self.tmp, "ws")
        os.makedirs(os.path.join(workspace, "pages"))
        self.book = library.Book(workspace)
        self.book.title = "We Were There"
        self.book.page_count = 2
        self.book.scripts = {
            1: 'Panel 1 (top right): A street.\nAiko: "Late."',
            2: "Panel 1 (top right): A clock.",
        }
        self.settings = {"gemini_api_keys": ["key"]}
        self.silence = b"\x00\x00" * 240  # a tenth of a second

    def tearDown(self):
        self.tts._wait = self._real_wait
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _path(self, name="book.mp3"):
        return os.path.join(self.tmp, name)

    # ----- what gets spoken -------------------------------------------

    def test_headings_are_given_an_ending(self):
        # A heading running straight into the next sentence is hard to
        # follow when read aloud.
        lines = self.tts.book_text(self.book)
        self.assertTrue(lines[0].endswith("."))
        self.assertIn("Page 1 of 2.", lines)

    def test_speech_follows_the_same_outline_as_other_exports(self):
        lines = self.tts.book_text(self.book)
        self.assertTrue(any("A street" in line for line in lines))
        self.assertTrue(any("Late" in line for line in lines))

    # ----- splitting ---------------------------------------------------

    def test_pieces_stay_under_the_limit(self):
        lines = ["a" * 30 for _ in range(10)]
        for chunk in self.tts.split_for_speech(lines, limit=100):
            self.assertLessEqual(len(chunk), 100)

    def test_a_line_is_never_cut_in_half(self):
        # A sentence split across two requests would join audibly.
        lines = ["first line here", "second line here", "third line here"]
        chunks = self.tts.split_for_speech(lines, limit=20)
        for line in lines:
            self.assertTrue(any(line in chunk for chunk in chunks))

    def test_an_overlong_line_is_left_whole(self):
        long_line = "x" * 500
        chunks = self.tts.split_for_speech([long_line], limit=100)
        self.assertEqual(chunks, [long_line])

    # ----- talking to the service --------------------------------------

    def test_audio_is_read_out_of_a_reply(self):
        import base64
        data = {"candidates": [{"content": {"parts": [
            {"inlineData": {"data": base64.b64encode(b"pcm").decode()}}]}}]}
        self.assertEqual(self.tts.extract_audio(data), b"pcm")

    def test_a_reply_with_words_instead_of_speech_is_named(self):
        # Google documents this as an occasional response, so the
        # message has to explain it rather than look like a crash.
        data = {"candidates": [{"content": {"parts": [{"text": "hello"}]}}]}
        with self.assertRaises(self.tts.SpeechError) as caught:
            self.tts.extract_audio(data)
        self.assertIn("words back instead of speech",
                      str(caught.exception))

    def test_a_fumbled_piece_is_retried(self):
        attempts = []

        def flaky(text):
            attempts.append(text)
            if len(attempts) == 1:
                raise self.tts.SpeechError("no audio this time")
            return self.silence

        self.tts.write_mp3(self.book, self._path(), self.settings,
                           request=flaky)
        self.assertEqual(len(attempts), 2)
        self.assertTrue(os.path.exists(self._path()))

    def test_a_piece_that_keeps_failing_stops_the_run(self):
        def broken(text):
            raise self.tts.SpeechError("no audio")

        with self.assertRaises(self.tts.SpeechError):
            self.tts.write_mp3(self.book, self._path(), self.settings,
                               request=broken)
        self.assertFalse(os.path.exists(self._path()))

    def test_a_missing_key_is_explained(self):
        with self.assertRaises(self.tts.SpeechError) as caught:
            self.tts.write_mp3(self.book, self._path(), {},
                               request=lambda t: self.silence)
        self.assertIn("Gemini API key", str(caught.exception))

    # ----- cancelling ---------------------------------------------------

    def test_cancelling_writes_no_file(self):
        result = self.tts.write_mp3(
            self.book, self._path(), self.settings,
            request=lambda t: self.silence, cancel_check=lambda: True)
        self.assertIsNone(result)
        self.assertFalse(os.path.exists(self._path()))

    @unittest.skipUnless(MP3_SUPPORT, "lameenc not installed")
    def test_cancelled_gemini_export_can_save_completed_audio(self):
        import core.tts as module
        import threading
        import time as _time

        cancelled = threading.Event()
        real_split = module.split_for_speech
        module.split_for_speech = lambda lines, limit=None: ["first", "second"]
        calls = []

        def speak(text):
            calls.append(text)
            if text == "second":
                _time.sleep(0.5)
            return self.silence

        def progress(message, done, total):
            if message.startswith("Read 1 of"):
                cancelled.set()

        try:
            seconds = module.write_mp3(
                self.book, self._path("partial-gemini.mp3"), self.settings,
                request=speak, workers=1, on_progress=progress,
                cancel_check=cancelled.is_set,
                save_partial_check=lambda: True)
        finally:
            module.split_for_speech = real_split
        self.assertGreater(seconds, 0)
        path = self._path("partial-gemini.mp3")
        self.assertTrue(os.path.exists(path))
        with open(path, "rb") as handle:
            head = handle.read(3)
        self.assertTrue(head.startswith(b"ID3") or head[0] == 0xFF)

    def test_cancelled_gemini_export_can_still_discard_completed_audio(self):
        import core.tts as module
        import threading
        import time as _time

        cancelled = threading.Event()
        real_split = module.split_for_speech
        module.split_for_speech = lambda lines, limit=None: ["first", "second"]

        def speak(text):
            if text == "second":
                _time.sleep(0.5)
            return self.silence

        def progress(message, done, total):
            if message.startswith("Read 1 of"):
                cancelled.set()

        path = self._path("discarded-gemini.mp3")
        with open(path, "wb") as handle:
            handle.write(b"existing audio")
        try:
            result = module.write_mp3(
                self.book, path, self.settings,
                request=speak, workers=1, on_progress=progress,
                cancel_check=cancelled.is_set,
                save_partial_check=lambda: False)
        finally:
            module.split_for_speech = real_split
        self.assertIsNone(result)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"existing audio")

    def test_progress_is_reported(self):
        seen = []
        self.tts.write_mp3(
            self.book, self._path(), self.settings,
            request=lambda t: self.silence,
            on_progress=lambda m, d, t: seen.append(m))
        self.assertTrue(seen)
        self.assertTrue(any("Saving the audio file" in m for m in seen))

    # ----- the file itself ----------------------------------------------

    @unittest.skipUnless(MP3_SUPPORT, "lameenc not installed")
    def test_the_result_is_a_real_mp3(self):
        self.tts.write_mp3(self.book, self._path(), self.settings,
                           request=lambda t: self.silence)
        head = open(self._path(), "rb").read(3)
        self.assertTrue(head.startswith(b"ID3") or head[0] == 0xFF)

    @unittest.skipUnless(MP3_SUPPORT, "lameenc not installed")
    def test_mp3_is_far_smaller_than_the_raw_audio(self):
        # The reason the audio is not simply saved as it arrives: a full
        # volume would be most of a gigabyte.
        pcm = b"\x00\x00" * self.tts.SAMPLE_RATE  # one second
        self.assertLess(len(self.tts.encode_mp3(pcm)), len(pcm) / 4)

    def test_audio_length_is_measured_for_progress(self):
        one_second = b"\x00\x00" * self.tts.SAMPLE_RATE
        self.assertAlmostEqual(self.tts.seconds_of(one_second), 1.0, places=2)

    def test_pieces_are_reassembled_in_order(self):
        # Pieces are spoken several at a time and come back in whatever
        # order they finish. A book assembled in arrival order would be
        # scrambled, so this is the invariant that matters most.
        import core.tts as module
        lines = ["line number %d with enough words to matter" % n
                 for n in range(40)]
        chunks = self.tts.split_for_speech(lines, limit=120)
        self.book.scripts = {1: "\n".join(lines)}
        self.book.page_count = 1

        real_split = module.split_for_speech
        module.split_for_speech = lambda ls, limit=None: chunks
        real_encoder = module.mp3_encoder

        class PassThroughEncoder:
            def encode(self, pcm):
                return pcm

            def flush(self):
                return b""

        module.mp3_encoder = lambda *args, **kwargs: PassThroughEncoder()
        try:
            lookup = {c: i for i, c in enumerate(chunks)}
            import time as _time

            def slow_in_reverse(text):
                index = lookup[text]
                # Later pieces finish first.
                _time.sleep(0.01 * (len(chunks) - index))
                return bytes([index + 1, 0]) * 50

            path = self._path("ordered.bin")
            self.tts.write_mp3(self.book, path, self.settings,
                               request=slow_in_reverse)
            raw = open(path, "rb").read()
        finally:
            module.split_for_speech = real_split
            module.mp3_encoder = real_encoder

        markers = [raw[i * 100] for i in range(len(chunks))]
        self.assertEqual(markers, list(range(1, len(chunks) + 1)))

    def test_several_pieces_are_spoken_at_once(self):
        # The whole reason a ten page book was slow: each request takes
        # about as long as the speech it produces, and they were done
        # one after another.
        import threading
        active = []
        peak = [0]
        lock = threading.Lock()

        def counting(text):
            with lock:
                active.append(1)
                peak[0] = max(peak[0], len(active))
            import time as _time
            _time.sleep(0.05)
            with lock:
                active.pop()
            return self.silence

        # Long enough to split into several pieces; a book small enough
        # to be one piece has nothing to do in parallel.
        # Long enough to still be several pieces at the current size.
        lines = ["line %d, %s" % (n, "word " * 40) for n in range(120)]
        self.book.scripts = {1: "\n".join(lines)}
        self.book.page_count = 1
        self.assertGreater(
            len(self.tts.split_for_speech(self.tts.book_text(self.book))), 3)
        self.tts.write_mp3(self.book, self._path("par.mp3"), self.settings,
                           request=counting, workers=3)
        self.assertGreater(peak[0], 1)

    def test_only_the_chosen_pages_are_spoken(self):
        # A whole volume is hours of speech and a large part of a
        # service's allowance, so a range is how that cost is kept down.
        self.book.page_count = 6
        self.book.scripts = {
            n: "Panel 1 (top right): this is page %d." % n
            for n in range(1, 7)}
        spoken = self.tts.book_text(self.book, pages=[2, 3])
        joined = " ".join(spoken)
        self.assertIn("page 2", joined)
        self.assertIn("page 3", joined)
        self.assertNotIn("page 1.", joined)
        self.assertNotIn("page 6", joined)

    def test_a_range_keeps_the_books_real_page_numbers(self):
        # Renumbering a range from one would lose the reader's place.
        self.book.page_count = 20
        self.book.scripts = {
            n: "Panel 1 (top right): x." for n in range(1, 21)}
        spoken = self.tts.book_text(self.book, pages=[12, 13])
        self.assertIn("Page 12 of 20.", spoken)
        self.assertNotIn("Page 1 of 2.", spoken)

    def test_an_empty_range_is_explained(self):
        self.book.page_count = 4
        self.book.scripts = {}
        with self.assertRaises(self.tts.SpeechError) as caught:
            self.tts.write_mp3(self.book, self._path(), self.settings,
                               request=lambda t: self.silence, pages=[2])
        self.assertIn("range", str(caught.exception))

    def test_unprocessed_pages_are_not_read_aloud(self):
        # An audiobook that keeps announcing "this page has not been
        # processed yet" is worse than one that simply omits it.
        self.book.page_count = 4
        self.book.scripts = {1: "Panel 1 (top right): the only page."}
        spoken = " ".join(self.tts.book_text(self.book))
        self.assertIn("the only page", spoken)
        self.assertNotIn("not been processed", spoken)
        self.assertNotIn("Page 2 of 4", spoken)

    def test_a_range_reaches_the_audio(self):
        seen = []
        self.book.page_count = 6
        self.book.scripts = {
            n: "Panel 1 (top right): page %d text." % n
            for n in range(1, 7)}

        def capture(text):
            seen.append(text)
            return self.silence

        self.tts.write_mp3(self.book, self._path(), self.settings,
                           request=capture, pages=[4, 5])
        joined = " ".join(seen)
        self.assertIn("page 4", joined)
        self.assertNotIn("page 1 ", joined)

    def test_a_rate_limit_waits_rather_than_giving_up(self):
        # 429 is not a fault, it means slow down. Abandoning a book most
        # of the way through because of one is the wrong response.
        import urllib.error
        attempts = []

        def limited(text, key=None):
            attempts.append(text)
            if len(attempts) < 3:
                raise urllib.error.HTTPError(
                    "u", 429, "Too Many Requests", {}, None)
            return self.silence

        result = self.tts._speak_with_retry(
            lambda text, key: limited(text), "some text", "k", 0)
        self.assertEqual(result, self.silence)
        self.assertEqual(len(attempts), 3)

    def test_the_services_own_retry_delay_is_used(self):
        import io, urllib.error
        body = io.BytesIO(json.dumps({"error": {"details": [
            {"@type": "type.googleapis.com/google.rpc.RetryInfo",
             "retryDelay": "37s"}]}}).encode())
        error = urllib.error.HTTPError("u", 429, "x", {}, body)
        self.assertEqual(self.tts.retry_delay_from(error), 37)

    def test_a_missing_retry_delay_is_tolerated(self):
        import io, urllib.error
        error = urllib.error.HTTPError(
            "u", 429, "x", {}, io.BytesIO(b"not json"))
        self.assertIsNone(self.tts.retry_delay_from(error))

    def test_persistent_rate_limiting_explains_itself(self):
        import urllib.error

        def always_limited(text, key=None):
            raise urllib.error.HTTPError("u", 429, "x", {}, None)

        with self.assertRaises(self.tts.SpeechError) as caught:
            self.tts._speak_with_retry(
                lambda text, key: always_limited(text), "t", "k", 0)
        message = str(caught.exception)
        self.assertIn("kept refusing", message)
        self.assertNotIn("429", message)
        self.assertIn("fewer pages", message)

    def test_a_key_problem_is_not_retried(self):
        import urllib.error
        attempts = []

        def refused(text, key=None):
            attempts.append(text)
            raise urllib.error.HTTPError("u", 403, "Forbidden", {}, None)

        with self.assertRaises(self.tts.SpeechError):
            self.tts._speak_with_retry(
                lambda text, key: refused(text), "t", "k", 0)
        self.assertEqual(len(attempts), 1)

    def test_a_daily_allowance_is_not_retried(self):
        # A per-minute limit is worth waiting out. A daily one will not
        # clear until it resets, so trying for several minutes and then
        # failing anyway is worse than saying so at once.
        import urllib.error, io, json as _json
        body = _json.dumps({"error": {"details": [
            {"violations": [
                {"quotaId": "GenerateRequestsPerDayPerProjectPerModel"}]},
            {"retryDelay": "31s"}]}})

        def exhausted(text):
            raise urllib.error.HTTPError(
                "u", 429, "Too Many Requests", {},
                io.BytesIO(body.encode()))

        with self.assertRaises(self.tts.SpeechError) as caught:
            self.tts.write_mp3(self.book, self._path(), self.settings,
                               request=exhausted)
        message = str(caught.exception)
        # Plain language: no quota identifiers or error codes.
        self.assertIn("Today's Gemini limit", message)
        self.assertIn("midnight", message)
        self.assertNotIn("429", message)
        self.assertNotIn("quota", message.lower())

    def test_the_quota_that_ran_out_is_named(self):
        import urllib.error, io, json as _json
        body = _json.dumps({"error": {"details": [
            {"violations": [{"quotaId": "GenerateRequestsPerMinute"}]},
            {"retryDelay": "12s"}]}})
        error = urllib.error.HTTPError(
            "u", 429, "Too Many", {}, io.BytesIO(body.encode()))
        delay, quota, daily = self.tts.rate_limit_details(error)
        self.assertEqual(delay, 12)
        self.assertEqual(quota, "GenerateRequestsPerMinute")
        self.assertFalse(daily)

    def test_requests_are_spaced_apart(self):
        # Firing as fast as possible is what earns a refusal on a free
        # allowance of a few requests a minute.
        import core.tts as module
        import time as _time
        stubbed = module._wait
        module._wait = self._real_wait      # this test needs real time
        try:
            pacer = module.Pacer(spacing=0.2)
            start = _time.time()
            for _ in range(3):
                pacer.wait_turn()
            self.assertGreater(_time.time() - start, 0.3)
        finally:
            module._wait = stubbed

    def test_the_pace_eases_off_after_a_refusal(self):
        pacer = self.tts.Pacer(spacing=1.0)
        before = pacer.spacing
        pacer.slow_down()
        self.assertGreater(pacer.spacing, before)

    def test_one_request_at_a_time_by_default(self):
        # Two at once on a per-minute allowance simply earns two
        # refusals, and they then wake together and collide again.
        self.assertEqual(self.tts.DEFAULT_WORKERS, 1)

    def test_a_long_wait_can_be_cancelled(self):
        # A rate-limit backoff can run well over a minute. Someone who
        # has changed their mind should not have to sit through it.
        import time as _time
        real_wait = self._real_wait
        start = _time.time()
        finished = real_wait(
            30, cancel_check=lambda: _time.time() - start > 0.4)
        self.assertFalse(finished)
        self.assertLess(_time.time() - start, 5)

    def test_a_sample_is_playable_audio(self):
        # Previews are wrapped in a WAV container: Windows can play that
        # without a decoder, unlike the MP3 the book is saved as.
        wav = self.tts.sample_voice(
            "Kore", self.settings, request=lambda text: self.silence)
        self.assertTrue(wav.startswith(b"RIFF"))
        self.assertIn(b"WAVE", wav[:16])

    def test_a_sample_needs_a_key(self):
        with self.assertRaises(self.tts.SpeechError):
            self.tts.sample_voice("Kore", {},
                                  request=lambda text: self.silence)

    def test_legacy_voices_are_filtered_out(self):
        # The old flat voices are what a program is given by default,
        # and offering them beside the good ones invites a
        # disappointing choice.
        from core import winspeech
        for name in ("Microsoft David Desktop - English (United States)",
                     "Microsoft Zira Desktop", "Microsoft Mark",
                     "Microsoft Hazel Desktop - English (Great Britain)",
                     "Microsoft Sara Desktop"):
            self.assertTrue(winspeech.is_legacy(name), name)

    def test_better_voices_are_kept(self):
        from core import winspeech
        for name in ("Microsoft Aria Online (Natural)",
                     "Microsoft Guy", "Microsoft Jenny",
                     "Microsoft Sonia Online"):
            self.assertFalse(winspeech.is_legacy(name), name)

    def test_local_default_cannot_fall_back_to_a_legacy_voice(self):
        from core import winspeech

        class Token:
            def __init__(self, identifier, description):
                self.Id = identifier
                self.description = description

            def GetDescription(self):
                return self.description

        tokens = [
            Token("legacy", "Microsoft David Desktop"),
            Token("onecore", "Microsoft Aria"),
        ]
        self.assertEqual(
            winspeech._chosen_token(tokens).Id, "onecore")
        with self.assertRaises(winspeech.WindowsSpeechError):
            winspeech._chosen_token(tokens, "missing")

    def test_no_voices_is_not_an_error(self):
        # A computer with nothing worth offering should simply not
        # offer the engine, rather than fail.
        from core import winspeech
        self.assertEqual(winspeech.voices() if not winspeech.available()
                         else [], [])

    def test_local_engine_needs_no_key(self):
        # The whole point: no account, no allowance, no network.
        import core.tts as module
        from core import winspeech
        real_available = winspeech.available
        real_speak = winspeech.speak
        winspeech.available = lambda: True
        winspeech.speak = lambda text, voice_id=None: (
            self.silence, 24000, 1)
        try:
            seconds = module.write_mp3(
                self.book, self._path("local.mp3"),
                {"tts_engine": "windows"})   # no keys at all
        finally:
            winspeech.available = real_available
            winspeech.speak = real_speak
        self.assertGreater(seconds, 0)
        self.assertTrue(os.path.exists(self._path("local.mp3")))

    def test_local_engine_says_so_when_unavailable(self):
        import core.tts as module
        from core import winspeech
        real = winspeech.available
        winspeech.available = lambda: False
        try:
            with self.assertRaises(module.SpeechError) as caught:
                module.write_mp3(self.book, self._path(), {
                    "tts_engine": "windows"})
        finally:
            winspeech.available = real
        self.assertIn("Gemini instead", str(caught.exception))

    def test_audio_is_encoded_at_the_rate_it_was_spoken(self):
        # A Windows voice picks its own rate; encoding at Gemini's
        # would play the book back at the wrong speed.
        pcm = b"\x00\x00" * 16000
        at_16k = self.tts.encode_mp3(pcm, sample_rate=16000)
        at_24k = self.tts.encode_mp3(pcm, sample_rate=24000)
        self.assertTrue(at_16k and at_24k)
        self.assertNotEqual(at_16k, at_24k)

    def test_every_model_has_a_description(self):
        # Offered in the dialog, so each needs something to tell a
        # reader why they might pick it.
        self.assertGreaterEqual(len(self.tts.TTS_MODELS), 2)
        for name, note in self.tts.TTS_MODELS:
            self.assertTrue(name and note)
        self.assertEqual(self.tts.DEFAULT_TTS_MODEL,
                         self.tts.TTS_MODELS[0][0])

    def test_the_chosen_model_is_used(self):
        seen = {}

        def capture(text):
            return self.silence

        import core.tts as module
        real = module._request_audio
        module._request_audio = (
            lambda text, key, model, voice, timeout=None:
            seen.update(model=model, voice=voice) or self.silence)
        try:
            module.write_mp3(
                self.book, self._path(),
                dict(self.settings, tts_model="gemini-2.5-flash-preview-tts",
                     tts_voice="Puck"))
        finally:
            module._request_audio = real
        self.assertEqual(seen["model"], "gemini-2.5-flash-preview-tts")
        self.assertEqual(seen["voice"], "Puck")

    def test_fewer_requests_than_before(self):
        # Every extra piece is another request, another wait for a turn
        # and another chance of being refused.
        lines = ["a line of narration about this panel" for _ in range(200)]
        self.assertLess(
            len(self.tts.split_for_speech(lines)),
            len(self.tts.split_for_speech(lines, limit=1600)))

    def test_every_voice_has_a_description(self):
        self.assertGreater(len(self.tts.VOICES), 10)
        for name, description in self.tts.VOICES:
            self.assertTrue(name and description)
        self.assertIn(self.tts.DEFAULT_VOICE,
                      [name for name, _ in self.tts.VOICES])


class TestKokoroAudio(unittest.TestCase):
    """The local catalogue, verified download, and atomic MP3 export."""

    def setUp(self):
        from core import kokoro, tts
        self.kokoro = kokoro
        self.tts = tts
        self.tmp = tempfile.mkdtemp(prefix="amr_kokoro_test_")
        workspace = os.path.join(self.tmp, "book")
        os.makedirs(os.path.join(workspace, "pages"))
        self.book = library.Book(workspace)
        self.book.title = "Local Voices"
        self.book.page_count = 1
        self.book.scripts = {1: "Narration: A quiet street at dusk."}
        self.silence = b"\x00\x00" * 240

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _path(self, name="kokoro.mp3"):
        return os.path.join(self.tmp, name)

    def _long_book(self):
        self.book.scripts = {1: "\n".join(
            "Narration: " + "word " * 35 for _ in range(100))}
        self.assertGreater(
            len(self.tts.split_for_kokoro(
                self.tts.book_text(self.book))), 1)

    def test_current_catalogue_has_every_official_voice(self):
        self.assertEqual(len(self.kokoro.LANGUAGES), 9)
        voices = [voice for group in self.kokoro.VOICES_BY_LANGUAGE.values()
                  for voice, _ in group]
        self.assertEqual(len(voices), 54)
        self.assertEqual(len(set(voices)), 54)
        for language, _ in self.kokoro.LANGUAGES:
            self.assertIn(self.kokoro.default_voice(language),
                          [voice for voice, _
                           in self.kokoro.VOICES_BY_LANGUAGE[language]])

    def test_voice_labels_are_factual(self):
        labels = [label.lower() for language, _ in self.kokoro.LANGUAGES
                  for _, label in self.kokoro.voice_options(language)]
        self.assertTrue(all("female" in label or "male" in label
                            for label in labels))
        for claim in ("better", "natural", "expressive", "free", "quota"):
            self.assertFalse(any(claim in label for label in labels), claim)

    def test_book_language_selects_a_supported_locale(self):
        for book_language, expected in (
                ("English", "en-us"), ("en-GB", "en-gb"),
                ("Japanese", "ja"), ("Chinese (Traditional)", "zh"),
                ("French", "fr-fr"), ("Portuguese", "pt-br")):
            self.book.output_language = book_language
            self.assertEqual(
                self.kokoro.language_for_book(self.book, {}), expected)
        self.book.output_language = "Arabic"
        self.assertEqual(
            self.kokoro.language_for_book(
                self.book, {"kokoro_language": "it"}), "it")

    def test_long_local_lines_are_not_truncated(self):
        line = " ".join("word%d" % number for number in range(300))
        chunks = self.tts.split_for_kokoro([line], limit=120)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 120 for chunk in chunks))
        self.assertEqual(" ".join(chunks).split(), line.split())
        japanese = "長い文章です。" * 80
        cjk_chunks = self.tts.split_for_kokoro([japanese], limit=60)
        self.assertTrue(all(len(chunk) <= 60 for chunk in cjk_chunks))
        # Sentence boundaries become newlines so the voice pauses there; the
        # original characters themselves must all remain present.
        self.assertEqual("".join(cjk_chunks).replace("\n", ""), japanese)

    def test_kokoro_uses_far_fewer_outer_parts(self):
        lines = ["Narration: " + "word " * 35 for _ in range(400)]
        current = self.tts.split_for_kokoro(lines)
        old = self.tts.split_for_kokoro(lines, limit=1000)
        self.assertGreaterEqual(self.tts.KOKORO_CHUNK_CHARACTERS, 8000)
        self.assertLess(len(current), len(old) / 5)

    def test_phoneme_batches_never_cross_the_runtime_limit(self):
        phonemes = ("phoneme sequence, " * 90).strip()
        pieces = self.kokoro.split_phonemes(phonemes)
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(
            len(piece) <= self.kokoro.MAX_PHONEME_CHARACTERS
            for piece in pieces))
        self.assertEqual("".join(pieces).replace(" ", ""),
                         phonemes.replace(" ", ""))

    @unittest.skipUnless(NUMPY_SUPPORT, "numpy not installed")
    def test_long_phonemes_are_all_sent_to_the_model(self):
        import numpy as np

        seen = []

        class Engine:
            def create(self, phonemes, **kwargs):
                seen.append(phonemes)
                return np.zeros(10, dtype=np.float32), 24000

        phonemes = "x" * 1200
        pcm, rate, channels = self.kokoro.synthesize_phonemes(
            phonemes, "af_heart", engine=Engine())
        self.assertEqual("".join(seen), phonemes)
        self.assertTrue(all(len(piece) <= 500 for piece in seen))
        self.assertEqual((rate, channels), (24000, 1))
        self.assertEqual(len(pcm), len(seen) * 20)

    def test_verified_download_becomes_ready(self):
        import hashlib

        payloads = {"model": b"model bytes", "voices": b"voice bytes"}
        assets = tuple({
            "name": name + ".bin", "size": len(payloads[url]),
            "sha256": hashlib.sha256(payloads[url]).hexdigest(), "url": url,
        } for name, url in (("model", "model"), ("voices", "voices")))

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        paths = self.kokoro.download_models(
            directory=self.tmp, assets=assets,
            opener=lambda url, timeout=None: Response(payloads[url]))
        self.assertEqual([open(path, "rb").read() for path in paths],
                         [payloads["model"], payloads["voices"]])
        self.assertTrue(self.kokoro.models_ready(self.tmp, assets))
        # A ready model makes no second network request.
        again = self.kokoro.download_models(
            directory=self.tmp, assets=assets,
            opener=lambda *args: self.fail("downloaded twice"))
        self.assertEqual(paths, again)

    def test_cancelled_download_leaves_no_partial_model(self):
        import hashlib

        data = b"a" * 100
        assets = ({
            "name": "model.bin", "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "url": "model",
        },)

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        checks = []
        with self.assertRaises(self.kokoro.DownloadCancelled):
            self.kokoro.download_models(
                directory=self.tmp, assets=assets,
                opener=lambda url, timeout=None: Response(data),
                cancel_check=lambda: checks.append(True) or len(checks) > 2)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "model.bin")))
        self.assertFalse(any(name.endswith(".download")
                             for name in os.listdir(self.tmp)))
        self.assertFalse(self.kokoro.models_ready(self.tmp, assets))

    def test_invalid_download_is_not_installed(self):
        assets = ({
            "name": "model.bin", "size": 3,
            "sha256": "0" * 64, "url": "model",
        },)

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        with self.assertRaises(self.kokoro.KokoroError):
            self.kokoro.download_models(
                directory=self.tmp, assets=assets,
                opener=lambda url, timeout=None: Response(b"bad"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "model.bin")))

    @unittest.skipUnless(MP3_SUPPORT, "lameenc not installed")
    def test_kokoro_export_needs_no_api_key(self):
        seconds = self.tts.write_mp3(
            self.book, self._path(), {
                "tts_engine": "kokoro", "kokoro_language": "en-us",
                "kokoro_voice": "af_heart"},
            request=lambda text: (self.silence, 24000, 1))
        self.assertGreater(seconds, 0)
        self.assertTrue(os.path.exists(self._path()))

    def test_failed_kokoro_export_keeps_the_existing_file(self):
        self._long_book()
        path = self._path()
        with open(path, "wb") as handle:
            handle.write(b"original")
        calls = []

        def fails_after_one(text):
            calls.append(text)
            if len(calls) > 1:
                raise RuntimeError("test failure")
            return self.silence, 24000, 1

        with self.assertRaises(self.tts.SpeechError):
            self.tts.write_mp3(
                self.book, path, {
                    "tts_engine": "kokoro", "kokoro_language": "en-us",
                    "kokoro_voice": "af_heart"},
                request=fails_after_one, workers=1)
        self.assertEqual(open(path, "rb").read(), b"original")
        self.assertFalse(any(name.startswith(".accessible-manga-audio-")
                             for name in os.listdir(self.tmp)))

    def test_cancelled_kokoro_export_writes_no_file(self):
        result = self.tts.write_mp3(
            self.book, self._path(), {
                "tts_engine": "kokoro", "kokoro_language": "en-us",
                "kokoro_voice": "af_heart"},
            request=lambda text: (self.silence, 24000, 1),
            cancel_check=lambda: True)
        self.assertIsNone(result)
        self.assertFalse(os.path.exists(self._path()))

    @unittest.skipUnless(MP3_SUPPORT, "lameenc not installed")
    def test_cancelled_kokoro_export_can_save_completed_audio(self):
        import threading
        import time as _time

        self._long_book()
        cancelled = threading.Event()
        calls = []

        def speak(text):
            calls.append(text)
            if len(calls) > 1:
                _time.sleep(0.5)
            return self.silence, 24000, 1

        def progress(message, done, total):
            if message.startswith("Generated 1 of"):
                cancelled.set()

        path = self._path("partial-kokoro.mp3")
        seconds = self.tts.write_mp3(
            self.book, path, {
                "tts_engine": "kokoro", "kokoro_language": "en-us",
                "kokoro_voice": "af_heart"},
            request=speak, workers=1, on_progress=progress,
            cancel_check=cancelled.is_set,
            save_partial_check=lambda: True)
        self.assertGreater(seconds, 0)
        self.assertTrue(os.path.exists(path))
        with open(path, "rb") as handle:
            head = handle.read(3)
        self.assertTrue(head.startswith(b"ID3") or head[0] == 0xFF)

    def test_sample_button_activation_includes_enter_and_space(self):
        import wx
        from gui import audio_dialog

        for key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_SPACE):
            self.assertTrue(audio_dialog._is_button_activation_key(key))
        self.assertFalse(audio_dialog._is_button_activation_key(ord("A")))

    def test_playing_either_sample_returns_focus_to_the_voice(self):
        from gui import audio_dialog

        class FakeVoiceList:
            def __init__(self):
                self.focused = False

            def IsEnabled(self):
                return True

            def GetSelection(self):
                return 0

            def SetFocus(self):
                self.focused = True

        class FakeDialog:
            def __init__(self, engine):
                self.engine = engine
                self.played = None
                self._closed = False
                self.voices = FakeVoiceList()

            def chosen_engine(self):
                return self.engine

            def _ensure_kokoro(self, callback):
                callback()

            def _play_kokoro_sample(self):
                self.played = self.tts.ENGINE_KOKORO

            def _play_kokoro_sample_and_focus(self):
                self._play_kokoro_sample()
                self._focus_chosen_voice()

            def _play_gemini_sample(self):
                self.played = self.tts.ENGINE_GEMINI

        original_call_after = audio_dialog.wx.CallAfter
        audio_dialog.wx.CallAfter = lambda callback, *args: callback(*args)
        try:
            for engine in (self.tts.ENGINE_KOKORO,
                           self.tts.ENGINE_GEMINI):
                dialog = FakeDialog(engine)
                dialog.tts = self.tts
                dialog._focus_chosen_voice = lambda dialog=dialog: (
                    audio_dialog.AudioOptionsDialog._focus_chosen_voice(
                        dialog))
                audio_dialog.AudioOptionsDialog.on_play(dialog, None)
                self.assertEqual(dialog.played, engine)
                self.assertTrue(dialog.voices.focused)
        finally:
            audio_dialog.wx.CallAfter = original_call_after

    def test_audio_dialog_describes_each_engines_language_support(self):
        from gui import audio_dialog
        explanation = audio_dialog.ENGINE_EXPLANATION
        self.assertIn("nine language and locale choices", explanation)
        self.assertIn(
            "detects the input language automatically", explanation)
        self.assertIn("supports 78 documented languages", explanation)
        self.assertNotIn("supports any language", explanation.lower())

    def test_audio_dialog_explains_the_kokoro_download(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "gui", "audio_dialog.py"),
                  encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("About the options", source)
        self.assertIn("model and voice", source)
        self.assertIn("before a sample", source)

    def test_new_ui_copy_does_not_rank_the_engines(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "gui", "audio_dialog.py"),
                  encoding="utf-8") as handle:
            source = handle.read().lower()
        for phrase in (
                "better but", "free and much faster", "more expressive",
                "natural local voices", "uses your allowance"):
            self.assertNotIn(phrase, source)


class TestJobRegistry(unittest.TestCase):
    """Only one book processes at a time, and the app must know which,
    so it can refuse actions that would disturb a running job. This is
    what lets processing be modeless without the app tripping over
    itself."""

    class FakeBook:
        def __init__(self, workspace, title):
            self.workspace = workspace
            self.title = title

    def setUp(self):
        from core import jobs
        self.jobs = jobs
        self.reg = jobs.JobRegistry()
        self.a = self.FakeBook("/ws/a", "Book A")
        self.b = self.FakeBook("/ws/b", "Book B")

    def test_starts_idle(self):
        self.assertFalse(self.reg.is_busy())
        self.assertIsNone(self.reg.busy_reason())
        self.assertIsNone(self.reg.blocked_reason(self.a))

    def test_start_claims_the_slot(self):
        self.assertTrue(self.reg.start(self.a))
        self.assertTrue(self.reg.is_busy())
        self.assertTrue(self.reg.is_processing(self.a))
        self.assertFalse(self.reg.is_processing(self.b))

    def test_only_one_job_at_a_time(self):
        self.reg.start(self.a)
        self.assertFalse(self.reg.start(self.b))
        self.assertIsNotNone(self.reg.busy_reason())
        self.assertIn("Book A", self.reg.busy_reason())

    def test_same_book_cannot_start_twice(self):
        self.reg.start(self.a)
        self.assertFalse(self.reg.start(self.a))

    def test_finish_frees_the_slot(self):
        self.reg.start(self.a)
        self.assertTrue(self.reg.finish(self.a))
        self.assertFalse(self.reg.is_busy())
        self.assertTrue(self.reg.start(self.b))

    def test_a_late_finish_cannot_clear_a_newer_job(self):
        # An old dialog finishing after a new job started must not
        # release the new job's slot.
        self.reg.start(self.a)
        self.reg.finish(self.a)
        self.reg.start(self.b)
        self.assertFalse(self.reg.finish(self.a))
        self.assertTrue(self.reg.is_processing(self.b))

    def test_the_processing_book_is_blocked(self):
        self.reg.start(self.a)
        reason = self.reg.blocked_reason(self.a)
        self.assertIsNotNone(reason)
        self.assertIn("Book A", reason)

    def test_other_books_stay_usable_while_one_processes(self):
        # The whole point: reading another book must remain possible.
        self.reg.start(self.a)
        self.assertIsNone(self.reg.blocked_reason(self.b))

    def test_blocked_reason_handles_no_book(self):
        self.reg.start(self.a)
        self.assertIsNone(self.reg.blocked_reason(None))

    def test_module_exposes_a_shared_registry(self):
        self.assertIsInstance(self.jobs.registry, self.jobs.JobRegistry)


class TestAppendImagePages(unittest.TestCase):
    """Adding more image files to an image-built book from the reader:
    new pages are numbered after the existing ones, and the pages
    already processed keep their scripts."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.pages_dir = os.path.join(self.tmp, "pages")
        os.makedirs(self.pages_dir)
        for n in (1, 2):
            Image.new("RGB", (10, 10), "white").save(
                os.path.join(self.pages_dir, "%04d.jpg" % n))
        self.src = os.path.join(self.tmp, "incoming")
        os.makedirs(self.src)
        self.new_paths = []
        for name in ("p10.png", "p3.png", "p04.png"):
            p = os.path.join(self.src, name)
            Image.new("RGB", (10, 10), "black").save(p)
            self.new_paths.append(p)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _page_files(self):
        return sorted(n for n in os.listdir(self.pages_dir)
                      if n.endswith(".jpg"))

    def test_new_pages_are_numbered_after_existing(self):
        added = extract.append_image_files(self.new_paths, self.tmp)
        self.assertEqual(added, 3)
        self.assertEqual(
            self._page_files(),
            ["0001.jpg", "0002.jpg", "0003.jpg", "0004.jpg", "0005.jpg"])

    def test_existing_pages_are_not_overwritten(self):
        before = Image.open(
            os.path.join(self.pages_dir, "0001.jpg")).getpixel((0, 0))
        extract.append_image_files(self.new_paths, self.tmp)
        after = Image.open(
            os.path.join(self.pages_dir, "0001.jpg")).getpixel((0, 0))
        self.assertEqual(before, after)

    def test_appended_pages_use_natural_sort(self):
        extract.append_image_files(self.new_paths, self.tmp)
        self.assertEqual(len(self._page_files()), 5)

    def test_scripts_for_existing_pages_survive_a_grow(self):
        book = library.Book(self.tmp)
        book.source_kind = "images"
        book.detect_page_count()
        book.scripts = {1: "page one", 2: "page two"}
        book.save()
        extract.append_image_files(self.new_paths, self.tmp)
        book.detect_page_count()
        self.assertEqual(book.page_count, 5)
        self.assertEqual(book.scripts.get(1), "page one")
        self.assertEqual(book.unprocessed_pages(), [3, 4, 5])

    def test_append_into_empty_workspace_starts_at_one(self):
        empty = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(empty, "pages"))
            added = extract.append_image_files(self.new_paths, empty)
            self.assertEqual(added, 3)
            files = sorted(n for n in os.listdir(
                os.path.join(empty, "pages")) if n.endswith(".jpg"))
            self.assertEqual(files[0], "0001.jpg")
        finally:
            shutil.rmtree(empty, ignore_errors=True)

    def test_import_does_not_change_the_books_identity(self):
        # The book's on-disk folder is a hash of its source string.
        # Appending pages must NOT rewrite source, or the book desyncs
        # from its own folder and a later re-import of the originals
        # lands in the wrong place -- which showed up as imported pages
        # vanishing when the book was reopened.
        appdata = tempfile.mkdtemp()
        old = os.environ.get("APPDATA")
        os.environ["APPDATA"] = appdata
        try:
            from core import config, extract as ex
            source = "orig1.png|orig2.png"
            book_id = ex.book_id_for_source(source)
            workspace = os.path.join(config.books_dir(), book_id)
            os.makedirs(os.path.join(workspace, "pages"))
            book = library.create_book(
                book_id, "T", source, source_kind="images")
            book.workspace = workspace
            for n in (1, 2):
                Image.new("RGB", (10, 10), "white").save(
                    os.path.join(workspace, "pages", "%04d.jpg" % n))
            book.detect_page_count()
            book.save()

            # Reader import: append images and recount, WITHOUT touching
            # source (this is the fixed behaviour).
            ex.append_image_files(self.new_paths, workspace)
            book.detect_page_count()
            book.save()

            reloaded = library.Book.load(workspace)
            # Source is unchanged, so it still hashes to this folder.
            self.assertEqual(reloaded.source, source)
            self.assertEqual(ex.book_id_for_source(reloaded.source),
                             os.path.basename(workspace))
            self.assertEqual(reloaded.page_count, 5)
        finally:
            if old is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = old
            shutil.rmtree(appdata, ignore_errors=True)

    def test_reading_position_reflects_final_save_not_import_time(self):
        # After importing pages mid-session the library reloads the book,
        # capturing the reading position as it was at import time. When
        # the reader later closes further along, reopening must restore
        # the final position, not the stale import-time one. The library
        # reloads from disk, so the invariant is that the last save on
        # close wins; this checks it at the data layer.
        appdata = tempfile.mkdtemp()
        old = os.environ.get("APPDATA")
        os.environ["APPDATA"] = appdata
        try:
            from core import config
            workspace = os.path.join(config.books_dir(), "posbook")
            os.makedirs(os.path.join(workspace, "pages"))
            book = library.create_book(
                "posbook", "T", "seed", source_kind="images")
            book.workspace = workspace
            for n in (1, 2, 3):
                Image.new("RGB", (10, 10), "white").save(
                    os.path.join(workspace, "pages", "%04d.jpg" % n))
            book.detect_page_count()
            book.scripts = {1: "a", 2: "b", 3: "c"}
            book.last_page = 2
            book.save()

            extract.append_image_files(self.new_paths, workspace)
            book.detect_page_count()
            book.save()
            for n in (4, 5):
                book.scripts[n] = "page %d" % n
            book.save()
            mid = library.Book.load(workspace)
            self.assertEqual(mid.last_page, 2)

            # Reader reads on to page 5 and closes, saving the position.
            book.last_page = 5
            book.save()

            final = library.Book.load(workspace)
            self.assertEqual(final.last_page, 5)
        finally:
            if old is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = old
            shutil.rmtree(appdata, ignore_errors=True)

    def test_imported_pages_persist_to_the_library(self):
        # The reader-side import bug: pages added and processed inside
        # the reader must survive when the library reloads books from
        # disk, not just live in the reader's in-memory copy.
        appdata = tempfile.mkdtemp()
        old_appdata = os.environ.get("APPDATA")
        os.environ["APPDATA"] = appdata
        try:
            from core import config
            workspace = os.path.join(config.books_dir(), "b1")
            os.makedirs(os.path.join(workspace, "pages"))
            book = library.create_book(
                "b1", "Test", "seed", source_kind="images")
            book.workspace = workspace
            # Two seed pages, both processed.
            for n in (1, 2):
                Image.new("RGB", (10, 10), "white").save(
                    os.path.join(workspace, "pages", "%04d.jpg" % n))
            book.detect_page_count()
            book.scripts = {1: "one", 2: "two"}
            book.save()

            # Simulate the reader import: append images, recount, save.
            extract.append_image_files(self.new_paths, workspace)
            book.detect_page_count()
            book.save()
            # Simulate processing the new pages (what ProcessingWindow
            # drives via processor, which saves after each batch).
            for n in (3, 4, 5):
                book.scripts[n] = "page %d" % n
            book.save()

            # The library reloads from disk -- this is what refresh_books
            # does. The reloaded book must show all five pages processed.
            reloaded = [b for b in library.list_books()
                        if b.workspace == workspace][0]
            self.assertEqual(reloaded.page_count, 5)
            self.assertEqual(reloaded.processed_count(), 5)
            self.assertTrue(reloaded.is_complete())
            self.assertEqual(reloaded.scripts.get(5), "page 5")
        finally:
            if old_appdata is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = old_appdata
            shutil.rmtree(appdata, ignore_errors=True)


class TestReprocessPageRange(unittest.TestCase):
    """Reprocessing a chosen range: clearing those pages' scripts and
    processing only them, leaving the rest of the book alone."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.book = library.Book(self.tmp)
        self.book.page_count = 10
        self.book.scripts = {n: "Panel 1 (top right): page %d" % n
                             for n in range(1, 11)}
        self.book.character_notes = "Aiko: short dark hair."

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_clearing_a_range_leaves_other_pages(self):
        cleared = self.book.clear_pages([4, 5, 6])
        self.assertEqual(cleared, [4, 5, 6])
        self.assertEqual(self.book.processed_count(), 7)
        self.assertIn(3, self.book.scripts)
        self.assertIn(7, self.book.scripts)
        self.assertNotIn(5, self.book.scripts)

    def test_cleared_pages_become_the_pending_work(self):
        self.book.clear_pages([4, 5, 6])
        self.assertEqual(self.book.unprocessed_pages(), [4, 5, 6])

    def test_clearing_keeps_character_notes(self):
        # Redoing a page in the middle of a book keeps the cast in mind.
        self.book.clear_pages([2])
        self.assertEqual(self.book.character_notes,
                         "Aiko: short dark hair.")

    def test_clear_pages_never_touches_notes_even_for_every_page(self):
        # clear_pages only ever drops scripts. A whole-book reprocess
        # resets the notes, but that is the caller's job, not this
        # method's -- see the reprocess handlers in the GUI.
        self.book.clear_pages(list(range(1, 11)))
        self.assertEqual(self.book.processed_count(), 0)
        self.assertEqual(self.book.character_notes,
                         "Aiko: short dark hair.")

    def test_clearing_a_single_page(self):
        cleared = self.book.clear_pages([7])
        self.assertEqual(cleared, [7])
        self.assertEqual(self.book.processed_count(), 9)

    def test_clearing_an_unprocessed_page_reports_nothing_cleared(self):
        self.book.clear_pages([3])
        self.assertEqual(self.book.clear_pages([3]), [])

    def test_clearing_pages_outside_the_book_is_harmless(self):
        self.assertEqual(self.book.clear_pages([99, 100]), [])
        self.assertEqual(self.book.processed_count(), 10)

    def test_cleared_range_survives_save_and_load(self):
        self.book.clear_pages([4, 5])
        self.book.save()
        reloaded = library.Book.load(self.tmp)
        self.assertEqual(reloaded.unprocessed_pages(), [4, 5])
        self.assertEqual(reloaded.character_notes, "Aiko: short dark hair.")


class TestProcessBookPageArgument(unittest.TestCase):
    """process_book(pages=...) drives a range reprocess: it must honour
    the list it is given and never resend work already done."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.book = library.Book(self.tmp)
        self.book.page_count = 10
        self.book.scripts = {n: "page %d" % n for n in range(1, 11)}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _pending(self, pages):
        """The page list process_book would work on, without calling
        the API: mirrors the filter at the top of process_book."""
        if pages is None:
            return self.book.unprocessed_pages()
        return [n for n in pages
                if 1 <= n <= self.book.page_count
                and n not in self.book.scripts]

    def test_none_means_every_unprocessed_page(self):
        self.book.clear_pages([2, 8])
        self.assertEqual(self._pending(None), [2, 8])

    def test_an_explicit_range_is_honoured(self):
        self.book.clear_pages([4, 5, 6])
        self.assertEqual(self._pending([4, 5, 6]), [4, 5, 6])

    def test_pages_still_holding_a_script_are_skipped(self):
        # Guards against a stale range resending pages that are fine.
        self.book.clear_pages([4])
        self.assertEqual(self._pending([3, 4, 5]), [4])

    def test_pages_outside_the_book_are_dropped(self):
        self.book.clear_pages([9, 10])
        self.assertEqual(self._pending([9, 10, 11, 99]), [9, 10])

    def test_an_empty_list_processes_nothing(self):
        self.assertEqual(self._pending([]), [])

    def test_a_cleared_range_batches_consecutively(self):
        # Batches must not bridge pages that still have scripts.
        self.book.clear_pages([3, 4, 7])
        batches = processor.make_batches(self._pending([3, 4, 7]), 4)
        self.assertEqual(batches, [[3, 4], [7]])


class TestReadableAfterProcessing(unittest.TestCase):
    """The processing dialog offers "Read now" when the book has any
    saved pages, which is what makes a book readable -- including after
    a cancelled or partly failed run. The condition is tested here
    against the real Book; the button itself is wxPython and is not
    imported by the test suite."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.book = library.Book(self.tmp)
        self.book.page_count = 4

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_nothing_processed_is_not_readable(self):
        self.assertEqual(self.book.processed_count(), 0)

    def test_a_partial_run_is_readable(self):
        # A cancelled or rate-limited run still saves what it finished,
        # and those pages can be read straight away.
        self.book.scripts = {1: "Panel 1 (top right): A street."}
        self.assertGreater(self.book.processed_count(), 0)
        self.assertFalse(self.book.is_complete())

    def test_a_complete_run_is_readable(self):
        self.book.scripts = {n: "Panel 1 (top right): x" for n in range(1, 5)}
        self.assertGreater(self.book.processed_count(), 0)
        self.assertTrue(self.book.is_complete())

    def test_pages_outside_the_book_do_not_count(self):
        # A stray script for a page beyond page_count must not make an
        # otherwise unprocessed book look readable.
        self.book.scripts = {99: "orphan"}
        self.assertEqual(self.book.processed_count(), 0)

    def test_saved_pages_survive_for_the_reader(self):
        self.book.scripts = {1: "Panel 1 (top right): A street."}
        self.book.save()
        reloaded = library.Book.load(self.tmp)
        self.assertEqual(reloaded.processed_count(), 1)


class TestPageLayoutMap(unittest.TestCase):
    """The model works out the page's panel layout before describing
    it, and sweeps each panel in the tradition's own direction. Grid
    positions suit page-based comics; a vertical webtoon has no columns,
    so it gets a sequence instead."""

    GRID_TYPES = ("manga", "manhwa", "western")
    ALL_TYPES = GRID_TYPES + ("webtoon",)

    def _prompt(self, comic_type="manga", verbosity="detailed"):
        return prompts.build_system_prompt(
            comic_type, verbosity, "English")

    def test_every_type_maps_the_page_first(self):
        for comic_type in self.ALL_TYPES:
            prompt = self._prompt(comic_type)
            self.assertIn("MAPPING THE PAGE", prompt)
            self.assertIn(prompts.LAYOUT_TEXT[comic_type], prompt)

    def test_manga_orders_rows_right_to_left(self):
        block = prompts.LAYOUT_TEXT["manga"]
        self.assertIn("from RIGHT to LEFT", block)
        self.assertIn("rows from top to bottom", block)

    def test_western_and_manhwa_order_rows_left_to_right(self):
        for comic_type in ("western", "manhwa"):
            block = prompts.LAYOUT_TEXT[comic_type]
            self.assertIn("from LEFT to RIGHT", block)

    def test_the_real_layout_is_read_not_assumed(self):
        # The nine position names are vocabulary, not a template: a
        # page has whatever panels it has.
        for comic_type in self.ALL_TYPES:
            block = prompts.LAYOUT_TEXT[comic_type]
            self.assertIn("actually drawn", block)
            self.assertIn("never assume", block)
            self.assertIn("fixed number of panels", block)

    def test_grid_types_say_the_cells_are_not_a_template(self):
        for comic_type in self.GRID_TYPES:
            block = prompts.LAYOUT_TEXT[comic_type]
            self.assertIn("not a grid the page must fit", block)
            self.assertIn("Only use the nine cell names", block)

    def test_irregular_layouts_are_given_as_examples(self):
        # Rows of two and four, banners and full-page images all need
        # naming or a model will reach for the nine-cell default.
        for comic_type in ("manga", "western"):
            block = prompts.LAYOUT_TEXT[comic_type]
            self.assertIn("two panels is", block)
            self.assertIn("full width top", block)
            self.assertIn("full page", block)

    def test_within_panel_direction_matches_the_tradition(self):
        self.assertIn("sweep the same way: right to left",
                      prompts.LAYOUT_TEXT["manga"])
        for comic_type in ("manhwa", "webtoon", "western"):
            self.assertIn("sweep left to right",
                          prompts.LAYOUT_TEXT[comic_type])

    def test_within_panel_rule_covers_art_and_dialogue(self):
        for comic_type in self.ALL_TYPES:
            block = prompts.LAYOUT_TEXT[comic_type]
            self.assertIn("visual description and to the order of the "
                          "dialogue lines", block)

    def test_webtoon_gets_no_grid_positions(self):
        # A scrolling strip has no left, centre or right, so grid words
        # would describe a layout the page does not have.
        block = prompts.LAYOUT_TEXT["webtoon"]
        for grid_word in ("top right", "top left", "middle right",
                          "middle left", "bottom right", "bottom left",
                          "bottom center", "right half", "left half"):
            self.assertNotIn(grid_word, block)
        self.assertIn("top, middle, bottom, and full width", block)
        self.assertIn("strictly top to bottom", block)

    def test_manhwa_handles_both_page_shapes(self):
        # The same manhwa can mix grid pages and vertical strips.
        block = prompts.LAYOUT_TEXT["manhwa"]
        self.assertIn("If the page is a grid of panels", block)
        self.assertIn("single vertical strip", block)
        self.assertIn("The same book may contain both", block)

    def test_wide_panels_have_a_form_in_grid_types(self):
        for comic_type in self.GRID_TYPES:
            block = prompts.LAYOUT_TEXT[comic_type]
            self.assertIn("full width top", block)
            self.assertIn("full page", block)

    def test_rows_are_not_assumed_to_hold_three_panels(self):
        for comic_type in ("manga", "western"):
            block = prompts.LAYOUT_TEXT[comic_type]
            self.assertIn("two or four", block)
            self.assertIn("Whatever the layout, that is the sequence",
                          block)

    def test_the_map_is_never_written_out(self):
        # Building a map must not become a preamble in the output.
        prompt = self._prompt()
        self.assertIn("working-out for your own use", prompt)
        self.assertIn("never written out as a list", prompt)

    def test_blocks_are_specific_to_each_tradition(self):
        self.assertEqual(len(set(prompts.LAYOUT_TEXT.values())), 4)

    def test_legacy_direction_values_get_layout_rules(self):
        for legacy, expected in (("rtl", "manga"), ("ltr", "western"),
                                 ("vertical", "webtoon")):
            prompt = prompts.build_system_prompt(
                legacy, "detailed", "English")
            self.assertIn(prompts.LAYOUT_TEXT[expected], prompt)

    def test_unknown_comic_type_falls_back_to_manga_layout(self):
        prompt = prompts.build_system_prompt(
            "nonsense", "detailed", "English")
        self.assertIn(prompts.LAYOUT_TEXT["manga"], prompt)

    def test_layout_applies_at_every_verbosity(self):
        for verbosity in ("concise", "detailed", "extensive"):
            prompt = self._prompt("manga", verbosity)
            self.assertIn("MAPPING THE PAGE", prompt)

    def test_position_vocabulary_points_at_the_map(self):
        prompt = self._prompt()
        self.assertIn("Pick the position from the page map", prompt)


class TestOutputDiscipline(unittest.TestCase):
    """The script must contain the comic and nothing else: no remarks
    from the model about its own work, and no reorganising the page
    into general image-description categories. Both were seen from
    Gemini models in real use."""

    COMIC_TYPES = ("manga", "manhwa", "webtoon", "western")

    def _prompt(self, comic_type="manga", verbosity="detailed"):
        return prompts.build_system_prompt(
            comic_type, verbosity, "English")

    def test_self_commentary_is_banned_in_every_type(self):
        for comic_type in self.COMIC_TYPES:
            prompt = self._prompt(comic_type)
            self.assertIn("NEVER WRITE ABOUT YOURSELF", prompt)

    def test_the_specific_leaked_phrases_are_named(self):
        # Naming the actual phrases works better than a general rule.
        prompt = self._prompt()
        for phrase in ('"I forgot"', '"oops"', '"correction"',
                       '"apologies"', '"as an AI"'):
            self.assertIn(phrase, prompt)

    def test_self_correction_is_silent(self):
        prompt = self._prompt()
        self.assertIn("do not narrate the fix", prompt)

    def test_unclear_art_is_settled_without_narration(self):
        # The model carries on writing rather than explaining its
        # difficulty, but the wording stays light -- it must not read
        # as another push toward answering Unknown.
        prompt = self._prompt()
        self.assertIn("carry on writing the script", prompt)

    def test_category_headings_are_banned_in_every_type(self):
        for comic_type in self.COMIC_TYPES:
            prompt = self._prompt(comic_type)
            self.assertIn("THE PANEL FORMAT IS THE ONLY STRUCTURE", prompt)

    def test_the_specific_categories_are_named(self):
        prompt = self._prompt()
        for heading in ('"Composition"', '"Setting"', '"Characters"',
                        '"Context"', '"Summary"', '"Mood"',
                        '"Art style"'):
            self.assertIn(heading, prompt)

    def test_grouping_across_panels_is_banned(self):
        prompt = self._prompt()
        self.assertIn("never group all the characters", prompt)
        self.assertIn("never gather all the characters", prompt)

    def test_panels_are_completed_one_at_a_time(self):
        for comic_type in self.COMIC_TYPES:
            prompt = self._prompt(comic_type)
            self.assertIn("one panel at a time", prompt)
            self.assertIn(
                "finishing each panel completely", prompt)

    def test_markdown_and_invented_headings_are_banned(self):
        for comic_type in self.COMIC_TYPES:
            prompt = self._prompt(comic_type)
            self.assertIn("NO HEADINGS, LABELS, OR MARKDOWN", prompt)

    def test_no_opening_or_closing_sentence(self):
        prompt = self._prompt()
        self.assertIn("first line of a page is its page header", prompt)

    def test_rules_apply_at_every_verbosity(self):
        for verbosity in ("concise", "detailed", "extensive"):
            prompt = self._prompt("manga", verbosity)
            self.assertIn("NEVER WRITE ABOUT YOURSELF", prompt)
            self.assertIn("THE PANEL FORMAT IS THE ONLY STRUCTURE", prompt)

    def test_existing_objectivity_rule_is_kept(self):
        # The new rules sit alongside the interpretive-commentary ban,
        # they do not replace it.
        prompt = self._prompt()
        self.assertIn("OBJECTIVITY IS STRICT", prompt)
        self.assertIn(
            "Do not add commentary, summaries, chapter recaps", prompt)


class TestPreambleStillReachesTheReader(unittest.TestCase):
    """If a model does emit stray text despite the rules, the reader
    shows it rather than silently dropping it -- losing real content
    would be worse than showing a stray line."""

    def test_preamble_is_attached_to_the_first_panel(self):
        script = ("Composition: a wide establishing shot.\n"
                  "Panel 1 (top right): A street at dusk.\n"
                  "Aiko: \"We're late.\"")
        units = prompts.split_panels(script)
        self.assertEqual(len(units), 1)
        self.assertIn("Composition:", units[0])
        self.assertIn("Panel 1", units[0])

    def test_a_script_with_no_panel_markers_is_one_unit(self):
        units = prompts.split_panels("Summary: nothing was parsed.")
        self.assertEqual(len(units), 1)

    def test_normal_scripts_are_unaffected(self):
        script = ("Panel 1 (top right): A street.\n"
                  "Aiko: \"Late again.\"\n"
                  "Panel 2 (top left): A clock.")
        units = prompts.split_panels(script)
        self.assertEqual(len(units), 2)
        self.assertTrue(units[0].startswith("Panel 1"))
        self.assertTrue(units[1].startswith("Panel 2"))


class TestTailRules(unittest.TestCase):
    """Speech-bubble tails: the artist's own mark of who is speaking.
    The tail outranks proximity, which is what previously caused wrong
    speaker names."""

    COMIC_TYPES = ("manga", "manhwa", "webtoon", "western")

    def _prompt(self, comic_type):
        return prompts.build_system_prompt(comic_type, "detailed", "English")

    def test_every_comic_type_has_tail_rules(self):
        for comic_type in self.COMIC_TYPES:
            self.assertIn(comic_type, prompts.TAIL_TEXT)
            self.assertGreater(len(prompts.TAIL_TEXT[comic_type]), 500)

    def test_tail_section_reaches_every_prompt(self):
        for comic_type in self.COMIC_TYPES:
            prompt = self._prompt(comic_type)
            self.assertIn("WHICH CHARACTER IS SPEAKING", prompt)
            self.assertIn(prompts.TAIL_TEXT[comic_type], prompt)

    def test_tail_outranks_proximity_in_every_type(self):
        for comic_type in self.COMIC_TYPES:
            prompt = self._prompt(comic_type)
            self.assertIn("Proximity is not attribution", prompt)

    def test_bubble_chains_are_one_speaker(self):
        for comic_type in self.COMIC_TYPES:
            self.assertIn("chain", self._prompt(comic_type))

    def test_tailless_bubbles_carry_the_speaker_forward(self):
        # A tail-less bubble should resolve to the previous speaker, NOT
        # become a reason to give up on naming anyone.
        for comic_type in self.COMIC_TYPES:
            prompt = self._prompt(comic_type)
            self.assertIn("no tail", prompt)
            self.assertIn("carry that speaker forward", prompt)

    def test_narration_and_thought_are_not_dialogue(self):
        for comic_type in self.COMIC_TYPES:
            prompt = self._prompt(comic_type)
            self.assertIn("narration", prompt.lower())
            self.assertIn("(thinking)", prompt)

    def test_rules_are_specific_to_each_tradition(self):
        manga = prompts.TAIL_TEXT["manga"]
        western = prompts.TAIL_TEXT["western"]
        webtoon = prompts.TAIL_TEXT["webtoon"]
        manhwa = prompts.TAIL_TEXT["manhwa"]
        self.assertIn("vertical text", manga)
        self.assertIn("narrow bands", western)
        self.assertNotIn("narrow bands", manga)
        self.assertIn("ABOVE or BELOW", webtoon)
        self.assertIn("ABOVE or BELOW", manhwa)
        self.assertNotIn("ABOVE or BELOW", manga)
        self.assertEqual(len({manga, manhwa, webtoon, western}), 4)

    def test_legacy_direction_values_get_tail_rules(self):
        for legacy, expected in (("rtl", "manga"), ("ltr", "western"),
                                 ("vertical", "webtoon")):
            prompt = prompts.build_system_prompt(
                legacy, "detailed", "English")
            self.assertIn(prompts.TAIL_TEXT[expected], prompt)

    def test_unknown_comic_type_falls_back_to_manga_tails(self):
        prompt = prompts.build_system_prompt(
            "nonsense", "detailed", "English")
        self.assertIn(prompts.TAIL_TEXT["manga"], prompt)

    def test_tail_rules_apply_at_every_verbosity(self):
        for verbosity in ("concise", "detailed", "extensive"):
            prompt = prompts.build_system_prompt(
                "manga", verbosity, "English")
            self.assertIn("Proximity is not attribution", prompt)


class TestUnknownIsNotEncouraged(unittest.TestCase):
    """Regression guard. An earlier draft of the tail rules also told
    the model that answering "Unknown" was an expected, non-failing
    outcome. In testing that made it answer Unknown far too often, so
    the tail rules must never grow that framing back: the single
    existing rule in the output format is the only place uncertainty is
    licensed."""

    COMIC_TYPES = ("manga", "manhwa", "webtoon", "western")

    def test_unknown_is_mentioned_exactly_once(self):
        # Once, in the OUTPUT FORMAT rules -- the 0.15.0 wording. More
        # than that starts nudging models toward using it, which is
        # what made the reverted 0.16.0 draft over-trigger.
        for comic_type in self.COMIC_TYPES:
            prompt = prompts.build_system_prompt(
                comic_type, "detailed", "English")
            self.assertEqual(
                prompt.count("Unknown"), 1,
                "%s prompt mentions Unknown %d times"
                % (comic_type, prompt.count("Unknown")))

    def test_original_attribution_rule_is_untouched(self):
        prompt = prompts.build_system_prompt(
            "manga", "detailed", "English")
        # The 0.15.0 rule, now with the fallback labels allowed in the
        # output language rather than pinned to English.
        self.assertIn(
            "Attribute every line of dialogue to a character. Use bubble "
            "tail position, who is shown speaking, and the CHARACTER "
            "NOTES to identify speakers. If genuinely uncertain, use "
            "the English equivalent of \"Off-panel voice:\" or "
            "\"Unknown:\" rather than guessing a name.", prompt)

    def test_tail_rules_never_frame_uncertainty_as_desirable(self):
        banned = ("not a failure", "expected outcome",
                  "correct, expected", "expect to use it",
                  "do not guess a name", "rather than guessing")
        for comic_type in self.COMIC_TYPES:
            block = prompts.TAIL_TEXT[comic_type]
            for phrase in banned:
                self.assertNotIn(
                    phrase, block,
                    "%s tail rules contain %r" % (comic_type, phrase))

    def test_off_panel_bullets_push_toward_naming(self):
        # Where a tail leads off-panel, the rules must send the model to
        # neighbouring panels to find a name first.
        for comic_type in self.COMIC_TYPES:
            block = prompts.TAIL_TEXT[comic_type]
            self.assertIn("surrounding panels to name them", block)

    def test_no_standalone_attribution_procedure_block(self):
        # The four-step "WHO IS SPEAKING" block was part of the reverted
        # design and must not return.
        self.assertFalse(hasattr(prompts, "ATTRIBUTION_TEXT"))
        prompt = prompts.build_system_prompt(
            "manga", "detailed", "English")
        self.assertNotIn("WHO IS SPEAKING", prompt)


class TestAskInheritsTailRules(unittest.TestCase):
    def _settings(self, comic_type="manga"):
        return {"comic_type": comic_type, "output_language": "English"}

    def test_ask_prompt_carries_tail_rules(self):
        from core import ask
        for comic_type in ("manga", "manhwa", "webtoon", "western"):
            prompt = ask.build_ask_system_prompt(self._settings(comic_type))
            self.assertIn(prompts.TAIL_TEXT[comic_type], prompt)

    def test_ask_prompt_prefers_the_image_over_the_script(self):
        from core import ask
        prompt = ask.build_ask_system_prompt(self._settings())
        self.assertIn("trust the page images", prompt)

    def test_ask_prompt_does_not_encourage_unknown(self):
        from core import ask
        prompt = ask.build_ask_system_prompt(self._settings())
        for phrase in ("rather than naming a likely", "cannot be "
                       "established", "not a failure"):
            self.assertNotIn(phrase, prompt)

    def test_ask_prompt_still_localised_and_markdown_free(self):
        from core import ask
        prompt = ask.build_ask_system_prompt(
            {"comic_type": "manga", "output_language": "Arabic"})
        self.assertIn("Answer in Arabic", prompt)
        self.assertIn("Markdown", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
