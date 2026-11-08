# Model licenses

| File | Source | License |
|---|---|---|
| `melspectrogram.onnx`, `embedding_model.onnx` | [openWakeWord](https://github.com/dscripka/openWakeWord) (shared feature extractor) | Apache-2.0 (code); pre-trained models CC BY-NC-SA 4.0 — non-commercial |
| `silero_vad.onnx` | [Silero VAD](https://github.com/snakers4/silero-vad), as bundled by openWakeWord | MIT |
| `extra/wall-e.onnx`, `extra/hey_zelda.onnx`, `extra/ronaldo_en.onnx` | [fwartner/home-assistant-wakewords-collection](https://github.com/fwartner/home-assistant-wakewords-collection) | MIT |
| `ronaldo_ptbr.onnx` | trained for this project with synthetic pt-BR voices (Piper), on top of the openWakeWord feature extractor | [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) © Thiago Guimarães — same terms as the openWakeWord models it depends on |
| `gol_grito.onnx` | trained for this project (goal-shout classifier) with synthetic pt-BR voices and public narration clips, on top of the openWakeWord feature extractor | [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) © Thiago Guimarães — same terms as the `ronaldo_ptbr` model |

The code in this repository is MIT (see [`LICENSE`](../LICENSE)); the models keep the licenses above.
