"""
Модуль для предварительной фильтрации шумоподавления аудио.

Поддерживает несколько методов:
- noisereduce: качественное шумоподавление через библиотеку noisereduce
- spectral_gating: простой спектральный гейтинг (fallback)
"""

import sys
from typing import Generator, Optional
import numpy as np


class NoiseReducer:
    """Класс для шумоподавления аудио потока."""

    def __init__(
        self,
        method: str = "noisereduce",
        sample_rate: int = 16000,
        enabled: bool = True,
        **kwargs
    ):
        """
        Инициализировать фильтр шумоподавления.

        Args:
            method: Метод шумоподавления ("noisereduce", "spectral_gating", "none")
            sample_rate: Частота дискретизации
            enabled: Включено ли шумоподавление
            **kwargs: Дополнительные параметры для конкретного метода
        """
        self.method = method if enabled else "none"
        self.sample_rate = sample_rate
        self.enabled = enabled
        self._reducer = None
        self._noise_profile = None
        self._noise_profile_samples = kwargs.get("noise_profile_samples", 1.0)  # секунды для профиля шума
        self._noise_profile_collected = False
        self._noise_buffer = []

        if self.method == "noisereduce":
            self._init_noisereduce(kwargs)
        elif self.method == "spectral_gating":
            self._init_spectral_gating(kwargs)

    def _init_noisereduce(self, kwargs: dict) -> None:
        """Инициализировать noisereduce."""
        try:
            import noisereduce as nr
            self._nr = nr
            self._reducer = "noisereduce"
            print("[noise_reduction] Используется noisereduce", file=sys.stderr)
        except ImportError:
            print(
                "[noise_reduction] noisereduce не установлен, используем spectral_gating",
                file=sys.stderr
            )
            self.method = "spectral_gating"
            self._init_spectral_gating(kwargs)

    def _init_spectral_gating(self, kwargs: dict) -> None:
        """Инициализировать простой спектральный гейтинг."""
        self._reducer = "spectral_gating"
        self._alpha = kwargs.get("alpha", 0.95)  # Коэффициент сглаживания
        self._threshold = kwargs.get("threshold", 0.01)  # Порог для шума
        print("[noise_reduction] Используется spectral_gating", file=sys.stderr)

    def _reduce_noisereduce(self, audio: np.ndarray) -> np.ndarray:
        """Применить noisereduce."""
        if not self._noise_profile_collected:
            # Собираем профиль шума из первых секунд
            self._noise_buffer.append(audio.copy())
            total_samples = sum(len(buf) for buf in self._noise_buffer)
            if total_samples >= self._noise_profile_samples * self.sample_rate:
                # Собрали достаточно для профиля
                noise_profile = np.concatenate(self._noise_buffer)
                self._noise_profile = noise_profile
                self._noise_profile_collected = True
                self._noise_buffer = []
                print("[noise_reduction] Профиль шума собран", file=sys.stderr)
            # Пока профиль не собран, возвращаем оригинал
            return audio

        # Применяем шумоподавление
        try:
            # Стационарный шум (быстрее)
            reduced = self._nr.reduce_noise(
                y=audio,
                sr=self.sample_rate,
                stationary=True,
                prop_decrease=0.8,  # Насколько уменьшить шум (0-1)
            )
            return reduced.astype(np.int16)
        except Exception as e:
            print(f"[noise_reduction] Ошибка noisereduce: {e}", file=sys.stderr)
            return audio

    def _reduce_spectral_gating(self, audio: np.ndarray) -> np.ndarray:
        """Применить простой спектральный гейтинг."""
        if not self._noise_profile_collected:
            # Собираем профиль шума
            self._noise_buffer.append(audio.copy())
            total_samples = sum(len(buf) for buf in self._noise_buffer)
            if total_samples >= self._noise_profile_samples * self.sample_rate:
                noise_profile = np.concatenate(self._noise_buffer)
                # Вычисляем среднюю мощность шума
                noise_power = np.mean(noise_profile.astype(np.float32) ** 2)
                self._noise_threshold = noise_power * (1 + self._threshold)
                self._noise_profile_collected = True
                self._noise_buffer = []
                print(f"[noise_reduction] Порог шума: {self._noise_threshold:.2f}", file=sys.stderr)
            return audio

        # Простой спектральный гейтинг
        audio_float = audio.astype(np.float32) / 32768.0
        power = audio_float ** 2
        
        # Если мощность ниже порога - это шум, уменьшаем
        mask = power > self._noise_threshold
        audio_float[mask] = audio_float[mask]
        audio_float[~mask] = audio_float[~mask] * 0.1  # Сильно уменьшаем шум
        
        return (audio_float * 32768.0).astype(np.int16)

    def process_chunk(self, chunk: bytes) -> bytes:
        """
        Обработать один чанк аудио.

        Args:
            chunk: Байты PCM 16-bit аудио

        Returns:
            Обработанные байты
        """
        if not self.enabled or self.method == "none":
            return chunk

        try:
            # Конвертируем байты в numpy array
            audio = np.frombuffer(chunk, dtype=np.int16)

            # Применяем выбранный метод
            if self.method == "noisereduce":
                reduced = self._reduce_noisereduce(audio)
            elif self.method == "spectral_gating":
                reduced = self._reduce_spectral_gating(audio)
            else:
                return chunk

            # Конвертируем обратно в байты
            return reduced.tobytes()
        except Exception as e:
            print(f"[noise_reduction] Ошибка обработки: {e}", file=sys.stderr)
            return chunk

    def process_stream(
        self, audio_stream: Generator[bytes, None, None]
    ) -> Generator[bytes, None, None]:
        """
        Обработать поток аудио.

        Args:
            audio_stream: Генератор байтов аудио

        Yields:
            Обработанные байты
        """
        for chunk in audio_stream:
            yield self.process_chunk(chunk)

    def reset(self) -> None:
        """Сбросить состояние (например, для новой сессии диктовки)."""
        self._noise_profile_collected = False
        self._noise_buffer = []
        self._noise_profile = None


def create_noise_reducer(config: dict) -> Optional[NoiseReducer]:
    """
    Создать фильтр шумоподавления из конфигурации.

    Args:
        config: Конфигурация с секцией [noise_reduction]

    Returns:
        NoiseReducer или None если отключено
    """
    noise_config = config.get("noise_reduction", {})
    
    if not noise_config.get("enabled", False):
        return None

    sample_rate = config.get("audio", {}).get("sample_rate", 16000)
    method = noise_config.get("method", "noisereduce")
    
    return NoiseReducer(
        method=method,
        sample_rate=sample_rate,
        enabled=True,
        noise_profile_samples=noise_config.get("noise_profile_samples", 1.0),
        alpha=noise_config.get("alpha", 0.95),
        threshold=noise_config.get("threshold", 0.01),
    )
