#!/usr/bin/env python3
"""
Скрипт установки GigaAM для nerd-dictation-gigaam.

GigaAM скачивает модели автоматически при первом использовании,
но этот скрипт позволяет:
- Установить библиотеку GigaAM
- Предзагрузить модели
- Проверить работоспособность GPU

Использование:
    nerd-dictation-gigaam-setup              # Установить GigaAM
    nerd-dictation-gigaam-setup --preload    # Предзагрузить модель
    nerd-dictation-gigaam-setup --check      # Проверить GPU
"""

import argparse
import subprocess
import sys


GIGAAM_REPO = "https://github.com/salute-developers/GigaAM.git"

MODELS = {
    "v3_ctc": "Быстрая CTC модель (~240M параметров)",
    "v3_rnnt": "Точная RNNT модель",
    "v3_e2e_ctc": "End-to-end CTC с пунктуацией",
    "v3_e2e_rnnt": "End-to-end RNNT с пунктуацией (лучшее качество)",
}


def check_gpu() -> bool:
    """Проверить доступность CUDA."""
    try:
        import torch
        if torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
            memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            print(f"✓ CUDA доступна")
            print(f"  GPU: {device_name}")
            print(f"  VRAM: {memory:.1f} GB")
            return True
        else:
            print("✗ CUDA недоступна")
            print("  GigaAM будет работать на CPU (медленнее)")
            return False
    except ImportError:
        print("✗ PyTorch не установлен")
        return False


def install_gigaam() -> bool:
    """Установить GigaAM из GitHub."""
    print("Установка GigaAM...")

    # Пробуем pip install gigaam (если есть в PyPI)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "gigaam"],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print("✓ GigaAM установлен из PyPI")
        return True

    # Если нет в PyPI, ставим из GitHub
    print("  Установка из GitHub...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", f"git+{GIGAAM_REPO}"],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print("✓ GigaAM установлен из GitHub")
        return True

    print(f"✗ Ошибка установки GigaAM:")
    print(result.stderr)
    return False


def preload_model(model_name: str = "v3_ctc") -> bool:
    """Предзагрузить модель GigaAM."""
    print(f"Загрузка модели {model_name}...")

    try:
        import gigaam
        model = gigaam.load_model(model_name)
        print(f"✓ Модель {model_name} загружена")

        # Тестовый инференс
        print("  Тестирование...")
        test_audio = gigaam.utils.download_short_audio()
        result = model.transcribe(test_audio)
        print(f"  Тест: '{result[:50]}...'")
        return True

    except Exception as e:
        print(f"✗ Ошибка загрузки модели: {e}")
        return False


def list_models() -> None:
    """Показать доступные модели."""
    print("Доступные модели GigaAM:\n")
    for name, desc in MODELS.items():
        print(f"  {name}:")
        print(f"    {desc}")
    print()
    print("Рекомендация:")
    print("  - v3_ctc для скорости")
    print("  - v3_e2e_rnnt для качества")


def main():
    parser = argparse.ArgumentParser(
        description="Установка GigaAM для nerd-dictation-gigaam"
    )
    parser.add_argument(
        "--check", "-c",
        action="store_true",
        help="Проверить доступность GPU"
    )
    parser.add_argument(
        "--preload", "-p",
        action="store_true",
        help="Предзагрузить модель"
    )
    parser.add_argument(
        "--model", "-m",
        choices=list(MODELS.keys()),
        default="v3_ctc",
        help="Модель для предзагрузки (по умолчанию: v3_ctc)"
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="Показать доступные модели"
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Пропустить установку GigaAM"
    )

    args = parser.parse_args()

    if args.list:
        list_models()
        return

    if args.check:
        check_gpu()
        return

    # Проверяем GPU
    print("=== Проверка GPU ===")
    check_gpu()
    print()

    # Устанавливаем GigaAM
    if not args.skip_install:
        print("=== Установка GigaAM ===")
        if not install_gigaam():
            print("\nУстановите вручную:")
            print(f"  git clone {GIGAAM_REPO}")
            print("  cd GigaAM && pip install -e .")
            sys.exit(1)
        print()

    # Предзагружаем модель
    if args.preload:
        print(f"=== Загрузка модели {args.model} ===")
        if not preload_model(args.model):
            sys.exit(1)
        print()

    print("Готово! Теперь можно использовать:")
    print("  nerd-dictation-ex begin --backend gigaam")


if __name__ == "__main__":
    main()
