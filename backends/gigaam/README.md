# nerd-dictation-gigaam

GigaAM бэкенд для [nerd-dictation-ex](https://github.com/marcusmae/nerd-dictation-ex).

## Особенности

- **Лучшее качество для русского**: WER ~5-7% (vs ~33% у Vosk)
- **GPU ускорение**: CUDA для быстрого инференса
- **Пунктуация**: Модели e2e автоматически расставляют знаки препинания
- **Открытый код**: MIT лицензия от Сбера

## Требования

- NVIDIA GPU с CUDA (рекомендуется)
- ~1-2 GB VRAM для v3_ctc
- Или CPU (медленнее)

## Установка

```bash
pip install nerd-dictation-gigaam

# Установить GigaAM и проверить GPU
nerd-dictation-gigaam-setup

# Предзагрузить модель (опционально)
nerd-dictation-gigaam-setup --preload --model v3_ctc
```

## Модели

| Модель | Описание | Скорость | Пунктуация |
|--------|----------|----------|------------|
| v3_ctc | Быстрая CTC | ★★★ | ❌ |
| v3_rnnt | Точная RNNT | ★★ | ❌ |
| v3_e2e_ctc | End-to-end CTC | ★★ | ✅ |
| v3_e2e_rnnt | Лучшее качество | ★ | ✅ |

## Конфигурация

В `~/.config/nerd-dictation-ex/config.toml`:

```toml
[general]
backend = "gigaam"

[gigaam]
# Модель (v3_ctc, v3_rnnt, v3_e2e_ctc, v3_e2e_rnnt)
model_name = "v3_ctc"

# Устройство (cuda или cpu)
device = "cuda"
```

## Ограничения

- Не поддерживает настоящий стриминг (batch по ~25 секунд)
- Требует GPU для комфортной работы
- Только русский язык

## Ссылки

- [GigaAM (GitHub)](https://github.com/salute-developers/GigaAM)
- [GigaAM Paper](https://arxiv.org/html/2506.01192)
- [Alphacephei: Сравнение моделей](https://alphacephei.com/nsh/2025/04/18/russian-models.html)
