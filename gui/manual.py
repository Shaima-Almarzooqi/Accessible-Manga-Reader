"""The in-app user manual, shown from the Help menu.

Rendered as an HTML document so screen reader browse mode can navigate
it by heading (H, and the number keys for heading levels). The text is
deliberately plain and step-by-step for readers new to the app.
"""

from core import config

_MANUAL_BODY = """
<h1>Accessible Manga Reader — User Manual</h1>

<h2>Before you start: what you need</h2>
<p>Accessible Manga Reader does not come with any manga. It reads manga
files that you already have on your computer. So the first step is to
have a manga volume or chapter saved as one of these file types:</p>
<ul>
<li>A CBZ file (the most common format for digital manga)</li>
<li>A ZIP file containing the page images</li>
<li>A PDF file</li>
<li>A folder of image files, or the image files themselves, one image
per page</li>
</ul>
<p>You can obtain manga in these formats from digital manga stores, from
services you subscribe to, or from other sources on the internet. Please
support creators by buying manga where you can. Once you have a file
saved on your computer, you are ready to begin.</p>

<h2>What this app does</h2>
<p>Manga tells its story through drawings: the words are part of the
artwork, and much of the meaning comes from pictures, facial
expressions, and sound effects rather than dialogue alone. Ordinary
screen readers cannot read any of this.</p>
<p>Accessible Manga Reader sends each page to an AI service that can see
images, and turns the page into text you can read with your screen
reader. For every page you get a description of each panel, the dialogue
with the name of the character speaking, the sound effects and what they
mean, and descriptions of silent moments. You read the result as
ordinary text.</p>

<h2>Step 1: Get an API key</h2>
<p>The app needs an AI service to read the pages for you. It does not
include one, so you sign up for one and give the app a key. A key is a
long password that lets the app use the service on your behalf.</p>
<p>The easiest free option is Google Gemini:</p>
<ol>
<li>Open your web browser and go to
<a href="https://aistudio.google.com">aistudio.google.com</a>.</li>
<li>Sign in with a Google account.</li>
<li>Find the button labelled Get API key and select it.</li>
<li>Create a key, then copy it. No credit card is required.</li>
</ol>
<p>Google's free level is generous, enough for hundreds of manga pages
per day.</p>
<p>Other services work too. OpenRouter (openrouter.ai) also has a free
option and only needs an email address. Claude and ChatGPT work if you
have paid access to their APIs. There is also an option for any other
compatible service if you know its address.</p>

<h2>Step 2: Enter your key in the app</h2>
<ol>
<li>Open the app.</li>
<li>Press Alt plus S to open Settings.</li>
<li>You will land on the AI engine tab. Choose your service in the
service list; Gemini is the default.</li>
<li>In the API keys box, paste your key. You can paste more than one
key, one per line; when one key runs out for the day, the app moves to
the next automatically.</li>
<li>Select OK.</li>
</ol>
<p>You only do this once. Your key is saved on your computer and is
never sent anywhere except to the service you chose.</p>

<h2>Step 3: Add a manga to your library</h2>
<p>The main window shows your library, which starts empty. To add a
book, open the File menu and choose how to import it:</p>
<ul>
<li>Import archive or PDF, for a CBZ, ZIP, or PDF file. The shortcut is
Ctrl plus O.</li>
<li>Import image files, to pick the page images yourself. The shortcut
is Ctrl plus I.</li>
<li>Import folder of images, for a whole folder of pages. The shortcut
is Ctrl plus Shift plus I.</li>
</ul>
<p>Choose your file, and the book appears in your library list.</p>

<h2>Step 4: Process the book</h2>
<p>Processing is when the app reads every page with the AI and saves the
results. This happens once per book.</p>
<ol>
<li>Select the book in your library.</li>
<li>Press Alt plus P to process it.</li>
<li>First you are offered a box for optional notes to the AI. The most
useful thing to add here is the cast: the characters' names and a short
description of each, for example, "Aiko: short dark hair, school
uniform, the class representative. Kenta: messy hair, always late." The
AI will then use those names from the first page instead of guessing.
You can also leave this empty.</li>
<li>Select Save and process to begin.</li>
</ol>
<p>If you prefer not to see this box each time, turn off "Ask for AI
instructions before processing a book" in Settings. Processing then
starts immediately, and the instructions stay available from the Book
menu, where Save and reprocess applies new instructions to a book that
is already processed.</p>
<p>A progress window opens and tells you how far along it is. Processing
a whole volume can take several minutes, because each page is sent to
the AI in turn. You can cancel at any time; everything done so far is
saved, and choosing Process again later continues from where it stopped.
If you reach a service's daily limit partway through, the same applies:
come back later and continue.</p>

<h2>Step 5: Read</h2>
<p>When the book is ready, select it and press Enter, or Alt plus R. The
reader window opens.</p>
<p>There are three ways to read, which you choose from the View menu, or
set a default in Settings:</p>
<ul>
<li>Entire book, one continuous document. This is best for reading
straight through with your screen reader's say-all command.</li>
<li>One page at a time, with a line telling you which page you are
on.</li>
<li>One panel at a time, the closest to how a sighted reader takes in a
page one piece at a time. Each panel tells you its position, for example
"Page 3 of 20, panel 2 of 6, top right", so you can picture the
page.</li>
</ul>
<p>In page and panel modes, use Page Down and Page Up to move forward
and back. In every mode, Ctrl plus Page Down and Ctrl plus Page Up move
between whole pages.</p>

<h3>Panel labels on or off</h3>
<p>By default the reader shows a short label before each panel, telling
you its number and position. If you prefer to read without these labels,
as flowing text, press Ctrl plus L, or open the View menu and turn off
Show panel labels. The story then reads continuously. You can turn this
on or off at any time; it changes only how the text is shown.</p>

<h3>Ask about a page</h3>
<p>If something in the description was unclear, you can ask the AI
about it directly. In the reader, press Ctrl plus Q, or use the Ask
button. Type your question, choose whether the AI should look at just
the current page, the surrounding pages, or a small range, then select
Ask. The AI looks at the original page images again, not just the
text, so it can clarify details the description missed, and it knows
the characters from the book's notes. You can ask follow-up questions
in the same window, and copy the latest answer. The answers appear as a
formatted document: each question is a heading and each answer is a
heading under it, so in browse mode H moves through everything, 2 moves
from question to question, and 3 from answer to answer. The newest
exchange is at the end, so Control plus End jumps straight to it.</p>
<p>Your question appears in the document as soon as you send it, with a
note under its Answer heading saying the AI is working. While it works,
the Ask button becomes Stop; choosing Stop abandons that question right
away and gives you the Ask button back, leaving your question in the box
so you can ask it again.</p>
<p>Two things to know: each question uses your AI service the same way
processing does, so it counts toward your allowance; and it needs the
book's page images, so it is unavailable for a book whose images were
removed with Free up space.</p>

<h3>Speaker names, and what "Unknown" means</h3>
<p>Comic artists show who is talking by drawing a small pointer on the
speech bubble, called a tail, aimed at the character saying the line.
The AI reads that tail first, before considering which character is
nearest the bubble, because bubbles are often placed near a listener
rather than the speaker. Each comic type follows the conventions of its
own tradition.</p>
<p>Some bubbles are drawn with no tail at all, and on a crowded page
the speaker is sometimes genuinely impossible to establish. In those
cases the AI writes "Unknown" instead of choosing a likely name, and
"Off-panel voice" when someone is speaking from outside the panel.
Seeing "Unknown" occasionally is the app working correctly: a wrong
name would quietly change the story, and an honest "Unknown" leaves you
free to work it out from the dialogue.</p>
<p>Two things improve the names. First, give the cast in the AI
instructions for the book, as described under Processing a book: names
with a short description of each let the AI recognise characters from
the very first page. Second, if a line still looks wrong, press Ctrl
plus Q and ask about that page. The AI looks at the original artwork
again and can tell you who the tail actually points at.</p>

<h3>HTML view</h3>
<p>For a different way to navigate, press Ctrl plus H to open the HTML
view. This shows the whole book in a window where each page and each
panel is a heading. With your screen reader's browse mode you can jump
by heading using the H key, jump between pages with the 2 key, and jump
between panels with the 3 key. From that window you can also save the
book as an HTML file to keep or open elsewhere.</p>

<h2>Other things you can do</h2>

<h3>Save a book as text</h3>
<p>In the reader, press Ctrl plus E to save the whole book as a plain
text file you can keep, share, or open in any program.</p>

<h3>Change how detailed the descriptions are</h3>
<p>In Settings, on the General tab, the Verbosity option controls how
much the AI describes:</p>
<ul>
<li>Concise, a short line per panel, for quick reading.</li>
<li>Detailed, a fuller description of action and expressions.</li>
<li>Extensive, the most thorough, describing composition, each
character's expression and pose, the background, and drawn effects.</li>
</ul>
<p>At every level, the AI is told to describe only what is actually
drawn, without adding its own opinions.</p>

<h3>Read in another language</h3>
<p>Also on the General tab, Output language sets the language of the
descriptions and dialogue. Choose from the list or type any language.
The text is translated into it and transcribed as it appears.</p>

<h3>Choose the comic type</h3>
<p>On the General tab, Comic type tells the app how the pages should be
read, which affects the order of panels and text:</p>
<ul>
<li>Manga, for Japanese comics, read right to left.</li>
<li>Manhwa or Manhua, for Korean or Chinese comics, read left to right,
usually as a vertical scroll in colour.</li>
<li>Webtoon, for vertical-scroll comics read top to bottom.</li>
<li>Western comic, read left to right.</li>
</ul>
<p>Set this to match what you are reading before you process a book, so
the panels come out in the right order.</p>

<h3>Add your own instructions for a comic type</h3>
<p>Below the comic type is a box for your own instructions for that
type. Anything you put there is applied to every book you read as that
type, so it is useful for a preference you always want, such as how much
to describe backgrounds. Each comic type has its own box. This is
separate from the notes you can give a single book, described below; if
both are set, the book's own notes take priority.</p>

<h3>Give the AI notes about a book</h3>
<p>To add or change the notes for a book, such as character names,
select it in the library and press Ctrl plus T. Save keeps your notes
for later; Save and reprocess applies them right away by processing the
book again. Notes affect pages processed after you add them.</p>

<h3>Free up disk space</h3>
<p>After a book is fully processed, its page images are no longer needed
for reading. To reclaim the space, select the book, open the Book menu,
and choose Free up space. The book stays fully readable.</p>

<h3>Updates</h3>
<p>The app can check for new versions when it starts and tell you when
one is available, showing what has changed and offering to open the
download page. You can turn this off, or choose not to be told about
beta versions, in Settings.</p>

<h2>Keyboard shortcuts</h2>
<p>In the library:</p>
<ul>
<li>Enter, or Alt plus R: read the selected book</li>
<li>Alt plus P, or Ctrl plus P: process or continue processing</li>
<li>Alt plus S: open Settings</li>
<li>Ctrl plus T: notes for the selected book</li>
<li>F2: rename. Delete: remove. Ctrl plus A: select all</li>
<li>The Applications key opens a menu with every action for a book</li>
</ul>
<p>In the reader:</p>
<ul>
<li>Page Down and Page Up: next and previous page or panel</li>
<li>Ctrl plus Page Down and Ctrl plus Page Up: next and previous page in
any mode</li>
<li>Alt plus G, or Ctrl plus G: go to a page</li>
<li>Ctrl plus F: find text</li>
<li>Ctrl plus L: show or hide panel labels</li>
<li>Ctrl plus Q: ask about the current page</li>
<li>Ctrl plus E: save as a text file</li>
<li>Ctrl plus H: open the HTML view</li>
<li>Alt plus C, or Escape: close the reader</li>
</ul>

<h2>If something goes wrong</h2>
<ul>
<li>If processing stops with a message about a limit or quota, you have
reached the service's daily free allowance. Wait until it resets, then
choose Process again to continue. Nothing is lost.</li>
<li>If processing stops with a server error such as 503, the service's
servers are temporarily overloaded. This is not caused by your key or
settings; wait a few minutes and choose Process again.</li>
<li>If a message says a model was not found, open Settings and use
Refresh model list to see the models your key can use, then pick
one.</li>
<li>If a request is refused for being too large, lower Pages per request
in Settings.</li>
</ul>

<h2>Getting help and giving feedback</h2>
<p>This app is in beta, which means it is still being improved. If
something does not work or you have a suggestion, you can reach the
developer from the Help menu:</p>
<ul>
<li>Visit project page on GitHub, to open the project's main page.</li>
<li>Report a problem, to open the page where you can describe an issue
or suggestion.</li>
<li>Contact developer by email, to show the developer's email address
with a button to copy it.</li>
</ul>
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
