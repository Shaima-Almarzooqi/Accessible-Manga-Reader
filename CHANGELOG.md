# Changelog

All notable changes to Accessible Manga Reader are recorded here. The
newest version is at the top.

## 0.18.0

### Changed

- The output language setting now covers the whole script. Before, it
  reliably translated the comic's text but did not govern the panel
  descriptions, so a non-English setting could produce a mixed-language
  script. Now the descriptions and the dialogue are both written in the
  language you choose, English by default. Reading a comic that is
  itself in another language — a Spanish manga, say — now gives you a
  script entirely in English.
- The AI now works out a page's panel layout before it describes
  anything, then follows that map. Positions run in the page's own
  direction: right to left along each row for manga, left to right for
  manhwa and Western comics, and top to bottom in a single column for
  vertical webtoons, which have no left or right. Within a single
  panel it now sweeps the same way, so the rightmost bubble, character
  or object comes first in manga and the leftmost first in the others.
- Stricter output rules, mainly to stop Gemini models drifting. The AI
  is now told never to write about its own work, so remarks like "I
  forgot who said that" or "oops, wrong panel" no longer appear in a
  script; a page it gets wrong partway is simply written correctly
  rather than corrected out loud. It is also held to the panel format:
  some models were reorganising a page into general headings like
  Composition, Setting and Characters, or describing everything of one
  kind across the whole page at once, instead of going panel by panel
  in reading order. On the Extensive verbosity level the list of things
  to describe is now clearly a checklist to cover in flowing prose,
  rather than a set of headings to print.

Applies to pages processed from now on. Use Reprocess pages in the
Book menu to apply them to a book already processed.

## 0.17.0

### Added

- Reprocess pages. If a page came out badly you can now send just that
  page to the AI again, or a range of pages you choose, instead of
  redoing the whole book. Press Ctrl plus R in the reader to redo the
  page you are reading, or choose Reprocess pages from the Book menu
  in your library. Redoing a page or a range keeps the AI's character
  notes for the book; redoing the whole book starts them again.

## 0.16.0

### Added

- A Read now button in the processing window, so a book can be opened
  straight from there when processing finishes instead of going back
  to the library. It appears whenever pages have been processed,
  including after a cancelled run, and Enter selects it.

### Changed

- Better speaker identification. The AI now follows the speech
  bubble's tail, the small pointer aimed at whoever is talking, rather
  than the character sitting nearest the bubble, with the conventions
  of each comic type: bubbles chained into one speaker, tails pointing
  off the panel, thought and whisper and shouting bubbles, and caption
  boxes that are narration rather than dialogue.
- Ask about a page follows the same rules, so it can correct a wrong
  speaker in the script.

Applies to pages processed from now on. Use Reprocess pages in the
Book menu to apply them to a book already processed.

## 0.15.0

### Added

- Ask about a page (Ctrl+Q in the reader): type a question about the
  current page, nearby pages, or a small range, and the AI answers by
  looking at the original page images again. Questions and answers are
  headings, so browse mode moves between them; follow-up questions keep
  the earlier ones in mind; a question can be stopped while it is being
  answered; and the latest answer can be copied. Each question uses your
  AI service like processing does.
- Newer Gemini models in the model list, including Gemini 3.6 Flash and
  Gemini 3.5 Flash-Lite. Your current model is unchanged; pick another
  in Settings, or use Refresh model list to see what your key offers.

## 0.14.0

### Added

- A Settings option to skip the AI-instructions box when processing a
  book. Instructions remain available from the Book menu, which now has
  Save and Save and reprocess buttons, so new instructions can be
  applied to an already processed book directly.

### Changed

- Error messages now explain in plain language what went wrong and what
  to do about it, for example that a 503 means the service's servers
  are temporarily busy and processing can simply be resumed later.
- The default Gemini model is now gemini-3.5-flash, the strongest model
  on the free tier.
- The model choices for every service now list only current models that
  can read images. Refresh model list and typing a model by hand work as
  before.

## 0.13.0

### Added

- Comic type setting with correct reading rules for each: Manga
  (Japanese, right to left), Manhwa or Manhua (Korean or Chinese, left
  to right), Webtoon (vertical scroll), and Western comic (left to
  right). This replaces the old reading-direction setting; your previous
  choice is carried over.
- Custom instructions for each comic type, in Settings, applied to every
  book of that type. A book's own instructions still take priority.

### Changed

- Descriptions now tie each piece of text to the character, object, or
  moment it belongs to, instead of listing text on its own, and explain
  diagrams and other structured graphics in a clear order.
- The reader no longer adds or changes honorifics on its own; text is
  transcribed exactly as it appears.

## 0.12.0

### Changed

- PDF import now works on all versions of the app, including Windows on
  ARM (Snapdragon). PDF files were previously not supported on the ARM
  version.

## 0.11.1

### Fixed

- The HTML view now shows its content. The window could previously open
  empty on some systems.
- In the HTML view, Tab moves between the content and the buttons, while
  the arrow keys work inside the content, matching the rest of the app.

## 0.11.0

### Added

- User manual: a step-by-step guide is now in the Help menu, covering how
  to get an API key, add and process a book, read it, and every feature
  and shortcut.
- Update notifications: the app can check for a new version when it
  starts and tell you what has changed, with the option to open the
  download page. You can turn this off, or skip beta versions, in
  Settings.
- A shortcut, Ctrl plus L, to show or hide panel labels in the reader.
- Help menu links to the project page, problem reporting, and developer
  contact.

### Fixed

- The HTML view window is now announced with the book title, without
  extra technical words.

## 0.10.1

### Changed

- The HTML view now uses a lighter built-in display engine, so it opens
  faster and works more smoothly with screen readers.
- When you refresh the model list in Settings, it now shows only models
  that can read images, instead of every model the service offers.

### Fixed

- Corrected the display engine used by the packaged app so it matches
  what is used when running from source.

## 0.10.0

### Added

- HTML view (Ctrl+H): open the whole book in a separate window as a web
  page, with each page and panel as a heading, so screen reader browse
  mode can navigate with the H, 2, and 3 keys. It can also be saved as
  an HTML file (Ctrl+Shift+E).
- Continuous narrative mode: a "Show panel labels" option in the View
  menu and in Settings. With it off, the "Panel N" position markers are
  hidden and each page reads as continuous text. The processed text is
  unchanged, so switching is instant.
- Free up space: a Book menu option that removes a processed book's
  stored page images to reclaim disk space. Reading is unaffected.

### Changed

- Stricter right-to-left reading order. The AI is given a clear example
  of how to read a multi-row page, which improves the order of panels,
  speech bubbles, and text.
- The AI is now instructed to describe every panel and transcribe every
  piece of text on a page, without leaving anything out.

## 0.9.0

- First public release.
