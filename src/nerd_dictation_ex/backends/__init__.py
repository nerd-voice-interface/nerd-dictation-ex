"""
nerd-dictation-ex backends

Модульная система бэкендов для распознавания речи.
Бэкенды загружаются динамически через entry points.

Установка бэкендов:
    pip install nerd-dictation-vosk    # Vosk (CPU)
    pip install nerd-dictation-gigaam  # GigaAM (GPU)
"""

from importlib.metadata import entry_points
from typing import Dict, Type

from .base import ASRBackend, ASRResult


def _discover_backends() -> Dict[str, Type[ASRBackend]]:
    """
    Обнаружить установленные бэкенды через entry points.

    Бэкенды регистрируются в pyproject.toml:
        [project.entry-points."nerd_dictation_ex.backends"]
        vosk = "nerd_dictation_vosk:VoskBackend"
    """
    backends = {}

    # Python 3.10+ API
    try:
        eps = entry_points(group="nerd_dictation_ex.backends")
    except TypeError:
        # Python 3.9 fallback
        eps = entry_points().get("nerd_dictation_ex.backends", [])

    for ep in eps:
        try:
            backend_class = ep.load()
            backends[ep.name] = backend_class
        except Exception as e:
            # Логируем, но не падаем — бэкенд может быть не установлен полностью
            import sys
            print(f"Предупреждение: не удалось загрузить бэкенд '{ep.name}': {e}", file=sys.stderr)

    return backends


# Ленивая загрузка бэкендов
_backends_cache: Dict[str, Type[ASRBackend]] = None


def get_available_backends() -> Dict[str, Type[ASRBackend]]:
    """Получить словарь доступных бэкендов."""
    global _backends_cache
    if _backends_cache is None:
        _backends_cache = _discover_backends()
    return _backends_cache


def get_backend(name: str, **kwargs) -> ASRBackend:
    """
    Получить экземпляр бэкенда по имени.

    Args:
        name: Имя бэкенда (vosk, gigaam)
        **kwargs: Параметры для инициализации бэкенда

    Returns:
        Экземпляр ASRBackend

    Raises:
        ValueError: Если бэкенд не найден
    """
    backends = get_available_backends()

    if name not in backends:
        if not backends:
            raise ValueError(
                f"Бэкенд '{name}' не найден. Нет установленных бэкендов.\n"
                "Установите бэкенд:\n"
                "  pip install nerd-dictation-vosk    # для Vosk (CPU)\n"
                "  pip install nerd-dictation-gigaam  # для GigaAM (GPU)"
            )
        available = ", ".join(backends.keys())
        raise ValueError(f"Бэкенд '{name}' не найден. Доступны: {available}")

    return backends[name](**kwargs)


def list_backends() -> None:
    """Вывести список доступных бэкендов."""
    backends = get_available_backends()

    if not backends:
        print("Нет установленных бэкендов.")
        print("\nУстановите бэкенд:")
        print("  pip install nerd-dictation-vosk    # Vosk (CPU)")
        print("  pip install nerd-dictation-gigaam  # GigaAM (GPU)")
        return

    print("Доступные бэкенды:\n")
    for name, cls in backends.items():
        streaming = "✓" if cls.supports_streaming else "✗"
        print(f"  {name}:")
        print(f"    Потоковый: {streaming}")
        if hasattr(cls, "__doc__") and cls.__doc__:
            # Первая строка документации
            desc = cls.__doc__.strip().split("\n")[0]
            print(f"    {desc}")
        print()


__all__ = [
    "ASRBackend",
    "ASRResult",
    "get_backend",
    "get_available_backends",
    "list_backends",
]
