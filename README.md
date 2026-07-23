# Accessible Manga Reader

Manga read aloud properly for blind readers.

Comics are one of the few storytelling media that stayed almost entirely closed to blind readers: the words are drawn into the artwork, so no screen reader can touch them, and the story is carried as much by panels, expressions, and sound effects as by dialogue. Accessible Manga Reader sends each page to an AI vision model and turns it into a script you can read with your screen reader: panel-by-panel descriptions, dialogue attributed to the character speaking, sound effects with their meaning, and the silent panels that carry so much of the storytelling. It reads manga, manhwa and manhua, webtoons, and Western comics.

It follows each tradition's own reading grammar, set by the comic type in Settings. Manga is read right to left, top to bottom — panels, speech bubbles inside a panel, and the artwork itself. Manhwa, manhua, and Western comics are read left to right, and webtoons as a single vertical scroll.

## Install

Download the executable for your computer from the [latest release](../../releases) and run it.

* `AccessibleMangaReader-x64.exe` — for most Windows PCs.
* `AccessibleMangaReader-arm64.exe` — for Windows on ARM machines (Snapdragon).

If you are unsure, choose x64. Windows SmartScreen may warn about an unrecognised app on first run, since the executable is not code-signed; choose More info, then Run anyway.

## Get an API key

The app needs an AI service to read the pages. A free key takes a minute:

1. Go to [aistudio.google.com](https://aistudio.google.com), sign in with a Google account, and choose **Get API key**. No credit card is needed.
2. In the app, press Alt+S for Settings and paste the key into the API keys box.

Google's free tier is generous — enough for hundreds of manga pages a day. [OpenRouter](https://openrouter.ai) is a good alternative (email signup, no credit card, free vision-capable models), and Claude and ChatGPT work too if you have paid API access. Any OpenAI-compatible service can be used by entering its endpoint URL.

## Reading a book

Import a book from the File menu:

* **Archive or PDF** (Ctrl+O) — a `.cbz`, `.zip`, or `.pdf` file.
* **Image files** (Ctrl+I) — select all the pages of a chapter; they are ordered by filename.
* **Folder of images** (Ctrl+Shift+I) — every image in a folder.

Then press Alt+P to process. You are offered a box for optional instructions to the AI first — the most useful thing to put there is the cast, for example: *Aiko: short dark hair, school uniform, the class representative. Kenta: messy hair, always late.* The AI will then use those names from the very first page instead of guessing.

Processing sends the pages to the AI in small batches and saves after every batch, so you can cancel any time, choose Process again to carry on where it stopped. Each book is processed once and then cached, so re-reading is instant.

After a book is fully processed, **Free up space** in the Book menu deletes its stored page images. Reading is unaffected; processing the book again later requires importing the original file again.

When it is done, select **Read now** in the processing window to start reading straight away, or press Enter or Alt+R on the book in your library.

## Reading modes

The reader's View menu offers three ways to read, and the default is in Settings:

* **Entire book** — one continuous document, ideal for say-all reading.
* **One page at a time** — with a "Page 3 of 20" position line.
* **One panel at a time** — the closest equivalent to how a sighted reader takes a page in, with a position line like "Page 3 of 20, panel 2 of 6, top right" so you build the same mental map of the page.

The View menu also has **Show panel labels**. When it is off, the "Panel N (position)" markers are hidden and each page reads as one continuous narrative. The processed text is unchanged; the option only affects the display. The same option is in Settings.

**HTML view** (Ctrl+H) opens the book in a separate window as an HTML document. Each page is a level-2 heading and each panel a level-3 heading, so screen reader browse mode navigates with H, 2, and 3. With panel labels off, only page headings are used. The window has a Save as HTML button, and Ctrl+Shift+E in the reader saves the same document.

The text area is an ordinary read-only text control, so say-all, review commands, and find all behave exactly as they do in any document.

## Keyboard

In the library:

* Enter or Alt+R — read the selected book
* Alt+P or Ctrl+P — process or resume it
* Alt+S — settings
* Ctrl+T — AI instructions for this book
* F2 — rename, Delete — remove, Ctrl+A — select all
* Applications key — context menu with every book action

In the reader:

* PageDown / PageUp — next / previous page or panel
* Ctrl+PageDown / Ctrl+PageUp — next / previous page in any mode
* Alt+P / Alt+N — previous / next
* Alt+G or Ctrl+G — go to a page
* Ctrl+F — find (entire-book mode)
* Ctrl+E — save the whole book as a text file
* Ctrl+Q — ask the AI about the current page (it looks at the page image again to answer; uses your AI service like processing does)
* Ctrl+H — open the HTML view
* Ctrl+Shift+E — save as an HTML file
* Alt+C or Escape — close, remembering your place

Tab moves between controls; arrow keys stay inside the control that has focus. Shortcuts belong to the window they are shown in, so Alt+P means Process in the library and Previous in the reader.

## Settings

**AI engine tab.** Choose the service, the model, and enter one or more API keys (one per line, up to 10 — when a key runs out of quota the next is used automatically). Use **Refresh model list** to fetch the models your key can actually use, straight from the service. Pages per request (default 4) trades fewer requests against larger ones; lower it if a service says a request is too large. The delay between requests keeps long runs under per-minute limits.

**General tab.** Output language (choose from the list or type any language — the script is translated into it, and text is transcribed exactly as it appears). Verbosity: Concise, Detailed, or Extensive, which walks every panel through composition, each character's expression and pose, the background, and drawn effects like speed lines. Comic type, which sets the correct reading rules: Manga (Japanese, right to left), Manhwa or Manhua (Korean or Chinese, left to right), Webtoon (vertical scroll), or Western comic (left to right). Custom instructions for the selected comic type, applied to every book of that type (kept separate from a book's own instructions). Whether the AI-instructions box is offered before processing a book (off starts processing immediately; instructions stay available from the Book menu, where Save and reprocess applies them to an already processed book). The default reader view, and whether panel labels are shown.

Verbosity and AI instructions apply to pages processed from then on. To apply them to a book already processed, use **Reprocess entire book** in the Book menu.

## Notes and limits

* **Speaker attribution** follows the speech bubble's tail — the pointer an artist draws toward whoever is talking — rather than whichever character sits nearest the bubble, with the conventions of each comic type. It is good but not perfect on crowded pages; where the speaker cannot be established the AI says "Unknown" rather than guessing. If a line looks misattributed, Ctrl+Q in the reader asks about the page from the original image and can correct it.
* **Your keys stay on your computer**, in a settings file in your app data folder. They are never sent anywhere except to the service you chose.
* **Interface language** is English regardless of the output language setting; only the AI's script is translated.
* **`.cbr` (RAR) archives** are not supported — convert to `.cbz` first.

## Running from source

    pip install -r requirements.txt
    python main.py

Run the tests before changing anything:

    python run_tests.py

## Licence

GNU General Public License, version 3 or later. See LICENSE.

PDF import uses pypdfium2, which is licensed permissively (Apache/BSD) by its authors; it keeps its own licence.
