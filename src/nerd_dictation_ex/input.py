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


def type_text(text: str, config: dict) -> None:
    """
    Ввести текст через выбранный метод.

    Args:
        text: Текст для ввода
        config: Конфигурация с настройками input_method и output
    """
    if not text:
        return

    output_config = config.get("output", {})
    if output_config.get("trailing_space", True):
        text = text + " "

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
