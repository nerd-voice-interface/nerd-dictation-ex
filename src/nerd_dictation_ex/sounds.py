"""
Модуль воспроизведения звуков для обратной связи.
"""

import subprocess
import sys
from pathlib import Path
from typing import Optional

# Путь к звукам (корень проекта / sounds)
# __file__ = src/nerd_dictation_ex/sounds.py
# parent = src/nerd_dictation_ex
# parent.parent = src
# parent.parent.parent = nerd-dictation-ex (корень)
SOUNDS_DIR = Path(__file__).parent.parent.parent / "sounds"

# Типы звуков
SOUND_BEGIN = "begin"
SOUND_END = "end"
SOUND_EXECUTE = "execute"


def _get_sound_path(sound_type: str) -> Optional[Path]:
    """Получить путь к звуковому файлу."""
    sound_file = SOUNDS_DIR / f"{sound_type}.wav"
    if sound_file.exists():
        return sound_file
    return None


def _find_player() -> Optional[list]:
    """Найти доступный аудио-плеер."""
    players = [
        ["paplay"],      # PulseAudio
        ["pw-play"],     # PipeWire
        ["aplay"],       # ALSA
    ]

    for player in players:
        try:
            result = subprocess.run(
                ["which", player[0]],
                capture_output=True,
                timeout=1
            )
            if result.returncode == 0:
                return player
        except Exception:
            pass

    return None


def play_sound(sound_type: str) -> None:
    """
    Воспроизвести звук асинхронно (не блокирует).

    Args:
        sound_type: Тип звука (begin, end, execute)
    """
    sound_path = _get_sound_path(sound_type)
    if not sound_path:
        return

    player = _find_player()
    if not player:
        return

    try:
        # Запускаем в фоне, не ждём завершения
        subprocess.Popen(
            player + [str(sound_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"[sounds] ошибка воспроизведения: {e}", file=sys.stderr)


def play_begin() -> None:
    """Воспроизвести звук начала диктовки."""
    play_sound(SOUND_BEGIN)


def play_end() -> None:
    """Воспроизвести звук окончания диктовки."""
    play_sound(SOUND_END)


def play_execute() -> None:
    """Воспроизвести звук выполнения команды."""
    play_sound(SOUND_EXECUTE)
