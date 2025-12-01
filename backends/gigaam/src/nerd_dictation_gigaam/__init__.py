"""
nerd-dictation-gigaam — GigaAM бэкенд для nerd-dictation-ex.

GigaAM — модель от Сбера для распознавания русской речи.
Лучшее качество среди open-source моделей для русского языка.

Использование:
    pip install nerd-dictation-gigaam
    nerd-dictation-gigaam-setup  # установка GigaAM

Модели:
    - v3_ctc: быстрая, ~5-7% WER
    - v3_rnnt: точнее, медленнее
    - v3_e2e_ctc: с пунктуацией
    - v3_e2e_rnnt: лучшее качество с пунктуацией
"""

from .backend import GigaAMBackend

__version__ = "0.1.0"
__all__ = ["GigaAMBackend"]
