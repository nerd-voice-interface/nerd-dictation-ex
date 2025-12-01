#!/usr/bin/env python3
"""
nerd-dictation-ex CLI — главная точка входа.

Использование:
    nerd-dictation-ex begin [--backend vosk|gigaam]
    nerd-dictation-ex end
    nerd-dictation-ex cancel
    nerd-dictation-ex list-backends
"""

import argparse
import fcntl
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Generator

# Пути конфигурации
CONFIG_DIRS = [
    Path.home() / ".config" / "nerd-dictation-ex",
    Path(__file__).parent.parent.parent.parent / "config",  # Для dev-режима
]
COOKIE_PATH = Path("/tmp/nerd-dictation-ex.cookie")


def load_config() -> dict:
    """Загрузить конфигурацию из TOML файла."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib

    for config_dir in CONFIG_DIRS:
        config_file = config_dir / "config.toml"
        if config_file.exists():
            with open(config_file, "rb") as f:
                return tomllib.load(f)

    # Проверяем default.toml
    for config_dir in CONFIG_DIRS:
        default_config = config_dir / "default.toml"
        if default_config.exists():
            with open(default_config, "rb") as f:
                return tomllib.load(f)

    # Встроенный дефолт
    return {
        "general": {"backend": "vosk", "input_method": "ydotool"},
        "audio": {"source": "pw-cat", "sample_rate": 16000, "chunk_size": 8000},
        "vosk": {"model_path": "~/.local/share/vosk/vosk-model-ru"},
        "gigaam": {"model_name": "v3_ctc", "device": "cuda"},
        "output": {"trailing_space": True},
    }


def get_audio_command(config: dict) -> list:
    """Получить команду для записи аудио."""
    source = config.get("audio", {}).get("source", "pw-cat")
    sample_rate = config.get("audio", {}).get("sample_rate", 16000)

    if source == "pw-cat":
        return [
            "pw-cat", "--record",
            "--format", "s16",
            "--rate", str(sample_rate),
            "--channels", "1",
            "-",
        ]
    elif source == "parec":
        return [
            "parec",
            f"--format=s16ne",
            f"--rate={sample_rate}",
            "--channels=1",
            "--raw",
        ]
    elif source == "sox":
        return [
            "sox", "-q", "-d",
            "-t", "raw",
            "-b", "16",
            "-e", "signed-integer",
            "-r", str(sample_rate),
            "-c", "1",
            "-",
        ]
    else:
        raise ValueError(f"Неизвестный источник аудио: {source}")


def get_typing_command(config: dict) -> list:
    """Получить команду для симуляции ввода."""
    method = config.get("general", {}).get("input_method", "ydotool")

    commands = {
        "ydotool": ["ydotool", "type", "--"],
        "dotool": ["dotool"],
        "xdotool": ["xdotool", "type", "--"],
        "wtype": ["wtype", "--"],
        "stdout": None,
    }

    if method not in commands:
        raise ValueError(f"Неизвестный метод ввода: {method}")

    return commands[method]


def type_text(text: str, config: dict) -> None:
    """Ввести текст через выбранный метод."""
    if not text:
        return

    output_config = config.get("output", {})
    if output_config.get("trailing_space", True):
        text = text + " "

    cmd = get_typing_command(config)
    if cmd is None:
        print(text, end="", flush=True)
    elif "dotool" in cmd[0]:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        proc.communicate(f"type {text}".encode())
    else:
        subprocess.run(cmd + [text], check=False)


def audio_stream(config: dict) -> Generator[bytes, None, None]:
    """Генератор аудио-чанков."""
    cmd = get_audio_command(config)
    chunk_size = config.get("audio", {}).get("chunk_size", 8000)

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)

    # Неблокирующее чтение
    fd = proc.stdout.fileno()
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

    try:
        while proc.poll() is None:
            try:
                chunk = proc.stdout.read(chunk_size)
                if chunk:
                    yield chunk
            except BlockingIOError:
                import time
                time.sleep(0.01)
    finally:
        proc.terminate()
        proc.wait()


def cmd_begin(args, config: dict) -> None:
    """Начать диктовку."""
    from . import get_backend, get_available_backends

    # Проверяем, не запущен ли уже процесс
    if COOKIE_PATH.exists():
        print("Диктовка уже запущена. Используйте 'end' или 'cancel'.", file=sys.stderr)
        sys.exit(1)

    # Определяем бэкенд
    backend_name = args.backend or config.get("general", {}).get("backend", "vosk")

    # Проверяем доступность
    available = get_available_backends()
    if not available:
        print("Ошибка: нет установленных бэкендов.", file=sys.stderr)
        print("\nУстановите бэкенд:", file=sys.stderr)
        print("  pip install nerd-dictation-vosk    # Vosk (CPU)", file=sys.stderr)
        print("  pip install nerd-dictation-gigaam  # GigaAM (GPU)", file=sys.stderr)
        sys.exit(1)

    if backend_name not in available:
        print(f"Ошибка: бэкенд '{backend_name}' не установлен.", file=sys.stderr)
        print(f"Доступные: {', '.join(available.keys())}", file=sys.stderr)
        sys.exit(1)

    # Загружаем бэкенд
    print(f"Загрузка бэкенда: {backend_name}...", file=sys.stderr)
    backend = get_backend(backend_name)

    # Загружаем модель
    backend_config = config.get(backend_name, {})
    sample_rate = config.get("audio", {}).get("sample_rate", 16000)

    if backend_name == "vosk":
        model_path = os.path.expanduser(backend_config.get("model_path", ""))
        backend.load_model(model_path, sample_rate=sample_rate)
    elif backend_name == "gigaam":
        backend.load_model(
            model_name=backend_config.get("model_name", "v3_ctc"),
            device=backend_config.get("device", "cuda"),
        )
    else:
        # Универсальный вызов для других бэкендов
        backend.load_model(**backend_config)

    # Записываем PID
    COOKIE_PATH.write_text(str(os.getpid()))

    # Обработчик сигналов
    running = True

    def handle_signal(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    print("Диктовка запущена. Говорите...", file=sys.stderr)

    try:
        with backend:
            for result in backend.transcribe_stream(
                audio_stream(config),
                sample_rate=sample_rate,
            ):
                if not running:
                    break
                if result.is_final and result.text:
                    type_text(result.text, config)

            # Финализация
            if running:
                final = backend.finalize()
                if final and final.text:
                    type_text(final.text, config)
    finally:
        COOKIE_PATH.unlink(missing_ok=True)
        print("\nДиктовка завершена.", file=sys.stderr)


def cmd_end(args, config: dict) -> None:
    """Завершить диктовку."""
    if not COOKIE_PATH.exists():
        print("Диктовка не запущена.", file=sys.stderr)
        sys.exit(1)

    pid = int(COOKIE_PATH.read_text())
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        COOKIE_PATH.unlink(missing_ok=True)
        print("Процесс диктовки не найден.", file=sys.stderr)


def cmd_cancel(args, config: dict) -> None:
    """Отменить диктовку без вывода."""
    if not COOKIE_PATH.exists():
        print("Диктовка не запущена.", file=sys.stderr)
        sys.exit(1)

    pid = int(COOKIE_PATH.read_text())
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    COOKIE_PATH.unlink(missing_ok=True)


def cmd_list_backends(args, config: dict) -> None:
    """Показать доступные бэкенды."""
    from . import list_backends
    list_backends()


def main():
    parser = argparse.ArgumentParser(
        description="nerd-dictation-ex — диктовка с подключаемыми бэкендами ASR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  nerd-dictation-ex begin              # Начать с бэкендом из конфига
  nerd-dictation-ex begin -b gigaam    # Начать с GigaAM
  nerd-dictation-ex end                # Завершить диктовку
  nerd-dictation-ex list-backends      # Показать бэкенды
        """
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # begin
    begin_parser = subparsers.add_parser("begin", help="Начать диктовку")
    begin_parser.add_argument(
        "--backend", "-b",
        help="Бэкенд распознавания (переопределяет конфиг)"
    )

    # end
    subparsers.add_parser("end", help="Завершить диктовку")

    # cancel
    subparsers.add_parser("cancel", help="Отменить диктовку")

    # list-backends
    subparsers.add_parser("list-backends", help="Показать доступные бэкенды")

    args = parser.parse_args()
    config = load_config()

    commands = {
        "begin": cmd_begin,
        "end": cmd_end,
        "cancel": cmd_cancel,
        "list-backends": cmd_list_backends,
    }

    commands[args.command](args, config)


if __name__ == "__main__":
    main()
