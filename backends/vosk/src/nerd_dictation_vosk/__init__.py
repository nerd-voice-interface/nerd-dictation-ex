"""
nerd-dictation-vosk — Vosk бэкенд для nerd-dictation-ex.

Vosk — это офлайн распознавание речи на базе Kaldi.
Работает на CPU, поддерживает потоковое распознавание.

Использование:
    pip install nerd-dictation-vosk
    nerd-dictation-vosk-setup --model small  # или large

Модели для русского языка:
    - small (~45MB): vosk-model-small-ru-0.22
    - large (~1.5GB): vosk-model-ru-0.42
"""

from .backend import VoskBackend

__version__ = "0.1.0"
__all__ = ["VoskBackend"]
