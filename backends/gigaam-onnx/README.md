# nerd-dictation-gigaam-onnx

GigaAM ONNX бэкенд для nerd-dictation-ex.

## Особенности

- **GPU через ONNX Runtime** — поддержка старых GPU (Pascal SM_61 и новее)
- **Автоматическая загрузка моделей** с Hugging Face
- **VAD-сегментация** через Silero VAD для псевдо-стриминга

## Установка

```bash
pip install nerd-dictation-gigaam-onnx
```

Для GPU нужен `onnxruntime-gpu` с поддержкой вашей видеокарты.

## Конфигурация

В `~/.config/nerd-dictation-ex/config.toml`:

```toml
[general]
backend = "gigaam-onnx"

[gigaam-onnx]
model_name = "v3-ctc"  # или v3-rnnt, v3-e2e-ctc, v3-e2e-rnnt
device = "cuda"        # или cpu, auto
```

## Модели

| Модель | Описание |
|--------|----------|
| v3-ctc | Быстрая CTC модель |
| v3-rnnt | Точнее, но медленнее |
| v3-e2e-ctc | С автоматической пунктуацией |
| v3-e2e-rnnt | Лучшее качество с пунктуацией |
| v2-ctc | Старая версия |
| v2-rnnt | Старая версия |

## Ссылки

- [GigaAM](https://github.com/salute-developers/GigaAM)
- [onnx-asr](https://github.com/istupakov/onnx-asr)
- [ONNX модели на Hugging Face](https://huggingface.co/istupakov/gigaam-v2-onnx)
