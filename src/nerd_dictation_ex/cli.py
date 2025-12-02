#!/usr/bin/env python3
"""
nerd-dictation-ex CLI — главная точка входа.

Использование:
    # Daemon (рекомендуется для быстрого отклика)
    nerd-dictation-ex daemon start       # Запустить daemon
    nerd-dictation-ex daemon stop        # Остановить daemon
    nerd-dictation-ex daemon status      # Статус daemon

    # Диктовка (через daemon если запущен, иначе напрямую)
    nerd-dictation-ex begin              # Начать диктовку
    nerd-dictation-ex end                # Завершить диктовку
    nerd-dictation-ex cancel             # Отменить диктовку

    # Утилиты
    nerd-dictation-ex list-backends      # Показать бэкенды
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


# ============================================================================
# Команды для работы через daemon (рекомендуется)
# ============================================================================

def cmd_begin(args, config: dict) -> None:
    """Начать диктовку (через daemon или напрямую)."""
    from .daemon import DaemonClient

    if DaemonClient.is_running():
        # Используем daemon
        response = DaemonClient.send_command({"action": "begin"})
        if response.get("status") == "ok":
            print("Диктовка запущена", file=sys.stderr)
        else:
            print(f"Ошибка: {response.get('message')}", file=sys.stderr)
            sys.exit(1)
    else:
        # Fallback: запуск напрямую (медленно)
        print("Daemon не запущен, загрузка модели...", file=sys.stderr)
        print("Для быстрого отклика запустите: nerd-dictation-ex daemon start", file=sys.stderr)
        _cmd_begin_direct(args, config)


def cmd_end(args, config: dict) -> None:
    """Завершить диктовку."""
    from .daemon import DaemonClient, SOCKET_PATH

    if DaemonClient.is_running():
        response = DaemonClient.send_command({"action": "end"})
        if response.get("status") == "ok":
            print("Диктовка завершена", file=sys.stderr)
        else:
            print(f"Ошибка: {response.get('message')}", file=sys.stderr)
    else:
        # Fallback для прямого режима
        _cmd_end_direct(args, config)


def cmd_cancel(args, config: dict) -> None:
    """Отменить диктовку."""
    from .daemon import DaemonClient

    if DaemonClient.is_running():
        response = DaemonClient.send_command({"action": "cancel"})
        if response.get("status") == "ok":
            print("Диктовка отменена", file=sys.stderr)
        else:
            print(f"Ошибка: {response.get('message')}", file=sys.stderr)
    else:
        _cmd_cancel_direct(args, config)


def cmd_toggle(args, config: dict) -> None:
    """Переключить диктовку (begin/end)."""
    from .daemon import DaemonClient

    if DaemonClient.is_running():
        # Проверяем статус
        status = DaemonClient.send_command({"action": "status"})
        if status.get("state") == "listening":
            cmd_end(args, config)
        else:
            cmd_begin(args, config)
    else:
        # Без daemon — проверяем cookie
        if COOKIE_PATH.exists():
            _cmd_end_direct(args, config)
        else:
            _cmd_begin_direct(args, config)


# ============================================================================
# Команды daemon
# ============================================================================

def cmd_daemon(args, config: dict) -> None:
    """Управление daemon'ом."""
    from .daemon import run_daemon, daemon_status, DaemonClient

    if args.daemon_command == "run":
        # Запуск daemon (для systemd)
        run_daemon(config)
    elif args.daemon_command == "status":
        daemon_status()
    elif args.daemon_command == "reload":
        if not DaemonClient.is_running():
            print("Daemon не запущен", file=sys.stderr)
            sys.exit(1)
        response = DaemonClient.send_command({
            "action": "reload",
            "backend": args.backend,
        })
        print(response.get("message", response), file=sys.stderr)


# ============================================================================
# Fallback: прямой режим (без daemon)
# ============================================================================

COOKIE_PATH = Path("/tmp/nerd-dictation-ex.cookie")


def _get_audio_command(config: dict) -> list:
    """Получить команду для записи аудио."""
    source = config.get("audio", {}).get("source", "pw-cat")
    sample_rate = config.get("audio", {}).get("sample_rate", 16000)

    commands = {
        "pw-cat": ["pw-cat", "--record", "--format", "s16",
                   "--rate", str(sample_rate), "--channels", "1", "-"],
        "parec": ["parec", f"--format=s16ne", f"--rate={sample_rate}",
                  "--channels=1", "--raw"],
        "sox": ["sox", "-q", "-d", "-t", "raw", "-b", "16",
                "-e", "signed-integer", "-r", str(sample_rate), "-c", "1", "-"],
    }

    if source not in commands:
        raise ValueError(f"Неизвестный источник аудио: {source}")
    return commands[source]


def _audio_stream(config: dict) -> Generator[bytes, None, None]:
    """Генератор аудио-чанков."""
    import time

    cmd = _get_audio_command(config)
    chunk_size = config.get("audio", {}).get("chunk_size", 8000)

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)

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
                time.sleep(0.01)
    finally:
        proc.terminate()
        proc.wait()


def _type_text(text: str, config: dict) -> None:
    """Ввести текст через выбранный метод."""
    if not text:
        return

    output_config = config.get("output", {})
    if output_config.get("trailing_space", True):
        text = text + " "

    method = config.get("general", {}).get("input_method", "ydotool")

    commands = {
        "ydotool": ["ydotool", "type", "--"],
        "dotool": ["dotool"],
        "xdotool": ["xdotool", "type", "--"],
        "wtype": ["wtype", "--"],
    }

    if method == "stdout":
        print(text, end="", flush=True)
    elif method in commands:
        cmd = commands[method]
        if "dotool" in cmd[0]:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            proc.communicate(f"type {text}".encode())
        else:
            subprocess.run(cmd + [text], check=False)


def _cmd_begin_direct(args, config: dict) -> None:
    """Начать диктовку напрямую (без daemon)."""
    from . import get_backend, get_available_backends

    if COOKIE_PATH.exists():
        print("Диктовка уже запущена. Используйте 'end' или 'cancel'.", file=sys.stderr)
        sys.exit(1)

    backend_name = args.backend or config.get("general", {}).get("backend", "vosk")

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

    print(f"Загрузка бэкенда: {backend_name}...", file=sys.stderr)
    backend = get_backend(backend_name)

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
        backend.load_model(**backend_config)

    COOKIE_PATH.write_text(str(os.getpid()))

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
                _audio_stream(config),
                sample_rate=sample_rate,
            ):
                if not running:
                    break
                if result.is_final and result.text:
                    _type_text(result.text, config)

            if running:
                final = backend.finalize()
                if final and final.text:
                    _type_text(final.text, config)
    finally:
        COOKIE_PATH.unlink(missing_ok=True)
        print("\nДиктовка завершена.", file=sys.stderr)


def _cmd_end_direct(args, config: dict) -> None:
    """Завершить диктовку (прямой режим)."""
    if not COOKIE_PATH.exists():
        print("Диктовка не запущена.", file=sys.stderr)
        sys.exit(1)

    pid = int(COOKIE_PATH.read_text())
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        COOKIE_PATH.unlink(missing_ok=True)
        print("Процесс диктовки не найден.", file=sys.stderr)


def _cmd_cancel_direct(args, config: dict) -> None:
    """Отменить диктовку (прямой режим)."""
    if not COOKIE_PATH.exists():
        print("Диктовка не запущена.", file=sys.stderr)
        sys.exit(1)

    pid = int(COOKIE_PATH.read_text())
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    COOKIE_PATH.unlink(missing_ok=True)


# ============================================================================
# Утилиты
# ============================================================================

def cmd_list_backends(args, config: dict) -> None:
    """Показать доступные бэкенды."""
    from . import list_backends
    list_backends()


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="nerd-dictation-ex — диктовка с подключаемыми бэкендами ASR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  # Запуск через systemd (рекомендуется):
  systemctl --user start nerd-dictation-ex   # Запустить daemon
  nerd-dictation-ex toggle                   # Переключить диктовку
  nerd-dictation-ex daemon status            # Проверить статус

  # Управление daemon:
  nerd-dictation-ex daemon reload -b gigaam  # Сменить бэкенд
  systemctl --user stop nerd-dictation-ex    # Остановить daemon

  # Без daemon (медленный старт):
  nerd-dictation-ex begin --no-daemon        # Загружать модель каждый раз
        """
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # daemon
    daemon_parser = subparsers.add_parser("daemon", help="Управление фоновым сервисом")
    daemon_subparsers = daemon_parser.add_subparsers(dest="daemon_command", required=True)

    daemon_subparsers.add_parser("run", help="Запустить daemon (для systemd)")
    daemon_subparsers.add_parser("status", help="Показать статус daemon")

    daemon_reload = daemon_subparsers.add_parser("reload", help="Перезагрузить бэкенд")
    daemon_reload.add_argument("--backend", "-b", help="Новый бэкенд")

    # begin
    begin_parser = subparsers.add_parser("begin", help="Начать диктовку")
    begin_parser.add_argument("--backend", "-b", help="Бэкенд (переопределяет конфиг)")
    begin_parser.add_argument("--no-daemon", action="store_true",
                              help="Не использовать daemon (медленно)")

    # end
    subparsers.add_parser("end", help="Завершить диктовку")

    # cancel
    subparsers.add_parser("cancel", help="Отменить диктовку")

    # toggle
    subparsers.add_parser("toggle", help="Переключить диктовку (begin/end)")

    # list-backends
    subparsers.add_parser("list-backends", help="Показать доступные бэкенды")

    args = parser.parse_args()
    config = load_config()

    if args.command == "daemon":
        cmd_daemon(args, config)
    elif args.command == "begin":
        if getattr(args, "no_daemon", False):
            _cmd_begin_direct(args, config)
        else:
            cmd_begin(args, config)
    elif args.command == "end":
        cmd_end(args, config)
    elif args.command == "cancel":
        cmd_cancel(args, config)
    elif args.command == "toggle":
        cmd_toggle(args, config)
    elif args.command == "list-backends":
        cmd_list_backends(args, config)


if __name__ == "__main__":
    main()
