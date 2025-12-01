"""
Vosk бэкенд для распознавания речи.
https://alphacephei.com/vosk/
"""

import json
from typing import Generator, Optional

from nerd_dictation_ex.backends.base import ASRBackend, ASRResult


class VoskBackend(ASRBackend):
    """Бэкенд на основе Vosk (CPU, потоковый)."""

    name = "vosk"
    supports_streaming = True

    def __init__(self):
        self._model = None
        self._recognizer = None

    def load_model(self, model_path: str, sample_rate: int = 16000, **kwargs) -> None:
        """
        Загрузить модель Vosk.

        Args:
            model_path: Путь к директории с моделью
            sample_rate: Частота дискретизации (по умолчанию 16000)
        """
        try:
            from vosk import Model, KaldiRecognizer, SetLogLevel
        except ImportError:
            raise ImportError(
                "Vosk не установлен. Установите: pip install vosk\n"
                "Скачайте модель: https://alphacephei.com/vosk/models"
            )

        SetLogLevel(-1)  # Отключить логи Kaldi
        self._model = Model(model_path)
        self._recognizer = KaldiRecognizer(self._model, sample_rate)
        self._sample_rate = sample_rate

    def transcribe_stream(
        self,
        audio_stream: Generator[bytes, None, None],
        sample_rate: int = 16000,
    ) -> Generator[ASRResult, None, None]:
        """Потоковое распознавание через Vosk."""
        if self._recognizer is None:
            raise RuntimeError("Модель не загружена. Вызовите load_model() сначала.")

        for chunk in audio_stream:
            if self._recognizer.AcceptWaveform(chunk):
                result = json.loads(self._recognizer.Result())
                text = result.get("text", "")
                if text:
                    yield ASRResult(text=text, is_final=True)
            else:
                partial = json.loads(self._recognizer.PartialResult())
                text = partial.get("partial", "")
                if text:
                    yield ASRResult(text=text, is_final=False)

    def finalize(self) -> Optional[ASRResult]:
        """Получить финальный результат."""
        if self._recognizer is None:
            return None
        result = json.loads(self._recognizer.FinalResult())
        text = result.get("text", "")
        if text:
            return ASRResult(text=text, is_final=True)
        return None

    def transcribe_file(self, audio_path: str) -> str:
        """Распознать аудиофайл."""
        import wave

        with wave.open(audio_path, "rb") as wf:
            if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
                raise ValueError("Аудио должно быть моно PCM 16-bit")

            sample_rate = wf.getframerate()
            if self._recognizer is None or sample_rate != self._sample_rate:
                from vosk import KaldiRecognizer
                self._recognizer = KaldiRecognizer(self._model, sample_rate)

            results = []
            while True:
                data = wf.readframes(4000)
                if len(data) == 0:
                    break
                if self._recognizer.AcceptWaveform(data):
                    res = json.loads(self._recognizer.Result())
                    if res.get("text"):
                        results.append(res["text"])

            final = json.loads(self._recognizer.FinalResult())
            if final.get("text"):
                results.append(final["text"])

            return " ".join(results)

    def reset(self) -> None:
        """Сбросить состояние распознавателя."""
        if self._recognizer is not None and self._model is not None:
            from vosk import KaldiRecognizer
            self._recognizer = KaldiRecognizer(self._model, self._sample_rate)
