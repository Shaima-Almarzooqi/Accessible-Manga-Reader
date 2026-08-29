# Third-party notices

Accessible Manga Reader is free software under the GNU General Public
License version 3 or later. The full text is in [LICENSE](LICENSE), and
the complete source for every release is in this repository.

The components below are distributed under their own licences, all of which
are compatible with GPL v3.

## Included in the downloads

| Component | Purpose | Licence |
| --- | --- | --- |
| [wxPython](https://wxpython.org/) | User interface | wxWindows Library Licence |
| [Requests](https://requests.readthedocs.io/) | API requests | Apache 2.0 |
| [Pillow](https://python-pillow.org/) | Image processing | MIT-CMU |
| [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) | PDF import and export validation | Apache 2.0 / BSD-3-Clause |
| [lameenc](https://github.com/chrisstaite/lameenc) | Writing MP3 files | LGPL 2.1 (LAME) |
| [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) | Offline speech generation | MIT |
| [ONNX Runtime](https://onnxruntime.ai/) | Offline model runtime | MIT |
| [Misaki](https://github.com/hexgrad/misaki) | Offline speech phonemization | Apache 2.0 |
| [eSpeak NG](https://github.com/espeak-ng/espeak-ng) | Offline speech phonemization | GPL v3 or later |
| [phonemizer-fork](https://github.com/thewh1teagle/phonemizer-fork) | Offline speech phonemization | GPL v3 or later |

## Downloaded for offline speech

The offline voice model is downloaded from a kokoro-onnx release on first use
and verified against a known checksum.

| Component | Licence |
| --- | --- |
| [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) model weights and voices | Apache 2.0 |

Kokoro is built on [StyleTTS 2](https://github.com/yl4579/StyleTTS2) and
was trained partly on permissively licensed audio, including CC BY
material. Its model card lists those sources in full.

## Exported content

The licences above do not apply to exported text or audio. Copyright in the
source comic remains separate from the application and speech components.
