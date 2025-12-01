#!/usr/bin/env python3
"""
Скрипт установки моделей Vosk для nerd-dictation-vosk.

Использование:
    nerd-dictation-vosk-setup --model small   # Маленькая модель (~45MB)
    nerd-dictation-vosk-setup --model large   # Большая модель (~1.5GB)
    nerd-dictation-vosk-setup --list          # Список доступных моделей
"""

import argparse
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

# Доступные модели
MODELS = {
    "small": {
        "url": "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip",
        "name": "vosk-model-small-ru-0.22",
        "target": "vosk-model-small-ru",
        "size": "45MB",
        "description": "Маленькая модель, быстрая, приемлемое качество",
    },
    "large": {
        "url": "https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip",
        "name": "vosk-model-ru-0.42",
        "target": "vosk-model-ru",
        "size": "1.5GB",
        "description": "Большая модель, лучшее качество",
    },
    "small-en": {
        "url": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
        "name": "vosk-model-small-en-us-0.15",
        "target": "vosk-model-small-en",
        "size": "40MB",
        "description": "Маленькая английская модель",
    },
}

DEFAULT_MODEL_DIR = Path.home() / ".local" / "share" / "vosk"


def get_model_dir() -> Path:
    """Получить директорию для моделей."""
    # Проверяем переменную окружения
    env_dir = os.environ.get("VOSK_MODEL_DIR")
    if env_dir:
        return Path(env_dir)
    return DEFAULT_MODEL_DIR


def download_with_progress(url: str, dest: Path) -> None:
    """Скачать файл с отображением прогресса."""
    print(f"Скачивание: {url}")

    def progress_hook(block_num, block_size, total_size):
        downloaded = block_num * block_size
        if total_size > 0:
            percent = min(100, downloaded * 100 // total_size)
            mb_downloaded = downloaded / (1024 * 1024)
            mb_total = total_size / (1024 * 1024)
            sys.stdout.write(f"\r  {percent}% ({mb_downloaded:.1f}/{mb_total:.1f} MB)")
            sys.stdout.flush()

    urllib.request.urlretrieve(url, dest, progress_hook)
    print()  # Новая строка после прогресса


def install_model(model_key: str, model_dir: Path, force: bool = False) -> Path:
    """Установить модель."""
    if model_key not in MODELS:
        print(f"Ошибка: неизвестная модель '{model_key}'")
        print(f"Доступные: {', '.join(MODELS.keys())}")
        sys.exit(1)

    model_info = MODELS[model_key]
    target_path = model_dir / model_info["target"]

    # Проверяем, установлена ли модель
    if target_path.exists() and not force:
        print(f"Модель уже установлена: {target_path}")
        print("Используйте --force для переустановки")
        return target_path

    # Создаём директорию
    model_dir.mkdir(parents=True, exist_ok=True)

    # Скачиваем
    zip_path = model_dir / f"{model_info['name']}.zip"
    try:
        download_with_progress(model_info["url"], zip_path)

        # Распаковываем
        print(f"Распаковка в {model_dir}...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(model_dir)

        # Переименовываем
        extracted_path = model_dir / model_info["name"]
        if extracted_path.exists():
            if target_path.exists():
                shutil.rmtree(target_path)
            extracted_path.rename(target_path)

        print(f"Модель установлена: {target_path}")
        return target_path

    finally:
        # Удаляем архив
        if zip_path.exists():
            zip_path.unlink()


def list_models() -> None:
    """Показать список доступных моделей."""
    print("Доступные модели Vosk:\n")
    model_dir = get_model_dir()

    for key, info in MODELS.items():
        target_path = model_dir / info["target"]
        status = "✓ установлена" if target_path.exists() else "✗ не установлена"
        print(f"  {key}:")
        print(f"    Размер: {info['size']}")
        print(f"    Описание: {info['description']}")
        print(f"    Статус: {status}")
        if target_path.exists():
            print(f"    Путь: {target_path}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Установка моделей Vosk для nerd-dictation-vosk"
    )
    parser.add_argument(
        "--model", "-m",
        choices=list(MODELS.keys()),
        help="Модель для установки"
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="Показать список доступных моделей"
    )
    parser.add_argument(
        "--dir", "-d",
        type=Path,
        default=None,
        help=f"Директория для моделей (по умолчанию: {DEFAULT_MODEL_DIR})"
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Переустановить модель, даже если она уже установлена"
    )

    args = parser.parse_args()

    if args.list:
        list_models()
        return

    if not args.model:
        parser.print_help()
        print("\nПример: nerd-dictation-vosk-setup --model small")
        sys.exit(1)

    model_dir = args.dir or get_model_dir()
    install_model(args.model, model_dir, args.force)


if __name__ == "__main__":
    main()
