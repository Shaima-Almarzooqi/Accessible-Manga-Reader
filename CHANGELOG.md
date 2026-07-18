# Changelog

All notable changes to Accessible Manga Reader are recorded here. The
newest version is at the top.

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
