"""
nerd-dictation-gigaam-onnx — GigaAM ONNX бэкенд для nerd-dictation-ex.

GigaAM через ONNX Runtime с поддержкой GPU (включая старые Pascal GPU).
Использует onnx-asr для загрузки моделей с Hugging Face.

Использование:
    pip install nerd-dictation-gigaam-onnx

Модели:
    - v3-ctc: быстрая CTC модель
    - v3-rnnt: точнее, медленнее
    - v3-e2e-ctc: с пунктуацией
    - v3-e2e-rnnt: лучшее качество с пунктуацией
    - v2-ctc, v2-rnnt: старые версии
"""

from .backend import GigaAMOnnxBackend

__version__ = "0.1.0"
__all__ = ["GigaAMOnnxBackend"]
