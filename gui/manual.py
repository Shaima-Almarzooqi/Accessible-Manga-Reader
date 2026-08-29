"""The in-app user manual, shown from the Help menu.

The manual is HTML so screen reader browse mode can navigate it by heading.
"""

from core import config

_MANUAL_BODY = """
<h1>Accessible Manga Reader — User Manual</h1>

<h2>What you need</h2>
<p>Accessible Manga Reader reads comic files already stored on your
computer. Supported sources are:</p>
<ul>
<li>CBZ or ZIP archives containing page images</li>
<li>PDF files</li>
<li>Folders of page images</li>
<li>Individual image files, with one image per page</li>
</ul>
<p>CBR and RAR archives are not supported. Convert them to CBZ before
importing them.</p>

<h2>What the app does</h2>
<p>The app sends each page to an AI service and converts the result into
screen-reader-accessible text. The text can include panel descriptions,
attributed dialogue, captions, sound effects, and other visual details.</p>
<p>Reading order is based on the comic type selected in Settings. The app
supports manga, manhwa, manhua, webtoons, and Western comics.</p>

<h2>Step 1: Get an API key</h2>
<p>An API key is a credential that allows the app to use an AI service.
Choose one of the supported providers below.</p>

<h3>Google Gemini</h3>
<ol>
<li>Go to <a href="https://aistudio.google.com">Google AI Studio</a>
and sign in.</li>
<li>Select Get API key, then Create API key.</li>
<li>Choose a Google Cloud project. Create a project if you do not have
one.</li>
<li>Create the key and copy it.</li>
</ol>
<p>Gemini limits are applied per Google Cloud project. If you use several
keys, each key must belong to a different project to provide a separate
allowance. Keys from the same project share one allowance.</p>

<h3>Anthropic</h3>
<p>Anthropic API use requires prepaid credit. A Claude Pro or Max
subscription does not include API usage.</p>
<ol>
<li>Go to
<a href="https://console.anthropic.com">console.anthropic.com</a> and
create an account.</li>
<li>Open Settings, then Billing, and add credit.</li>
<li>Open Settings, then API Keys, and select Create Key.</li>
<li>Copy the key when it is shown. Anthropic does not show the full key
again.</li>
</ol>

<h3>OpenAI</h3>
<p>OpenAI API use requires prepaid credit. A ChatGPT Plus subscription
does not include API usage.</p>
<ol>
<li>Go to
<a href="https://platform.openai.com">platform.openai.com</a> and sign
in.</li>
<li>Open Settings, then Billing. Add a payment method and buy credit.</li>
<li>Open the API keys page and select Create new secret key.</li>
<li>Copy the key when it is shown. OpenAI does not show the full key
again.</li>
</ol>

<h3>OpenRouter</h3>
<ol>
<li>Go to <a href="https://openrouter.ai">openrouter.ai</a> and create
an account.</li>
<li>Open Keys from the account menu and create a key.</li>
<li>Copy the key.</li>
</ol>
<p>OpenRouter offers paid and free models. The available free models and
their limits can change. Accessible Manga Reader requires a model that
accepts images. Use Refresh model list in Settings to list compatible
models for your account.</p>

<h2>Step 2: Enter the API key</h2>
<ol>
<li>Open Accessible Manga Reader.</li>
<li>Press Alt+S to open Settings.</li>
<li>On the AI engine tab, choose the provider.</li>
<li>Paste the key into the API keys box. Enter additional keys on
separate lines.</li>
<li>Select OK.</li>
</ol>
<p>The app can store up to 10 keys for a provider. When one key reaches a
limit, the app tries the next key. Keys are stored in the local settings
file and are sent only to the selected provider.</p>

<h2>Step 3: Add a book</h2>
<p>Open the File menu and choose an import command:</p>
<ul>
<li>Import archive or PDF (Ctrl+O) for CBZ, ZIP, or PDF files</li>
<li>Import image files (Ctrl+I) for selected page images</li>
<li>Import folder of images (Ctrl+Shift+I) for all supported images in a
folder</li>
</ul>
<p>Imported image files are ordered by filename.</p>

<h2>Step 4: Process the book</h2>
<ol>
<li>Select the book in the library.</li>
<li>Press Alt+P.</li>
<li>Enter optional instructions for this book. Character names and brief
identifying details can improve speaker attribution. Leave the box empty
if no instructions are needed.</li>
<li>Select Save and process.</li>
</ol>
<p>Turn off Ask for AI instructions before processing a book in Settings
to start processing without this prompt. Book instructions remain
available from the Book menu.</p>
<p>The app processes pages in batches and saves each completed batch.
Cancelling does not remove completed work. Select Process again to
continue. The same applies after an API limit or temporary server
failure.</p>
<p>Select Read now when processing finishes. The button is also available
after cancellation when at least one page has been processed.</p>

<h3>Read during processing</h3>
<p>The processing window does not block the library or other reader
windows. Use Alt+Tab to return to the library and open another book.</p>
<p>The Converted pages area displays completed pages. Use Page Down and
Page Up, Alt+N and Alt+P, or the Previous page and Next page buttons to
move through them. New pages become available without changing the page
currently displayed.</p>
<p>Only one book can be processed at a time. A book being processed cannot
be renamed, deleted, reprocessed, or cleared with Free up space.</p>

<h2>Step 5: Read</h2>
<p>Select Read now in the processing window, or select a book in the
library and press Enter or Alt+R.</p>
<p>The View menu contains three reading modes:</p>
<ul>
<li>Entire book: all processed text in one document</li>
<li>One page at a time: one page with its position in the book</li>
<li>One panel at a time: one panel with its page, number, and position</li>
</ul>
<p>In page and panel modes, use Page Down and Page Up to move between
items. Ctrl+Page Down and Ctrl+Page Up move between full pages in every
mode.</p>

<h3>Panel labels</h3>
<p>Panel labels show the panel number and position. Press Ctrl+L or use
View, Show panel labels to show or hide them. This setting changes the
display only; it does not change the saved text.</p>

<h3>Ask about a page</h3>
<p>Press Ctrl+Q in the reader to ask a question about the current page.
Choose the current page, surrounding pages, or a page range, then select
Ask. The AI uses the stored page images and the book's character notes.</p>
<p>Questions and answers are displayed as headings. In screen reader
browse mode, use H to move through headings, 2 for questions, and 3 for
answers. Ctrl+End moves to the latest exchange.</p>
<p>Each question uses the selected AI service and counts toward its usage
limit. This feature is unavailable after the page images have been
removed with Free up space.</p>

<h3>Speaker attribution</h3>
<p>The AI uses speech-bubble tails and the conventions of the selected
comic type to identify speakers. Attribution can still be incorrect on
crowded or unclear pages. Book instructions with character names and
identifying features can improve the result.</p>
<p>Use Ctrl+Q to ask about a questionable line. Use Ctrl+R to replace the
processed text for a page.</p>

<h3>Reprocess pages</h3>
<p>Press Ctrl+R in the reader, or choose Reprocess pages from the Book
menu. Reprocess the current page, a page range, or the full book.</p>
<p>Reprocessing a page or range keeps the existing character notes.
Reprocessing the full book rebuilds the notes from the first page.</p>

<h3>Add more image pages</h3>
<p>For books imported from individual images, press Ctrl+I in the reader
to add more pages. New pages are placed after the current last page. This
command is not available for books imported from an archive or PDF.</p>

<h3>HTML view</h3>
<p>Press Ctrl+H to open the full book as structured HTML. Pages are
level-2 headings and panels are level-3 headings. In browse mode, use H,
2, and 3 to navigate. The HTML view can also save the document to a
file.</p>

<h2>Export</h2>
<p>Choose Export from the Book menu in the library or reader. Available
formats are:</p>
<ul>
<li>Text</li>
<li>HTML with page and panel headings</li>
<li>EPUB with headings and page navigation</li>
<li>Word with heading styles</li>
<li>Tagged PDF with headings and bookmarks</li>
<li>MP3 audio</li>
</ul>
<p>PDF export requires Microsoft Edge or Google Chrome. Ctrl+E exports
text, and Ctrl+Shift+E exports HTML.</p>

<h3>Audio export</h3>
<p>MP3 export supports Gemini speech and offline Kokoro voices. Gemini
uses the configured Gemini API keys. Kokoro runs on the computer and
requires a one-time model and voice download.</p>
<p>The progress window reports the percentage read and an estimated time
remaining. A cancelled export can save the completed audio or discard
it.</p>

<h2>Settings</h2>

<h3>AI engine</h3>
<p>Select the provider, model, API keys, pages per request, and delay
between requests. Use Refresh model list to retrieve models available to
the current account.</p>

<h3>Verbosity</h3>
<ul>
<li>Concise: short panel descriptions</li>
<li>Detailed: more information about action and expressions</li>
<li>Extensive: detailed composition, poses, backgrounds, and drawn
effects</li>
</ul>
<p>The prompt instructs the model to describe visible content without
adding opinions.</p>

<h3>Output language</h3>
<p>Select a listed language or enter another language. Descriptions,
dialogue, names, captions, sound effects, and labels are written in the
selected language.</p>
<p>Select Original (same as the comic) to avoid translation. The app
transcribes the comic's text and writes descriptions in the comic's
language. Exports do not assign a language in this mode.</p>

<h3>Comic type</h3>
<ul>
<li>Manga: Japanese right-to-left reading order</li>
<li>Manhwa or Manhua: Korean or Chinese left-to-right reading order</li>
<li>Webtoon: vertical top-to-bottom reading order</li>
<li>Western comic: left-to-right reading order</li>
</ul>
<p>Select the comic type before processing so the correct layout rules
are used.</p>

<h3>Instructions</h3>
<p>Comic-type instructions apply to every book of the selected type.
Book instructions apply only to one book and take priority. Select a book
and press Ctrl+T to edit its instructions.</p>
<p>Instruction and verbosity changes affect pages processed after the
change. Use Reprocess pages to replace existing text.</p>

<h3>Free up space</h3>
<p>After a book is fully processed, select Free up space from the Book
menu to remove its stored page images. The processed text remains
available. Reprocessing and page questions require the images.</p>

<h3>Updates</h3>
<p>The app checks for updates at startup unless this option is disabled in
Settings. Include beta versions controls whether pre-release versions
are offered.</p>
<p>Installed copies and writable folder copies can apply updates from the
update window. The app downloads the appropriate installer or ZIP,
closes, applies the update, and restarts. Installed updates require
administrator permission because the app is stored in Program Files.</p>
<p>Updates and uninstallation do not remove books, settings, API keys, or
downloaded voices.</p>

<h2>Keyboard shortcuts</h2>
<p>Library:</p>
<ul>
<li>Enter or Alt+R: read the selected book</li>
<li>Alt+P or Ctrl+P: process or continue processing</li>
<li>Alt+S: open Settings</li>
<li>Ctrl+T: edit instructions for the selected book</li>
<li>F2: rename the selected book</li>
<li>Delete: remove the selected book</li>
<li>Ctrl+A: select all books</li>
<li>Applications key: open the context menu</li>
</ul>
<p>Reader:</p>
<ul>
<li>Page Down / Page Up: next / previous page or panel</li>
<li>Ctrl+Page Down / Ctrl+Page Up: next / previous full page</li>
<li>Alt+P / Alt+N: previous / next</li>
<li>Alt+F / Alt+L: first / last page</li>
<li>Ctrl+Home / Ctrl+End: start / end of the current text control</li>
<li>Alt+G or Ctrl+G: go to a page</li>
<li>Ctrl+F: find text</li>
<li>Ctrl+L: show or hide panel labels</li>
<li>Ctrl+Q: ask about the current page</li>
<li>Ctrl+R: reprocess pages</li>
<li>Ctrl+I: add pages to a book imported from images</li>
<li>Ctrl+E: export as text</li>
<li>Ctrl+Shift+E: export as HTML</li>
<li>Ctrl+H: open HTML view</li>
<li>Alt+C or Escape: close the reader</li>
</ul>

<h2>Troubleshooting</h2>
<ul>
<li>Limit or quota message: wait for the provider's allowance to reset,
then select Process again.</li>
<li>Server error such as 503: wait a few minutes and retry.</li>
<li>Model not found: open Settings, select Refresh model list, and choose
an available model.</li>
<li>Request too large: reduce Pages per request in Settings.</li>
<li>Incorrect or malformed page text: choose another model and reprocess
the affected pages.</li>
</ul>

<h2>Help and feedback</h2>
<p>The Help menu contains links to the project page, issue tracker, and
developer contact information.</p>
"""

_MANUAL_STYLE = """
body { font-family: sans-serif; max-width: 46em; margin: 1em auto;
       padding: 0 1em; line-height: 1.6; }
h1 { font-size: 1.6em; }
h2 { font-size: 1.3em; margin-top: 1.4em; }
h3 { font-size: 1.1em; margin-top: 1em; }
li { margin: 0.3em 0; }
"""


def manual_html():
    """Return the complete user manual as an HTML document."""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        "<title>%s — User Manual</title>\n"
        "<style>%s</style>\n</head>\n<body>\n%s\n</body>\n</html>"
        % (config.APP_NAME, _MANUAL_STYLE, _MANUAL_BODY)
    )
