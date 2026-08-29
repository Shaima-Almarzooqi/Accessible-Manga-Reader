# Accessible Manga Reader

Accessible Manga Reader converts comics into text that can be read with a screen reader. It supports manga, manhwa, manhua, webtoons, and Western comics.

The app sends page images to a supported AI service. The result includes panel descriptions, attributed dialogue, captions, sound effects, and relevant visual details. Reading order follows the comic type selected in Settings.

## Install

Download the files for your processor from the [latest release](../../releases):

- **`AccessibleMangaReader-<arch>-setup.exe`** installs the app in Program Files, creates shortcuts, and supports in-app updates. Installation and updates require administrator permission.
- **`AccessibleMangaReader-<arch>.zip`** is the portable folder version. Extract the ZIP and run the executable inside. It can update itself if its folder is writable.

Use `x64` for most Windows computers. Use `arm64` for Windows on ARM devices, including Snapdragon-based computers.

Windows SmartScreen may warn that the app is unrecognised because it is not code-signed. Select **More info**, then **Run anyway**, if you downloaded it from this repository.

Books, settings, API keys, and downloaded voices are stored separately from the program files. Updating or uninstalling the app does not remove them.

## Get an API key

The app needs access to an AI service. Gemini is the default provider.

To create a Gemini key:

1. Go to [Google AI Studio](https://aistudio.google.com) and sign in.
2. Select **Get API key**, then **Create API key**.
3. Choose a Google Cloud project. Create a project if you do not already have one.
4. Copy the key.
5. In Accessible Manga Reader, press Alt+S and paste the key into the API keys box.

Gemini usage limits are applied per Google Cloud project. Extra keys increase the available allowance only when each key belongs to a different project.

Anthropic and OpenAI API keys require prepaid API credit. ChatGPT Plus and Claude Pro or Max subscriptions do not include API usage. OpenRouter offers some free models, but only models that accept images can process comics. Use **Refresh model list** in Settings to list compatible models for your account.

The built-in manual, available from the Help menu or with F1, includes setup instructions for each provider.

## Add and process a book

Use the File menu to import:

- **Archive or PDF** (Ctrl+O): CBZ, ZIP, or PDF.
- **Image files** (Ctrl+I): selected page images, ordered by filename.
- **Folder of images** (Ctrl+Shift+I): all supported images in a folder.

Select the book and press Alt+P to process it. Before processing, you can enter book-specific instructions, such as character names and identifying features. This prompt can be disabled in Settings.

Pages are processed in batches. The app saves each completed batch, so a cancelled or interrupted job can continue later. A partially processed book can be read while the remaining pages are processed.

After processing, choose **Read now**, press Enter on the book in the library, or press Alt+R.

## Reading modes

The View menu provides three modes:

- **Entire book** shows the processed book as one document.
- **One page at a time** shows one page and its position in the book.
- **One panel at a time** shows one panel and its page, panel number, and position.

**Show panel labels** controls whether labels such as “Panel 2 (top right)” are displayed. It does not change the stored text.

**HTML view** (Ctrl+H) opens the book with page and panel headings. Screen reader browse mode can navigate those headings with H, 2, and 3. Ctrl+Shift+E saves the same structured document as HTML.

## Keyboard shortcuts

In the library:

- Enter or Alt+R — read the selected book
- Alt+P or Ctrl+P — process or resume processing
- Alt+S — open Settings
- Ctrl+T — edit AI instructions for the selected book
- F2 — rename the selected book
- Delete — remove the selected book
- Ctrl+A — select all books
- Applications key — open the context menu

In the reader:

- Page Down / Page Up — next / previous page or panel
- Ctrl+Page Down / Ctrl+Page Up — next / previous page in any mode
- Alt+P / Alt+N — previous / next
- Alt+F / Alt+L — first / last page
- Ctrl+Home / Ctrl+End — start / end of the current text control
- Alt+G or Ctrl+G — go to a page
- Ctrl+F — find text in entire-book mode
- Ctrl+Q — ask the AI about the current page
- Ctrl+R — reprocess a page, range, or the full book
- Ctrl+I — add pages to a book imported from images
- Ctrl+E — export as text
- Ctrl+H — open HTML view
- Ctrl+Shift+E — export as HTML
- Alt+C or Escape — close the reader and save the current position

## Settings

The **AI engine** tab contains the provider, model, API keys, pages per request, and delay between requests. Up to 10 keys can be entered, one per line. The app rotates to the next key when the current key reaches a limit.

The **General** tab contains:

- **Output language.** Select a language or enter one. The app translates descriptions, dialogue, labels, sound effects, and names into that language. Select **Original (same as the comic)** to transcribe the comic without translation.
- **Verbosity.** Concise, Detailed, or Extensive.
- **Comic type.** Manga, Manhwa or Manhua, Webtoon, or Western comic. This controls reading order and layout rules.
- **Comic-type instructions.** Instructions applied to every book of the selected type.
- **Processing and reader options.** Controls for the instruction prompt, default reading mode, panel labels, and update checks.

Changes to output language, verbosity, or instructions apply to newly processed pages. Use **Reprocess pages** to apply them to existing text.

## Export and audio

Processed books can be exported as text, HTML, EPUB, Word, tagged PDF, or MP3. PDF export requires Microsoft Edge or Google Chrome. Audio export supports Gemini speech and offline Kokoro voices. Kokoro model files are downloaded on first use and stored in the app data folder.

## Notes and limits

- Speaker attribution uses speech-bubble tails and the conventions of the selected comic type. Crowded or unclear pages may still be misattributed.
- If a model does not follow the required script format, select another model and reprocess the affected pages.
- API keys remain in the local settings file and are sent only to the selected provider.
- The interface is in English. The output-language setting applies to processed comic text.
- CBR/RAR archives are not supported. Convert them to CBZ first.
- **Free up space** removes stored page images after a book is fully processed. Reading still works, but reprocessing and page questions require the images.

## Run from source

```text
pip install -r requirements.txt
python main.py
```

Run the test suite with:

```text
python run_tests.py
```

## Licence

Accessible Manga Reader is licensed under GNU GPL version 3 or later. See [LICENSE](LICENSE).

Third-party components and their licences are listed in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
