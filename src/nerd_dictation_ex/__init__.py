"""
nerd-dictation-ex — расширенная диктовка для Linux.

Модульная система с подключаемыми бэкендами ASR:
- nerd-dictation-vosk: Vosk (CPU, потоковый)
- nerd-dictation-gigaam: GigaAM (GPU, высокое качество)

Использование:
    pip install nerd-dictation-ex
    pip install nerd-dictation-vosk  # или nerd-dictation-gigaam

    nerd-dictation-ex begin
    nerd-dictation-ex end
"""

__version__ = "0.1.0"

from .backends import ASRBackend, ASRResult, get_backend, get_available_backends, list_backends

__all__ = [
    "__version__",
    "ASRBackend",
    "ASRResult",
    "get_backend",
    "get_available_backends",
    "list_backends",
]
