"""
GigaAM бэкенд для распознавания речи.
https://github.com/salute-developers/GigaAM
"""

import tempfile
import wave
from typing import Generator, Optional

from nerd_dictation_ex.backends.base import ASRBackend, ASRResult


class GigaAMBackend(ASRBackend):
    """
    Бэкенд на основе GigaAM (GPU, batch).

    GigaAM не поддерживает настоящий стриминг — аудио накапливается
    и распознаётся по чанкам (~25 секунд максимум).
    """

    name = "gigaam"
    supports_streaming = False  # Псевдо-стриминг через буферизацию

    # Доступные модели GigaAM
    MODELS = {
        "v3_ctc": "Быстрая CTC модель",
        "v3_rnnt": "Точная RNNT модель",
        "v3_e2e_ctc": "End-to-end CTC с пунктуацией",
        "v3_e2e_rnnt": "End-to-end RNNT с пунктуацией (лучшее качество)",
    }

    def __init__(self, model_name: str = "v3_ctc", device: str = "cuda"):
        """
        Args:
            model_name: Имя модели GigaAM (v3_ctc, v3_rnnt, v3_e2e_ctc, v3_e2e_rnnt)
            device: Устройство для инференса (cuda/cpu)
        """
        self._model = None
        self._model_name = model_name
        self._device = device
        self._buffer = bytearray()
        self._sample_rate = 16000
        # Максимум ~25 секунд аудио для GigaAM
        self._max_buffer_samples = 25 * self._sample_rate * 2  # 16-bit = 2 bytes

    def load_model(self, model_path: str = None, **kwargs) -> None:
        """
        Загрузить модель GigaAM.

        Args:
            model_path: Игнорируется, модель загружается по имени
            device: "cuda", "cpu", или "auto" (попробовать cuda, fallback на cpu)
        """
        import sys

        try:
            import gigaam
        except ImportError:
            raise ImportError(
                "GigaAM не установлен. Установите:\n"
                "  git clone https://github.com/salute-developers/GigaAM\n"
                "  cd GigaAM && pip install -e ."
            )

        model_name = kwargs.get("model_name", self._model_name)
        device = kwargs.get("device", self._device)

        if model_name not in self.MODELS:
            available = ", ".join(self.MODELS.keys())
            raise ValueError(f"Неизвестная модель: {model_name}. Доступны: {available}")

        self._model = gigaam.load_model(model_name)

        # Определяем устройство
        if device in ("cuda", "auto"):
            import torch
            if torch.cuda.is_available():
                try:
                    # Пробуем загрузить на GPU и выполнить тестовый inference
                    self._model = self._model.cuda()
                    # Тест: создаём маленький тензор и проверяем что CUDA работает
                    test_tensor = torch.zeros(1, device="cuda")
                    del test_tensor
                    self._device = "cuda"
                    print("[gigaam] Используется CUDA", file=sys.stderr)
                except RuntimeError as e:
                    if "no kernel image" in str(e) or "CUDA" in str(e):
                        print(f"[gigaam] CUDA недоступна для этого GPU: {e}", file=sys.stderr)
                        print("[gigaam] Переключаюсь на CPU", file=sys.stderr)
                        self._model = self._model.cpu()
                        self._device = "cpu"
                    else:
                        raise
            else:
                if device == "cuda":
                    print("[gigaam] CUDA недоступна, используется CPU", file=sys.stderr)
                self._device = "cpu"
        else:
            self._device = "cpu"
            print("[gigaam] Используется CPU", file=sys.stderr)

    def transcribe_stream(
        self,
        audio_stream: Generator[bytes, None, None],
        sample_rate: int = 16000,
    ) -> Generator[ASRResult, None, None]:
        """
        Псевдо-потоковое распознавание.

        Накапливает аудио в буфер и распознаёт при достижении лимита.
        """
        if self._model is None:
            raise RuntimeError("Модель не загружена. Вызовите load_model() сначала.")

        self._sample_rate = sample_rate

        for chunk in audio_stream:
            self._buffer.extend(chunk)

            # Распознаём когда буфер заполнен
            if len(self._buffer) >= self._max_buffer_samples:
                text = self._transcribe_buffer()
                if text:
                    yield ASRResult(text=text, is_final=True)
                self._buffer.clear()

    def finalize(self) -> Optional[ASRResult]:
        """Распознать оставшееся аудио в буфере."""
        if len(self._buffer) > 0:
            text = self._transcribe_buffer()
            self._buffer.clear()
            if text:
                return ASRResult(text=text, is_final=True)
        return None

    def _transcribe_buffer(self) -> str:
        """Распознать аудио из буфера."""
        if len(self._buffer) == 0:
            return ""

        # Сохраняем буфер во временный WAV файл
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name
            with wave.open(f, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self._sample_rate)
                wf.writeframes(bytes(self._buffer))

        try:
            return self._model.transcribe(temp_path)
        finally:
            import os
            os.unlink(temp_path)

    def transcribe_file(self, audio_path: str) -> str:
        """Распознать аудиофайл."""
        if self._model is None:
            raise RuntimeError("Модель не загружена. Вызовите load_model() сначала.")
        return self._model.transcribe(audio_path)

    def reset(self) -> None:
        """Сбросить буфер."""
        self._buffer.clear()
