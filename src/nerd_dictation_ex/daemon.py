#!/usr/bin/env python3
"""
nerd-dictation-ex daemon — фоновый сервис с моделью в памяти.

Держит ASR модель загруженной для мгновенного отклика.
Общение через Unix socket.

Запуск через systemd:
    systemctl --user start nerd-dictation-ex
"""

import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Optional, Generator

# Пути
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
SOCKET_PATH = RUNTIME_DIR / "nerd-dictation-ex.sock"
PID_FILE = RUNTIME_DIR / "nerd-dictation-ex.pid"


class DaemonState(Enum):
    """Состояние daemon'а."""
    IDLE = "idle"
    LISTENING = "listening"  # Диктовка активна
    STOPPING = "stopping"


class DictationDaemon:
    """
    Daemon для nerd-dictation-ex.

    Держит модель в памяти и обрабатывает команды через Unix socket.
    """

    def __init__(self, config: dict):
        self.config = config
        self.state = DaemonState.IDLE
        self.backend = None
        self.backend_name = None
        self._audio_proc: Optional[subprocess.Popen] = None
        self._running = True
        self._dictation_thread: Optional[threading.Thread] = None
        self._stop_dictation = threading.Event()

    def load_backend(self, backend_name: str = None) -> None:
        """Загрузить бэкенд и модель в память."""
        from . import get_backend

        backend_name = backend_name or self.config.get("general", {}).get("backend", "vosk")

        if self.backend and self.backend_name == backend_name:
            print(f"Бэкенд {backend_name} уже загружен", file=sys.stderr)
            return

        print(f"Загрузка бэкенда: {backend_name}...", file=sys.stderr)
        self.backend = get_backend(backend_name)
        self.backend_name = backend_name

        # Загружаем модель
        backend_config = self.config.get(backend_name, {})
        sample_rate = self.config.get("audio", {}).get("sample_rate", 16000)

        if backend_name == "vosk":
            model_path = os.path.expanduser(backend_config.get("model_path", ""))
            self.backend.load_model(model_path, sample_rate=sample_rate)
        elif backend_name == "gigaam":
            self.backend.load_model(
                model_name=backend_config.get("model_name", "v3_ctc"),
                device=backend_config.get("device", "cuda"),
            )
        else:
            self.backend.load_model(**backend_config)

        print(f"Бэкенд {backend_name} загружен и готов", file=sys.stderr)

    def _get_audio_command(self) -> list:
        """Получить команду для записи аудио."""
        source = self.config.get("audio", {}).get("source", "pw-cat")
        sample_rate = self.config.get("audio", {}).get("sample_rate", 16000)

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

    def _audio_stream(self) -> Generator[bytes, None, None]:
        """Генератор аудио-чанков."""
        cmd = self._get_audio_command()
        chunk_size = self.config.get("audio", {}).get("chunk_size", 8000)

        self._audio_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)

        # Неблокирующее чтение
        fd = self._audio_proc.stdout.fileno()
        fl = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

        try:
            while not self._stop_dictation.is_set() and self._audio_proc.poll() is None:
                try:
                    chunk = self._audio_proc.stdout.read(chunk_size)
                    if chunk:
                        yield chunk
                except BlockingIOError:
                    time.sleep(0.01)
        finally:
            if self._audio_proc:
                self._audio_proc.terminate()
                self._audio_proc.wait()
                self._audio_proc = None

    def _type_text(self, text: str) -> None:
        """Ввести текст через выбранный метод."""
        print(f"[daemon] _type_text вызван с: '{text}'", file=sys.stderr)
        if not text:
            print("[daemon] _type_text: пустой текст, пропуск", file=sys.stderr)
            return

        output_config = self.config.get("output", {})
        if output_config.get("trailing_space", True):
            text = text + " "

        method = self.config.get("general", {}).get("input_method", "xdotool")
        print(f"[daemon] _type_text: метод={method}, текст='{text}'", file=sys.stderr)

        commands = {
            "ydotool": ["ydotool", "type", "--"],
            "dotool": ["dotool"],
            "xdotool": ["xdotool", "type", "--"],
            "wtype": ["wtype"],
        }

        if method == "stdout":
            print(text, end="", flush=True)
        elif method in commands:
            import shlex
            cmd = commands[method]
            shell_cmd = f'{" ".join(cmd)} {shlex.quote(text)}'
            print(f"[daemon] выполняю: {shell_cmd}", file=sys.stderr)
            result = subprocess.run(shell_cmd, shell=True, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"[daemon] ошибка: {result.stderr}", file=sys.stderr)
            else:
                print(f"[daemon] успех", file=sys.stderr)

    def _dictation_loop(self) -> None:
        """Основной цикл диктовки (в отдельном потоке)."""
        sample_rate = self.config.get("audio", {}).get("sample_rate", 16000)

        try:
            for result in self.backend.transcribe_stream(
                self._audio_stream(),
                sample_rate=sample_rate,
            ):
                if self._stop_dictation.is_set():
                    break
                if result.is_final and result.text:
                    self._type_text(result.text)

            # Финализация (всегда вызываем при end, пропускаем только при cancel)
            print("[daemon] вызываю finalize", file=sys.stderr)
            final = self.backend.finalize()
            if final and final.text:
                self._type_text(final.text)
        except Exception as e:
            print(f"Ошибка диктовки: {e}", file=sys.stderr)
        finally:
            self.backend.reset()
            self.state = DaemonState.IDLE

    def begin_dictation(self) -> dict:
        """Начать диктовку."""
        if self.state == DaemonState.LISTENING:
            return {"status": "error", "message": "Диктовка уже запущена"}

        if not self.backend:
            return {"status": "error", "message": "Бэкенд не загружен"}

        self.state = DaemonState.LISTENING
        self._stop_dictation.clear()

        self._dictation_thread = threading.Thread(target=self._dictation_loop, daemon=True)
        self._dictation_thread.start()

        return {"status": "ok", "message": "Диктовка запущена"}

    def end_dictation(self) -> dict:
        """Завершить диктовку с выводом текста."""
        if self.state != DaemonState.LISTENING:
            return {"status": "error", "message": "Диктовка не запущена"}

        self._stop_dictation.set()

        if self._audio_proc:
            self._audio_proc.terminate()

        if self._dictation_thread:
            self._dictation_thread.join(timeout=2.0)

        self.state = DaemonState.IDLE
        return {"status": "ok", "message": "Диктовка завершена"}

    def cancel_dictation(self) -> dict:
        """Отменить диктовку без вывода."""
        if self.state != DaemonState.LISTENING:
            return {"status": "error", "message": "Диктовка не запущена"}

        self._stop_dictation.set()

        if self._audio_proc:
            self._audio_proc.kill()

        # Сбрасываем бэкенд без финализации
        self.backend.reset()
        self.state = DaemonState.IDLE

        if self._dictation_thread:
            self._dictation_thread.join(timeout=1.0)

        return {"status": "ok", "message": "Диктовка отменена"}

    def get_status(self) -> dict:
        """Получить статус daemon'а."""
        return {
            "status": "ok",
            "state": self.state.value,
            "backend": self.backend_name,
            "pid": os.getpid(),
        }

    def handle_command(self, cmd: dict) -> dict:
        """Обработать команду от клиента."""
        action = cmd.get("action")
        print(f"Команда: {action}", file=sys.stderr)

        handlers = {
            "begin": self.begin_dictation,
            "end": self.end_dictation,
            "cancel": self.cancel_dictation,
            "status": self.get_status,
            "reload": lambda: self._reload_backend(cmd.get("backend")),
            "shutdown": self._shutdown,
        }

        if action not in handlers:
            return {"status": "error", "message": f"Неизвестная команда: {action}"}

        result = handlers[action]()
        print(f"  -> {result.get('status')}: {result.get('message', result.get('state', ''))}", file=sys.stderr)
        return result

    def _reload_backend(self, backend_name: str = None) -> dict:
        """Перезагрузить бэкенд."""
        if self.state == DaemonState.LISTENING:
            return {"status": "error", "message": "Остановите диктовку перед перезагрузкой"}

        try:
            self.backend = None
            self.backend_name = None
            self.load_backend(backend_name)
            return {"status": "ok", "message": f"Бэкенд {self.backend_name} перезагружен"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _shutdown(self) -> dict:
        """Остановить daemon."""
        self._running = False
        return {"status": "ok", "message": "Daemon останавливается"}

    def run(self) -> None:
        """Запустить daemon."""
        # Удаляем старый socket если есть
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()

        # Создаём Unix socket
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(SOCKET_PATH))
        server.listen(5)
        server.settimeout(1.0)  # Для проверки _running

        # Записываем PID
        PID_FILE.write_text(str(os.getpid()))

        print(f"Daemon запущен, socket: {SOCKET_PATH}", file=sys.stderr)

        try:
            while self._running:
                try:
                    client, _ = server.accept()
                    self._handle_client(client)
                except socket.timeout:
                    continue
        finally:
            server.close()
            SOCKET_PATH.unlink(missing_ok=True)
            PID_FILE.unlink(missing_ok=True)
            print("Daemon остановлен", file=sys.stderr)

    def _handle_client(self, client: socket.socket) -> None:
        """Обработать подключение клиента."""
        try:
            data = client.recv(4096).decode()
            if data:
                cmd = json.loads(data)
                response = self.handle_command(cmd)
                client.send(json.dumps(response).encode())
        except Exception as e:
            error_response = {"status": "error", "message": str(e)}
            client.send(json.dumps(error_response).encode())
        finally:
            client.close()


class DaemonClient:
    """Клиент для общения с daemon'ом."""

    @staticmethod
    def send_command(cmd: dict, timeout: float = 5.0) -> dict:
        """Отправить команду daemon'у."""
        if not SOCKET_PATH.exists():
            return {"status": "error", "message": "Daemon не запущен"}

        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(timeout)
            client.connect(str(SOCKET_PATH))
            client.send(json.dumps(cmd).encode())
            response = client.recv(4096).decode()
            client.close()
            return json.loads(response)
        except socket.timeout:
            return {"status": "error", "message": "Таймаут соединения с daemon"}
        except ConnectionRefusedError:
            return {"status": "error", "message": "Daemon не отвечает"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @staticmethod
    def is_running() -> bool:
        """Проверить, запущен ли daemon."""
        if not PID_FILE.exists():
            return False

        try:
            pid = int(PID_FILE.read_text())
            os.kill(pid, 0)  # Проверка существования процесса
            return True
        except (ProcessLookupError, ValueError):
            # Процесс не существует, чистим файлы
            PID_FILE.unlink(missing_ok=True)
            SOCKET_PATH.unlink(missing_ok=True)
            return False


def run_daemon(config: dict) -> None:
    """Запустить daemon (вызывается из CLI или systemd)."""
    daemon = DictationDaemon(config)

    def handle_signal(signum, frame):
        daemon._running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    daemon.load_backend()
    daemon.run()


def daemon_status() -> None:
    """Показать статус daemon."""
    if not DaemonClient.is_running():
        print("Daemon не запущен")
        return

    response = DaemonClient.send_command({"action": "status"})
    if response.get("status") == "ok":
        print(f"Daemon запущен (PID: {response.get('pid')})")
        print(f"  Состояние: {response.get('state')}")
        print(f"  Бэкенд: {response.get('backend')}")
    else:
        print(f"Ошибка: {response.get('message')}")


def main() -> None:
    """Точка входа для nerd-dictation-ex-daemon (используется systemd)."""
    from .cli import load_config
    config = load_config()
    run_daemon(config)
