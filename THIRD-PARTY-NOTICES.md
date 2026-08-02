# Third-party notices

Accessible Manga Reader is free software under the GNU General Public
License version 3 or later. The full text is in [LICENSE](LICENSE), and
the complete source for every release is in this repository.

The components below are used under their own licences. All of them are
compatible with GPL v3.

## Included in the downloads

| Component | Purpose | Licence |
| --- | --- | --- |
| [wxPython](https://wxpython.org/) | The application's windows and controls | wxWindows Library Licence |
| [Requests](https://requests.readthedocs.io/) | Talking to the AI services | Apache 2.0 |
| [Pillow](https://python-pillow.org/) | Reading and preparing page images | MIT-CMU |
| [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) | Importing PDFs, and checking exported ones are tagged | Apache 2.0 / BSD-3-Clause |
| [lameenc](https://github.com/chrisstaite/lameenc) | Writing MP3 files | LGPL 2.1 (LAME) |
| [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) | Running the offline voice model | MIT |
| [ONNX Runtime](https://onnxruntime.ai/) | Running the offline voice model | MIT |
| [Misaki](https://github.com/hexgrad/misaki) | Turning text into sounds for the offline voices | Apache 2.0 |
| [eSpeak NG](https://github.com/espeak-ng/espeak-ng) | Turning text into sounds for the offline voices | GPL v3 or later |
| [phonemizer-fork](https://github.com/thewh1teagle/phonemizer-fork) | Turning text into sounds for the offline voices | GPL v3 or later |
| [comtypes](https://github.com/enthought/comtypes) | Reaching the voices already installed on Windows | MIT |

## Downloaded when you first use an offline voice

The offline voice model is not part of the download. The application
fetches it from the kokoro-onnx releases the first time you choose an
offline voice, and checks it against a known checksum.

| Component | Licence |
| --- | --- |
| [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) model weights and voices | Apache 2.0 |

Kokoro is built on [StyleTTS 2](https://github.com/yl4579/StyleTTS2) and
was trained partly on permissively licensed audio, including CC BY
material. Its model card lists those sources in full.

## Audio and text you produce

Nothing you export is covered by the licences above. Copyright in the
comic you are reading is a separate matter, unaffected by this
application and by the voices that read it aloud.
