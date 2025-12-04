#!/usr/bin/env python3
"""
nerd-dictation-ex CLI — главная точка входа.

Использование:
    # Запуск daemon через systemd (рекомендуется)
    systemctl --user start nerd-dictation-ex
    systemctl --user enable nerd-dictation-ex  # автозапуск

    # Диктовка
    nerd-dictation-ex toggle             # Переключить диктовку
    nerd-dictation-ex begin              # Начать диктовку
    nerd-dictation-ex end                # Завершить диктовку
    nerd-dictation-ex cancel             # Отменить диктовку

    # Утилиты
    nerd-dictation-ex list-backends      # Показать бэкенды
"""

import argparse
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
from collections import deque
from typing import Optional, Generator

# Пути
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
SOCKET_PATH = RUNTIME_DIR / "nerd-dictation-ex.sock"
PID_FILE = RUNTIME_DIR / "nerd-dictation-ex.pid"
COOKIE_PATH = Path("/tmp/nerd-dictation-ex.cookie")

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
        "general": {"backend": "vosk", "input_method": "xdotool"},
        "audio": {"source": "pw-cat", "sample_rate": 16000, "chunk_size": 8000},
        "vosk": {"model_path": "~/.local/share/vosk/vosk-model-ru"},
        "gigaam": {"model_name": "v3_ctc", "device": "cuda"},
        "output": {"trailing_space": True},
    }


# ============================================================================
# Daemon
# ============================================================================

class DaemonState(Enum):
    """Состояние daemon'а."""
    IDLE = "idle"
    LISTENING = "listening"
    STOPPING = "stopping"


class DictationDaemon:
    """Daemon для nerd-dictation-ex. Держит модель в памяти."""

    # Размер кольцевого буфера в секундах
    AUDIO_BUFFER_SECONDS = 1.5

    # Wake word настройки
    WAKE_WORD = "запись"
    WAKE_WORD_ENABLED = True

    def __init__(self, config: dict):
        self.config = config
        self.state = DaemonState.IDLE
        self.backend = None
        self.backend_name = None
        self._audio_proc: Optional[subprocess.Popen] = None
        self._running = True
        self._dictation_thread: Optional[threading.Thread] = None
        self._stop_dictation = threading.Event()

        # Кольцевой буфер аудио
        sample_rate = config.get("audio", {}).get("sample_rate", 16000)
        chunk_size = config.get("audio", {}).get("chunk_size", 8000)
        # Сколько чанков помещается в буфер
        bytes_per_second = sample_rate * 2  # 16-bit = 2 bytes per sample
        buffer_bytes = int(bytes_per_second * self.AUDIO_BUFFER_SECONDS)
        self._buffer_max_chunks = max(1, buffer_bytes // chunk_size)
        self._audio_buffer: deque = deque(maxlen=self._buffer_max_chunks)
        self._audio_buffer_lock = threading.Lock()
        self._audio_listener_thread: Optional[threading.Thread] = None

        # Очередь для wake word (без лимита, wake word loop потребляет данные)
        from queue import Queue
        self._wake_word_queue: Queue = Queue()

        # Wake word detection
        self._wake_word_enabled = config.get("wake_word", {}).get("enabled", self.WAKE_WORD_ENABLED)
        self._wake_word = config.get("wake_word", {}).get("word", self.WAKE_WORD)
        self._wake_word_model_path = os.path.expanduser(
            config.get("wake_word", {}).get("model_path", "~/.local/share/vosk/vosk-model-small-ru")
        )
        self._vosk_model = None
        self._vosk_recognizer = None
        self._vad_model = None
        self._vad_iterator = None
        self._wake_word_thread: Optional[threading.Thread] = None
        self._wake_word_running = False

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

    def _load_wake_word_models(self) -> bool:
        """Загрузить модели для wake word detection (Silero VAD + Vosk small)."""
        if not self._wake_word_enabled:
            return False

        # Загрузить Silero VAD
        try:
            import torch
            print("Загрузка Silero VAD для wake word...", file=sys.stderr)
            self._vad_model, utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                onnx=False,
                trust_repo=True
            )
            (_, _, _, VADIterator, _) = utils
            sample_rate = self.config.get("audio", {}).get("sample_rate", 16000)
            self._vad_iterator = VADIterator(
                self._vad_model,
                sampling_rate=sample_rate,
                threshold=0.5,
                min_silence_duration_ms=300,
                speech_pad_ms=100
            )
            print("Silero VAD загружен", file=sys.stderr)
        except Exception as e:
            print(f"Ошибка загрузки Silero VAD: {e}", file=sys.stderr)
            return False

        # Загрузить Vosk small для wake word
        try:
            from vosk import Model, KaldiRecognizer
            print(f"Загрузка Vosk модели для wake word: {self._wake_word_model_path}...", file=sys.stderr)

            if not os.path.exists(self._wake_word_model_path):
                print(f"Модель не найдена: {self._wake_word_model_path}", file=sys.stderr)
                print("Скачайте: https://alphacephei.com/vosk/models", file=sys.stderr)
                return False

            self._vosk_model = Model(self._wake_word_model_path)
            sample_rate = self.config.get("audio", {}).get("sample_rate", 16000)
            self._vosk_recognizer = KaldiRecognizer(self._vosk_model, sample_rate)
            print("Vosk модель для wake word загружена", file=sys.stderr)
            return True
        except Exception as e:
            print(f"Ошибка загрузки Vosk модели: {e}", file=sys.stderr)
            return False

    def _start_wake_word_detection(self) -> None:
        """Запустить поток wake word detection."""
        if not self._wake_word_enabled:
            return

        if self._wake_word_thread and self._wake_word_thread.is_alive():
            return

        if not self._load_wake_word_models():
            print("Wake word detection отключён из-за ошибок загрузки", file=sys.stderr)
            return

        self._wake_word_running = True
        self._wake_word_thread = threading.Thread(
            target=self._wake_word_loop, daemon=True
        )
        self._wake_word_thread.start()
        print(f"Wake word detection запущен (слово: '{self._wake_word}')", file=sys.stderr)

    def _wake_word_loop(self) -> None:
        """Цикл распознавания wake word."""
        import torch
        import numpy as np
        from queue import Empty

        sample_rate = self.config.get("audio", {}).get("sample_rate", 16000)

        # VAD требует чанки по 512 сэмплов при 16kHz
        vad_chunk_samples = 512
        vad_buffer = np.array([], dtype=np.int16)

        # Буфер для накопления речи перед отправкой в Vosk
        speech_buffer = b''
        is_speech_active = False

        while self._wake_word_running and self._running:
            # Пропускаем, если диктовка уже активна
            if self.state == DaemonState.LISTENING:
                # Сбросить состояние и очистить очередь
                vad_buffer = np.array([], dtype=np.int16)
                speech_buffer = b''
                is_speech_active = False
                # Очистить очередь
                while not self._wake_word_queue.empty():
                    try:
                        self._wake_word_queue.get_nowait()
                    except Empty:
                        break
                if self._vad_iterator:
                    self._vad_iterator.reset_states()
                if self._vosk_recognizer:
                    self._vosk_recognizer.Reset()
                time.sleep(0.1)
                continue

            # Получить аудио из очереди (блокирующий вызов с таймаутом)
            try:
                chunk = self._wake_word_queue.get(timeout=0.1)
            except Empty:
                continue

            # Конвертировать в numpy
            audio_np = np.frombuffer(chunk, dtype=np.int16)
            vad_buffer = np.concatenate([vad_buffer, audio_np])

            # Обрабатываем VAD чанками по 512 сэмплов
            while len(vad_buffer) >= vad_chunk_samples:
                vad_chunk = vad_buffer[:vad_chunk_samples]
                vad_buffer = vad_buffer[vad_chunk_samples:]

                # Нормализация для VAD
                audio_float = torch.from_numpy(vad_chunk.astype(np.float32) / 32768.0)

                # Проверяем VAD
                speech_dict = self._vad_iterator(audio_float, return_seconds=False)

                if speech_dict:
                    if 'start' in speech_dict:
                        is_speech_active = True
                        speech_buffer = vad_chunk.tobytes()
                    elif 'end' in speech_dict:
                        is_speech_active = False
                        speech_buffer += vad_chunk.tobytes()

                        # Распознаём накопленную речь
                        if speech_buffer:
                            self._vosk_recognizer.AcceptWaveform(speech_buffer)
                            result = json.loads(self._vosk_recognizer.Result())
                            text = result.get("text", "").lower().strip()

                            if text:
                                print(f"[wake word] распознано: '{text}'", file=sys.stderr)

                                # Проверяем на wake word (включая падежные формы)
                                wake_words = [self._wake_word.lower(), "записи"]
                                if any(w in text for w in wake_words):
                                    print(f"[wake word] активация по слову '{self._wake_word}'!", file=sys.stderr)
                                    self._vad_iterator.reset_states()
                                    self._vosk_recognizer.Reset()
                                    # Очистить аудио-буфер чтобы wake word не попал в диктовку
                                    with self._audio_buffer_lock:
                                        self._audio_buffer.clear()
                                    self.begin_dictation()

                        speech_buffer = b''
                        self._vosk_recognizer.Reset()
                elif is_speech_active:
                    speech_buffer += vad_chunk.tobytes()

    def _start_audio_listener(self) -> None:
        """Запустить постоянный слушатель аудио."""
        if self._audio_listener_thread and self._audio_listener_thread.is_alive():
            return

        self._audio_listener_thread = threading.Thread(
            target=self._audio_listener_loop, daemon=True
        )
        self._audio_listener_thread.start()
        print("Аудио-слушатель запущен", file=sys.stderr)

    def _audio_listener_loop(self) -> None:
        """Постоянно слушать микрофон и заполнять кольцевой буфер."""
        cmd = _get_audio_command(self.config)
        chunk_size = self.config.get("audio", {}).get("chunk_size", 8000)

        while self._running:
            try:
                self._audio_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)

                # Блокирующее чтение — ждём пока накопится chunk_size байт
                while self._running and self._audio_proc.poll() is None:
                    chunk = self._audio_proc.stdout.read(chunk_size)
                    if chunk:
                        with self._audio_buffer_lock:
                            self._audio_buffer.append(chunk)
                        # Дублируем в очередь для wake word
                        if self._wake_word_running and self.state != DaemonState.LISTENING:
                            try:
                                self._wake_word_queue.put_nowait(chunk)
                            except:
                                pass  # Очередь переполнена - пропускаем
                    elif not chunk:
                        # EOF или процесс завершился
                        break
            except Exception as e:
                print(f"Ошибка аудио-слушателя: {e}", file=sys.stderr)
            finally:
                if self._audio_proc:
                    self._audio_proc.terminate()
                    self._audio_proc.wait()
                    self._audio_proc = None

            if self._running:
                time.sleep(0.5)  # Пауза перед перезапуском

    def _audio_stream(self) -> Generator[bytes, None, None]:
        """Генератор аудио-чанков: сначала буфер, потом живой поток."""
        # Сначала отдаём накопленный буфер
        with self._audio_buffer_lock:
            buffered = list(self._audio_buffer)
            self._audio_buffer.clear()

        for chunk in buffered:
            if self._stop_dictation.is_set():
                return
            yield chunk

        # Затем читаем живой поток
        while not self._stop_dictation.is_set():
            with self._audio_buffer_lock:
                if self._audio_buffer:
                    chunk = self._audio_buffer.popleft()
                    yield chunk
                    continue
            time.sleep(0.01)

    def _type_text(self, text: str) -> None:
        """Ввести текст через выбранный метод."""
        from .input import type_text, press_keys
        from .postprocess import process_text, TextAction, KeyAction
        from .sounds import play_execute

        actions = process_text(text)
        for action in actions:
            if isinstance(action, TextAction):
                type_text(action.text, self.config)
            elif isinstance(action, KeyAction):
                play_execute()
                press_keys(action.keys, self.config)

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

        # Сбросить постобработчик для новой диктовки
        from .postprocess import reset_processor
        from .sounds import play_begin
        reset_processor()
        play_begin()

        self._dictation_thread = threading.Thread(target=self._dictation_loop, daemon=True)
        self._dictation_thread.start()

        return {"status": "ok", "message": "Диктовка запущена"}

    def end_dictation(self) -> dict:
        """Завершить диктовку с выводом текста."""
        if self.state != DaemonState.LISTENING:
            return {"status": "error", "message": "Диктовка не запущена"}

        from .sounds import play_end
        play_end()

        self._stop_dictation.set()

        if self._dictation_thread:
            self._dictation_thread.join(timeout=2.0)

        self.state = DaemonState.IDLE
        return {"status": "ok", "message": "Диктовка завершена"}

    def cancel_dictation(self) -> dict:
        """Отменить диктовку без вывода."""
        if self.state != DaemonState.LISTENING:
            return {"status": "error", "message": "Диктовка не запущена"}

        self._stop_dictation.set()
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
        self._wake_word_running = False
        return {"status": "ok", "message": "Daemon останавливается"}

    def run(self) -> None:
        """Запустить daemon."""
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(SOCKET_PATH))
        server.listen(5)
        server.settimeout(1.0)

        PID_FILE.write_text(str(os.getpid()))

        # Запустить постоянный аудио-слушатель
        self._start_audio_listener()

        # Запустить wake word detection если включено
        self._start_wake_word_detection()

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
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, ValueError):
            PID_FILE.unlink(missing_ok=True)
            SOCKET_PATH.unlink(missing_ok=True)
            return False


# ============================================================================
# Команды для работы через daemon
# ============================================================================

def cmd_begin(args, config: dict) -> None:
    """Начать диктовку (через daemon или напрямую)."""
    if DaemonClient.is_running():
        response = DaemonClient.send_command({"action": "begin"})
        if response.get("status") == "ok":
            print("Диктовка запущена", file=sys.stderr)
        else:
            print(f"Ошибка: {response.get('message')}", file=sys.stderr)
            sys.exit(1)
    else:
        print("Daemon не запущен, загрузка модели...", file=sys.stderr)
        print("Для быстрого отклика: systemctl --user start nerd-dictation-ex", file=sys.stderr)
        _cmd_begin_direct(args, config)


def cmd_end(args, config: dict) -> None:
    """Завершить диктовку."""
    if DaemonClient.is_running():
        response = DaemonClient.send_command({"action": "end"})
        if response.get("status") == "ok":
            print("Диктовка завершена", file=sys.stderr)
        else:
            print(f"Ошибка: {response.get('message')}", file=sys.stderr)
    else:
        _cmd_end_direct(args, config)


def cmd_cancel(args, config: dict) -> None:
    """Отменить диктовку."""
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
    if DaemonClient.is_running():
        status = DaemonClient.send_command({"action": "status"})
        if status.get("state") == "listening":
            cmd_end(args, config)
        else:
            cmd_begin(args, config)
    else:
        if COOKIE_PATH.exists():
            _cmd_end_direct(args, config)
        else:
            _cmd_begin_direct(args, config)


# ============================================================================
# Fallback: прямой режим (без daemon)
# ============================================================================

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


def _cmd_begin_direct(args, config: dict) -> None:
    """Начать диктовку напрямую (без daemon)."""
    from . import get_backend, get_available_backends
    from .input import type_text
    from .sounds import play_begin, play_end

    if COOKIE_PATH.exists():
        print("Диктовка уже запущена. Используйте 'end' или 'cancel'.", file=sys.stderr)
        sys.exit(1)

    backend_name = getattr(args, 'backend', None) or config.get("general", {}).get("backend", "vosk")

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
    play_begin()

    try:
        with backend:
            for result in backend.transcribe_stream(
                _audio_stream(config),
                sample_rate=sample_rate,
            ):
                if not running:
                    break
                if result.is_final and result.text:
                    type_text(result.text, config)

            if running:
                final = backend.finalize()
                if final and final.text:
                    type_text(final.text, config)
    finally:
        play_end()
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

def _run_daemon(config: dict) -> None:
    """Запустить daemon (для systemd)."""
    daemon = DictationDaemon(config)

    def handle_signal(signum, frame):
        daemon._running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    daemon.load_backend()
    daemon.run()


def main():
    """Точка входа для nerd-dictation-ex."""
    parser = argparse.ArgumentParser(
        description="nerd-dictation-ex — диктовка с подключаемыми бэкендами ASR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  # Запуск через systemd (рекомендуется):
  systemctl --user start nerd-dictation-ex   # Запустить daemon
  nerd-dictation-ex toggle                   # Переключить диктовку

  # Без daemon (медленный старт):
  nerd-dictation-ex begin --no-daemon        # Загружать модель каждый раз
        """
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # daemon (для systemd)
    subparsers.add_parser("daemon", help="Запустить daemon (для systemd)")

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
        _run_daemon(config)
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
