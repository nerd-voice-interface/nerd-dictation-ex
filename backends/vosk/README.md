# nerd-dictation-vosk

Vosk бэкенд для [nerd-dictation-ex](https://github.com/marcusmae/nerd-dictation-ex).

## Особенности

- **CPU**: Работает на любом процессоре, GPU не требуется
- **Потоковое распознавание**: Текст появляется в реальном времени
- **Офлайн**: Полностью локальная работа
- **Лёгкие модели**: От 45MB до 1.5GB

## Установка

```bash
pip install nerd-dictation-vosk
```

## Установка моделей

```bash
# Показать доступные модели
nerd-dictation-vosk-setup --list

# Установить маленькую модель (~45MB, быстрая)
nerd-dictation-vosk-setup --model small

# Установить большую модель (~1.5GB, точная)
nerd-dictation-vosk-setup --model large

# Установить английскую модель
nerd-dictation-vosk-setup --model small-en
```

Модели устанавливаются в `~/.local/share/vosk/`.

## Конфигурация

В `~/.config/nerd-dictation-ex/config.toml`:

```toml
[general]
backend = "vosk"

[vosk]
# Путь к модели (по умолчанию: ~/.local/share/vosk/vosk-model-ru)
model_path = "~/.local/share/vosk/vosk-model-ru"
```

## Качество распознавания

| Модель | WER (русский) | Скорость |
|--------|---------------|----------|
| small  | ~35-40%       | Быстрая  |
| large  | ~30-33%       | Средняя  |

WER (Word Error Rate) — процент ошибок в словах. Меньше = лучше.

## Ссылки

- [Vosk](https://alphacephei.com/vosk/)
- [Модели Vosk](https://alphacephei.com/vosk/models)
- [Alphacephei: Русские модели](https://alphacephei.com/nsh/2024/04/14/russian-models.html)
