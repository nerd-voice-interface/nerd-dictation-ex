"""
Базовый интерфейс для ASR бэкендов.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generator, Optional


@dataclass
class ASRResult:
    """Результат распознавания."""
    text: str
    is_final: bool
    confidence: Optional[float] = None


class ASRBackend(ABC):
    """Абстрактный базовый класс для бэкендов распознавания речи."""

    name: str = "base"
    supports_streaming: bool = False

    @abstractmethod
    def load_model(self, model_path: str, **kwargs) -> None:
        """Загрузить модель."""
        pass

    @abstractmethod
    def transcribe_stream(
        self,
        audio_stream: Generator[bytes, None, None],
        sample_rate: int = 16000,
    ) -> Generator[ASRResult, None, None]:
        """
        Потоковое распознавание аудио.

        Args:
            audio_stream: Генератор байтов аудио (PCM 16-bit)
            sample_rate: Частота дискретизации

        Yields:
            ASRResult с распознанным текстом
        """
        pass

    @abstractmethod
    def transcribe_file(self, audio_path: str) -> str:
        """Распознать аудиофайл целиком."""
        pass

    def finalize(self) -> Optional[ASRResult]:
        """Завершить распознавание и получить финальный результат."""
        return None

    def reset(self) -> None:
        """Сбросить состояние распознавателя."""
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.reset()
        return False
