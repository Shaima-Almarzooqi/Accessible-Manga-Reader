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
        self.assertIn("=== Page 1 of 2 ===", text)
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
        self.assertEqual(client.model, "gemini-3.6-flash")


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
                         "gemini-3.6-flash")




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
        self.assertIn("translate it into Swahili", prompt)

    def test_listed_language_reaches_the_prompt(self):
        prompt = prompts.build_system_prompt("rtl", "detailed", "Arabic")
        self.assertIn("translate it into Arabic", prompt)




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
        self.assertIn("silently map the page's panel grid", prompt)

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
        text = "=== Page 2 of 9 ===\nPanel 1 (top left): x."
        stripped = prompts.strip_panel_labels(text)
        self.assertIn("=== Page 2 of 9 ===", stripped)

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
        self.assertIn("<h1>HTML &lt;Test&gt; &amp; Co</h1>", page)
        self.assertIn("<h2>Page 1 of 2</h2>", page)
        self.assertIn("<h3>Panel 1 of 2 (top right)</h3>", page)
        self.assertIn("<h3>Panel 2 of 2 (bottom left)</h3>", page)
        # Content is escaped, so nothing a script wrote can inject HTML.
        self.assertIn("A &lt;b&gt;boy&lt;/b&gt; runs.", page)
        self.assertIn("&quot;Wait &amp; see!&quot;", page)

    def test_continuous_mode_has_page_headings_only(self):
        from core import html_export
        page = html_export.build_html(self._book(), show_panel_labels=False)
        self.assertIn("<h2>Page 1 of 2</h2>", page)
        self.assertNotIn("<h3>", page)
        self.assertNotIn("Panel 1", page)
        self.assertIn("A &lt;b&gt;boy&lt;/b&gt; runs.", page)

    def test_unprocessed_page_placeholder(self):
        from core import html_export
        page = html_export.build_html(self._book(), show_panel_labels=True)
        self.assertIn("<h2>Page 2 of 2</h2>", page)
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
            self.assertIn("do not add or remove honorifics", p)

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
                         "gemini-3.6-flash")
        self.assertEqual(config.SUGGESTED_MODELS["gemini"][0],
                         "gemini-3.6-flash")

    def test_every_default_model_is_in_its_suggested_list(self):
        for service in ("gemini", "anthropic", "openai", "openrouter"):
            default = config.DEFAULT_SETTINGS["%s_model" % service]
            self.assertIn(default, config.SUGGESTED_MODELS[service],
                          service)

    def test_ask_instructions_setting_defaults_on(self):
        self.assertTrue(
            config.DEFAULT_SETTINGS["ask_instructions_before_processing"])

    def test_gemini_list_offers_only_flash_class_models(self):
        """The frontier models think for far longer per request and are
        the ones free-tier keys cannot get served, so the suggestions
        stay on the Flash line. Anything else can still be typed in."""
        for model in config.SUGGESTED_MODELS["gemini"]:
            self.assertIn("flash", model, model)




class TestInteractiveRetryPolicy(unittest.TestCase):
    """Asking must not leave the reader through minutes of backoff."""

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
        # One client already built, one built after the limits are set:
        # both must end up with the short policy.
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

    def test_only_the_newest_question_carries_the_jump_anchor(self):
        """The window jumps to this anchor after each reply, so a
        follow-up lands on itself rather than back at question one."""
        from core import ask
        doc = ask.conversation_html(
            "Book", [("First?", "Done."), ("Second?", "Also done.")])
        self.assertEqual(doc.count('id="%s"' % ask.LATEST_ANCHOR_ID), 1)
        anchored = doc.index('id="%s"' % ask.LATEST_ANCHOR_ID)
        self.assertGreater(anchored, doc.index("First?"))
        self.assertLess(anchored, doc.index("Second?"))
        # Focusable, or the screen reader cursor would not follow it.
        self.assertIn('tabindex="-1"', doc)

    def test_a_pending_question_takes_the_anchor(self):
        from core import ask
        doc = ask.conversation_html(
            "Book", [("First?", "Done.")],
            pending=("Second?", ask.WAITING_TEXT))
        anchored = doc.index('id="%s"' % ask.LATEST_ANCHOR_ID)
        self.assertGreater(anchored, doc.index("First?"))

    def test_waiting_note_stays_free_of_mechanics(self):
        from core import ask
        self.assertNotIn("page images", ask.WAITING_TEXT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
