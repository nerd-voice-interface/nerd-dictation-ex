"""
GigaAM бэкенд для распознавания речи.
https://github.com/salute-developers/GigaAM

Использует Silero VAD для определения пауз в речи и сегментации аудио.
"""

import sys
import tempfile
import wave
from typing import Generator, Optional

import numpy as np
import torch

from nerd_dictation_ex.backends.base import ASRBackend, ASRResult


class GigaAMBackend(ASRBackend):
    """
    Бэкенд на основе GigaAM (GPU, batch) с VAD-сегментацией.

    Использует Silero VAD для определения пауз в речи.
    При обнаружении паузы накопленное аудио отправляется на распознавание.
    """

    name = "gigaam"
    supports_streaming = False  # Псевдо-стриминг через VAD

    # Доступные модели GigaAM
    MODELS = {
        "v3_ctc": "Быстрая CTC модель",
        "v3_rnnt": "Точная RNNT модель",
        "v3_e2e_ctc": "End-to-end CTC с пунктуацией",
        "v3_e2e_rnnt": "End-to-end RNNT с пунктуацией (лучшее качество)",
    }

    # VAD параметры
    VAD_THRESHOLD = 0.5  # Порог вероятности речи
    MIN_SILENCE_MS = 500  # Минимальная пауза для сегментации (мс)
    MIN_SPEECH_MS = 250  # Минимальная длина речи (мс)

    def __init__(self, model_name: str = "v3_ctc", device: str = "cuda"):
        """
        Args:
            model_name: Имя модели GigaAM (v3_ctc, v3_rnnt, v3_e2e_ctc, v3_e2e_rnnt)
            device: Устройство для инференса (cuda/cpu)
        """
        self._model = None
        self._vad_model = None
        self._model_name = model_name
        self._device = device
        self._buffer = bytearray()
        self._sample_rate = 16000
        # Максимум ~25 секунд аудио для GigaAM
        self._max_buffer_samples = 25 * self._sample_rate * 2  # 16-bit = 2 bytes
        # VAD состояние
        self._silence_samples = 0
        self._speech_samples = 0
        self._in_speech = False
        self._vad_buffer = bytearray()  # Буфер для накопления аудио для VAD

    def _load_vad(self) -> None:
        """Загрузить Silero VAD модель."""
        if self._vad_model is not None:
            return

        print("[gigaam] Загружаю Silero VAD...", file=sys.stderr)
        self._vad_model, _ = torch.hub.load(
            repo_or_dir='snakers4/silero-vad',
            model='silero_vad',
            force_reload=False,
            onnx=False,
            trust_repo=True,
        )
        self._vad_model.eval()
        print("[gigaam] Silero VAD загружен", file=sys.stderr)

    def load_model(self, model_path: str = None, **kwargs) -> None:
        """
        Загрузить модель GigaAM и VAD.

        Args:
            model_path: Игнорируется, модель загружается по имени
            device: "cuda", "cpu", или "auto" (попробовать cuda, fallback на cpu)
        """
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
            if torch.cuda.is_available():
                try:
                    self._model = self._model.cuda()
                    test_tensor = torch.zeros(1, device="cuda")
                    del test_tensor
                    self._device = "cuda"
                    print("[gigaam] Используется CUDA", file=sys.stderr)
                except RuntimeError as e:
                    if "no kernel image" in str(e) or "CUDA" in str(e):
                        print(f"[gigaam] CUDA недоступна для этого GPU: {e}", file=sys.stderr)
                        print("[gigaam] Переключаюсь на CPU", file=sys.stderr)
                        self._model = self._model.cpu().float()
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

        # Загружаем VAD
        self._load_vad()

    def _bytes_to_float(self, audio_bytes: bytes) -> torch.Tensor:
        """Конвертировать PCM16 bytes в float tensor для VAD."""
        audio_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
        audio_float = audio_int16.astype(np.float32) / 32768.0
        return torch.from_numpy(audio_float)

    def _check_vad(self, chunk: bytes) -> bool:
        """
        Проверить наличие речи в чанке через VAD.

        Returns:
            True если обнаружена пауза после речи (нужно распознать буфер)
        """
        if self._vad_model is None:
            return False

        # Накапливаем аудио для VAD (Silero требует минимум 512 samples)
        self._vad_buffer.extend(chunk)

        # Silero VAD работает с 16kHz, чанками по 512 samples (1024 bytes)
        vad_chunk_samples = 512
        vad_chunk_bytes = vad_chunk_samples * 2  # 16-bit = 2 bytes

        # Обрабатываем пока есть достаточно данных
        while len(self._vad_buffer) >= vad_chunk_bytes:
            vad_bytes = bytes(self._vad_buffer[:vad_chunk_bytes])
            del self._vad_buffer[:vad_chunk_bytes]

            audio_tensor = self._bytes_to_float(vad_bytes)
            prob = self._vad_model(audio_tensor, self._sample_rate).item()

            if prob >= self.VAD_THRESHOLD:
                self._speech_samples += vad_chunk_samples
                self._silence_samples = 0
                self._in_speech = True
            else:
                self._silence_samples += vad_chunk_samples

        # Минимальные пороги в samples
        min_silence = int(self.MIN_SILENCE_MS * self._sample_rate / 1000)
        min_speech = int(self.MIN_SPEECH_MS * self._sample_rate / 1000)

        # Если была речь и теперь достаточно тишины — пора распознавать
        if (self._in_speech and
            self._silence_samples >= min_silence and
            self._speech_samples >= min_speech):
            return True

        return False

    def transcribe_stream(
        self,
        audio_stream: Generator[bytes, None, None],
        sample_rate: int = 16000,
    ) -> Generator[ASRResult, None, None]:
        """
        VAD-управляемое потоковое распознавание.

        Накапливает аудио и распознаёт при обнаружении паузы в речи.
        """
        if self._model is None:
            raise RuntimeError("Модель не загружена. Вызовите load_model() сначала.")

        self._sample_rate = sample_rate
        self._reset_vad_state()

        for chunk in audio_stream:
            self._buffer.extend(chunk)

            # Проверяем VAD
            should_transcribe = self._check_vad(chunk)

            # Распознаём при паузе или переполнении буфера
            if should_transcribe or len(self._buffer) >= self._max_buffer_samples:
                if len(self._buffer) > 0:
                    text = self._transcribe_buffer()
                    if text:
                        print(f"[gigaam] распознано: '{text}'", file=sys.stderr)
                        yield ASRResult(text=text, is_final=True)
                    self._buffer.clear()
                    self._reset_vad_state()

    def _reset_vad_state(self) -> None:
        """Сбросить состояние VAD."""
        self._silence_samples = 0
        self._speech_samples = 0
        self._in_speech = False
        self._vad_buffer.clear()
        if self._vad_model is not None:
            self._vad_model.reset_states()

    def finalize(self) -> Optional[ASRResult]:
        """Распознать оставшееся аудио в буфере."""
        if len(self._buffer) > 0:
            text = self._transcribe_buffer()
            self._buffer.clear()
            self._reset_vad_state()
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
        """Сбросить буфер и VAD."""
        self._buffer.clear()
        self._reset_vad_state()
