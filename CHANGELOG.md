# Changelog

Notable changes to Accessible Manga Reader are listed below, newest first.

## 1.0.0

### Added

- Per-machine installers for x64 and ARM64. The installer uses the folder
  build, installs in Program Files, creates shortcuts, and requests
  administrator permission.
- In-app installation of updates for installed and writable folder copies.
  Downloads are verified for size before use. Folder updates are staged and
  swapped after the app closes, with rollback if the swap fails.
- Original (same as the comic) output language. In this mode, comic text is
  transcribed without translation and exports do not assign a language.
- MP3 export for a full book or page range.
- Offline Kokoro speech with 54 voices across nine language and locale groups.
  Model files are downloaded and verified on first use.
- Gemini speech with selectable voice models, voice samples, pacing, retries,
  and API-key rotation.
- A separate audio progress window with cancellation and optional saving of
  completed audio.

### Changed

- Releases provide a ZIP and installer for each architecture. The standalone
  one-file executable is no longer distributed.
- Audio progress is reported as a percentage.
- Per-minute rate limits move immediately to the next API key. The client waits
  only after every configured key is limited. Daily quota errors still rotate
  immediately.
- Removed retired Gemini models. The default is `gemini-3.6-flash`, and saved
  retired models are migrated to current replacements.
- First page and last page use Alt+F and Alt+L. Ctrl+Home and Ctrl+End remain
  available to the text control.
- Audio exports preserve the book's page numbering when a page range is used.
- Audio settings describe the supported language coverage for Kokoro and
  Gemini.

### Fixed

- Empty successful API responses are retried with backoff. Content blocks are
  still reported without retrying.
- Keyboard focus returns to the selected voice after a sample starts.
- Removed the unused Windows speech engine and its `comtypes` dependency.

## 0.20.0

### Added

- Export menu for text, HTML, EPUB, Word, and tagged PDF.
- Page and panel headings in EPUB, Word, and PDF exports.

### Changed

- Text and HTML export commands moved to the Export menu. Ctrl+E and
  Ctrl+Shift+E remain available.

### Fixed

- Arrow keys work correctly in the Reprocess pages and Ask about this page
  option groups.

## 0.19.0

### Added

- Reading from the processing window while completed pages continue to load.
- First and Last navigation commands and buttons.
- A folder-based ZIP build alongside the single-file executable.
- A setting to show converted pages individually or as one continuous list.

### Changed

- Updated Anthropic model suggestions and defaults.
- Page headings no longer contain decorative equals signs.
- Previous and Next move focus to the reader text.
- The library identifies the book currently being processed.
- Only one book can be processed at a time. Operations that conflict with the
  active job are blocked.

## 0.18.0

### Added

- Import more pages from the reader for books created from image files.

### Changed

- Output language now applies to descriptions, dialogue, speaker names, sound
  effects, captions, thoughts, and character notes.
- Page analysis now maps panel layout before writing the script and follows the
  reading direction of the selected comic type.
- Prompt rules require panel-by-panel output and prohibit model commentary and
  unsupported headings.

## 0.17.0

### Added

- Reprocess the current page, a page range, or the full book. Partial
  reprocessing keeps existing character notes.

## 0.16.0

### Added

- Read now button in the processing window, including after a cancelled run
  with completed pages.

### Changed

- Speaker attribution follows speech-bubble tails and comic-specific dialogue
  conventions.
- Page questions use the same attribution rules.

## 0.15.0

### Added

- Ask about a page, including surrounding-page context, follow-up questions,
  cancellation, structured headings, and answer copying.
- Updated Gemini model suggestions and model-list refresh support.

## 0.14.0

### Added

- Setting to skip the book-instructions prompt before processing.
- Save and Save and reprocess commands for book instructions.

### Changed

- Error messages include plain-language causes and recovery steps.
- Updated default and suggested models.
- Suggested model lists include only models that support images.

## 0.13.0

### Added

- Comic type setting for manga, manhwa or manhua, webtoons, and Western comics.
- Separate custom instructions for each comic type.

### Changed

- Descriptions associate text with the relevant character, object, or event.
- Structured graphics are described in reading order.
- The prompt does not add or remove honorifics.

## 0.12.0

### Changed

- PDF import is supported on Windows ARM64 builds.

## 0.11.1

### Fixed

- HTML view content displays correctly on affected systems.
- Tab and arrow-key behaviour in HTML view matches the rest of the app.

## 0.11.0

### Added

- Built-in user manual.
- Optional update checks and beta-version filtering.
- Ctrl+L shortcut for panel labels.
- Help links for the project, issue tracker, and developer contact.

### Fixed

- HTML view announces the book title without internal display terminology.

## 0.10.1

### Changed

- HTML view uses the lighter built-in display engine.
- Model refresh lists only models that support images.

### Fixed

- Packaged and source builds use the same HTML display engine.

## 0.10.0

### Added

- Structured HTML view and HTML export.
- Option to hide panel labels and read each page as continuous text.
- Free up space command for removing stored images from processed books.

### Changed

- Improved right-to-left panel, bubble, and text ordering.
- Prompt requires every panel and visible text element to be included.

## 0.9.0

- First public release.
