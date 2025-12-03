"""
Модуль ввода текста через различные методы (xdotool, ydotool, wtype, dotool).
"""

import shlex
import subprocess
import sys

# Команды для различных методов ввода
INPUT_COMMANDS = {
    "ydotool": ["ydotool", "type", "--"],
    "dotool": ["dotool"],
    "xdotool": ["xdotool", "type", "--"],
    "wtype": ["wtype"],
}

# Команды для нажатия клавиш
KEY_COMMANDS = {
    "ydotool": ["ydotool", "key"],
    "dotool": ["dotool"],
    "xdotool": ["xdotool", "key"],
    "wtype": ["wtype", "-k"],
}


def type_text(text: str, config: dict) -> None:
    """
    Ввести текст через выбранный метод.

    Args:
        text: Текст для ввода
        config: Конфигурация с настройками input_method и output
    """
    if not text:
        return

    method = config.get("general", {}).get("input_method", "xdotool")

    if method == "stdout":
        print(text, end="", flush=True)
        return

    if method not in INPUT_COMMANDS:
        print(f"[input] неизвестный метод: {method}", file=sys.stderr)
        return

    cmd = INPUT_COMMANDS[method]

    if cmd[0] == "dotool":
        # dotool принимает команды через stdin
        print(f"[input] выполняю: {cmd} (stdin)", file=sys.stderr)
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        proc.communicate(f"type {text}".encode())
    else:
        # Остальные — через shell для корректной обработки аргументов
        shell_cmd = f'{" ".join(cmd)} {shlex.quote(text)}'
        print(f"[input] выполняю: {shell_cmd}", file=sys.stderr)
        result = subprocess.run(shell_cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"[input] ошибка: {result.stderr}", file=sys.stderr)


def press_keys(keys: str, config: dict) -> None:
    """
    Нажать комбинацию клавиш.

    Args:
        keys: Комбинация клавиш (формат xdotool: "ctrl+Return")
        config: Конфигурация с настройками input_method
    """
    method = config.get("general", {}).get("input_method", "xdotool")

    if method == "stdout":
        print(f"[KEY:{keys}]", end="", flush=True)
        return

    if method not in KEY_COMMANDS:
        print(f"[input] неизвестный метод для клавиш: {method}", file=sys.stderr)
        return

    cmd = KEY_COMMANDS[method]

    if cmd[0] == "dotool":
        # dotool: "key ctrl+enter"
        dotool_keys = keys.lower().replace("return", "enter")
        print(f"[input] клавиши: {cmd} key {dotool_keys}", file=sys.stderr)
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        proc.communicate(f"key {dotool_keys}".encode())
    else:
        # xdotool, ydotool, wtype
        shell_cmd = f'{" ".join(cmd)} {keys}'
        print(f"[input] клавиши: {shell_cmd}", file=sys.stderr)
        result = subprocess.run(shell_cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"[input] ошибка: {result.stderr}", file=sys.stderr)
