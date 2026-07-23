# Changelog

All notable changes to Accessible Manga Reader are recorded here. The
newest version is at the top.

## 0.16.0

### Changed

- Better speaker identification. The AI now follows the speech
  bubble's tail, the small pointer aimed at whoever is talking, rather
  than the character sitting nearest the bubble, with the conventions
  of each comic type: bubbles chained into one speaker, tails pointing
  off the panel, thought and whisper and shouting bubbles, and caption
  boxes that are narration rather than dialogue.
- Where the speaker cannot be worked out, the AI now says "Unknown"
  instead of guessing a name, so a book may show a few more of these
  than before.
- Ask about a page follows the same rules, so it can correct a wrong
  speaker in the script.

Applies to pages processed from now on. Use Reprocess entire book in
the Book menu to apply them to a book already processed.

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
