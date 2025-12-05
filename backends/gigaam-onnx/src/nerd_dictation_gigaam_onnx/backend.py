"""
GigaAM ONNX бэкенд для распознавания речи на GPU через ONNX Runtime.

Использует onnx-asr для загрузки GigaAM моделей и Silero VAD для сегментации.
Поддерживает GPU с CUDA (включая SM_61 — Pascal архитектура).
"""

import sys
import tempfile
import wave
from typing import Generator, Optional

import numpy as np

from nerd_dictation_ex.backends.base import ASRBackend, ASRResult


class GigaAMOnnxBackend(ASRBackend):
    """
    Бэкенд на основе GigaAM через ONNX Runtime с VAD-сегментацией.

    Преимущества:
    - Поддержка GPU через ONNX Runtime (включая старые Pascal GPU)
    - Быстрее PyTorch на некоторых конфигурациях
    - Меньше потребление памяти
    """

    name = "gigaam-onnx"
    supports_streaming = False  # Псевдо-стриминг через VAD

    # Доступные модели GigaAM через onnx-asr
    MODELS = {
        "v3-ctc": "gigaam-v3-ctc",
        "v3-rnnt": "gigaam-v3-rnnt",
        "v3-e2e-ctc": "gigaam-v3-e2e-ctc",
        "v3-e2e-rnnt": "gigaam-v3-e2e-rnnt",
        "v2-ctc": "gigaam-v2-ctc",
        "v2-rnnt": "gigaam-v2-rnnt",
    }

    # VAD параметры
    VAD_THRESHOLD = 0.5
    MIN_SILENCE_MS = 500
    MIN_SPEECH_MS = 250

    def __init__(self, model_name: str = "v3-ctc", device: str = "cuda"):
        """
        Args:
            model_name: Имя модели (v3-ctc, v3-rnnt, v3-e2e-ctc, v3-e2e-rnnt, v2-ctc, v2-rnnt)
            device: Устройство для инференса (cuda/cpu/auto)
        """
        self._model = None
        self._vad_model = None
        self._model_name = model_name
        self._device = device
        self._buffer = bytearray()
        self._sample_rate = 16000
        self._max_buffer_samples = 25 * self._sample_rate * 2  # ~25 секунд
        # VAD состояние
        self._silence_samples = 0
        self._speech_samples = 0
        self._in_speech = False
        self._vad_buffer = bytearray()

    def _load_vad(self) -> None:
        """Загрузить Silero VAD модель."""
        if self._vad_model is not None:
            return

        import torch
        print("[gigaam-onnx] Загружаю Silero VAD...", file=sys.stderr)
        self._vad_model, _ = torch.hub.load(
            repo_or_dir='snakers4/silero-vad',
            model='silero_vad',
            force_reload=False,
            onnx=False,
            trust_repo=True,
        )
        self._vad_model.eval()
        print("[gigaam-onnx] Silero VAD загружен", file=sys.stderr)

    def _get_providers(self, device: str) -> list:
        """Получить список ONNX провайдеров для устройства."""
        import onnxruntime as ort
        available = ort.get_available_providers()

        if device == "cuda" or device == "auto":
            if "CUDAExecutionProvider" in available:
                return ["CUDAExecutionProvider", "CPUExecutionProvider"]
            elif device == "cuda":
                print("[gigaam-onnx] CUDA недоступна, используется CPU", file=sys.stderr)
        return ["CPUExecutionProvider"]

    def load_model(self, model_path: str = None, **kwargs) -> None:
        """
        Загрузить модель GigaAM ONNX и VAD.

        Args:
            model_path: Путь к локальной модели (опционально)
            model_name: Имя модели (v3-ctc, v3-rnnt, и т.д.)
            device: "cuda", "cpu", или "auto"
        """
        try:
            import onnx_asr
        except ImportError:
            raise ImportError(
                "onnx-asr не установлен. Установите:\n"
                "  pip install onnx-asr huggingface_hub"
            )

        model_name = kwargs.get("model_name", self._model_name)
        device = kwargs.get("device", self._device)

        if model_name not in self.MODELS:
            available = ", ".join(self.MODELS.keys())
            raise ValueError(f"Неизвестная модель: {model_name}. Доступны: {available}")

        onnx_model_name = self.MODELS[model_name]
        providers = self._get_providers(device)

        print(f"[gigaam-onnx] Загружаю модель {onnx_model_name}...", file=sys.stderr)
        print(f"[gigaam-onnx] Провайдеры: {providers}", file=sys.stderr)

        self._model = onnx_asr.load_model(
            onnx_model_name,
            path=model_path,
            providers=providers,
        )

        # Определяем реальное устройство
        if "CUDAExecutionProvider" in providers:
            self._device = "cuda"
            print("[gigaam-onnx] Используется CUDA", file=sys.stderr)
        else:
            self._device = "cpu"
            print("[gigaam-onnx] Используется CPU", file=sys.stderr)

        # Загружаем VAD
        self._load_vad()
        print("[gigaam-onnx] Модель загружена и готова", file=sys.stderr)

    def _bytes_to_float(self, audio_bytes: bytes) -> "torch.Tensor":
        """Конвертировать PCM16 bytes в float tensor для VAD."""
        import torch
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

        self._vad_buffer.extend(chunk)

        vad_chunk_samples = 512
        vad_chunk_bytes = vad_chunk_samples * 2

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

        min_silence = int(self.MIN_SILENCE_MS * self._sample_rate / 1000)
        min_speech = int(self.MIN_SPEECH_MS * self._sample_rate / 1000)

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
        """
        if self._model is None:
            raise RuntimeError("Модель не загружена. Вызовите load_model() сначала.")

        self._sample_rate = sample_rate
        self._reset_vad_state()

        for chunk in audio_stream:
            self._buffer.extend(chunk)

            should_transcribe = self._check_vad(chunk)

            if should_transcribe or len(self._buffer) >= self._max_buffer_samples:
                if len(self._buffer) > 0:
                    text = self._transcribe_buffer()
                    if text:
                        print(f"[gigaam-onnx] распознано: '{text}'", file=sys.stderr)
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
        import time

        if len(self._buffer) == 0:
            return ""

        # Конвертируем в float32 numpy array
        audio_int16 = np.frombuffer(bytes(self._buffer), dtype=np.int16)
        audio_float = audio_int16.astype(np.float32) / 32768.0

        audio_duration = len(audio_float) / self._sample_rate
        start_time = time.time()

        # onnx-asr принимает numpy array напрямую
        result = self._model.recognize(audio_float, sample_rate=self._sample_rate)

        inference_time = time.time() - start_time
        rtf = inference_time / audio_duration if audio_duration > 0 else 0
        print(f"[gigaam-onnx] инференс: {inference_time:.3f}с для {audio_duration:.2f}с аудио (RTF={rtf:.2f})", file=sys.stderr)

        return result.strip() if result else ""

    def transcribe_file(self, audio_path: str) -> str:
        """Распознать аудиофайл."""
        if self._model is None:
            raise RuntimeError("Модель не загружена. Вызовите load_model() сначала.")
        return self._model.recognize_file(audio_path)

    def reset(self) -> None:
        """Сбросить буфер и VAD."""
        self._buffer.clear()
        self._reset_vad_state()
