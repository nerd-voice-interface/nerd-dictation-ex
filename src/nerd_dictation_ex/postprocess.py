"""
Постобработка распознанного текста.

- Замена слов на знаки препинания
- Замена слов на нажатия клавиш
- Капитализация после точки/!/?
- Капитализация в начале диктовки
"""

import re
from dataclasses import dataclass
from typing import Optional, List, Union


@dataclass
class TextAction:
    """Действие: ввод текста."""
    text: str


@dataclass
class KeyAction:
    """Действие: нажатие клавиш."""
    keys: str  # Формат xdotool: "ctrl+Return", "shift+Tab", etc.


Action = Union[TextAction, KeyAction]


# Слова → нажатия клавиш (обрабатываются до замены пунктуации)
KEY_MAP = {
    "выполнять": "ctrl+Return",
    "выполняй": "ctrl+Return",
}

# Слова → знаки препинания
PUNCTUATION_MAP = {
    "точка": ".",
    "запятая": ",",
    "двоеточие": ":",
    "тире": "—",
    "дефис": "-",
    "восклицательный знак": "!",
    "вопросительный знак": "?",
    "вопрос": "?",
    "многоточие": "...",
    "кавычки": '"',
    "открыть кавычки": "«",
    "закрыть кавычки": "»",
    "открыть скобку": "(",
    "закрыть скобку": ")",
    "новая строка": "\n",
    "новый абзац": "\n\n",
    # Смайлики
    "смайлик улыбка": "😊",
    "смайлик смех": "😂",
    "смайлик крутой": "😎",
    "смайлик грустный": "😢",
    "смайлик сердце": "❤️",
    "смайлик огонь": "🔥",
    "смайлик палец вверх": "👍",
    "смайлик ок": "👌",
}

# Знаки после которых следующее слово с большой буквы
CAPITALIZE_AFTER = {".", "!", "?", "😊", "😂", "😎", "😢", "❤️", "🔥", "👍", "👌"}

# Знаки перед которыми удаляется пробел
NO_SPACE_BEFORE = {".", ",", ":", "!", "?", "—", "-", "...", "»", ")"}


class TextPostProcessor:
    """Постобработчик текста с сохранением состояния между вызовами."""

    def __init__(self):
        self._capitalize_next = True  # Начинаем с большой буквы
        self._pending_space = False   # Буферизованный пробел в конце

    def process(self, text: str) -> List[Action]:
        """
        Обработать текст: заменить слова на пунктуацию/клавиши, капитализировать.

        Args:
            text: Распознанный текст

        Returns:
            Список действий (TextAction или KeyAction)
        """
        if not text:
            return []

        # Разбиваем на части по ключевым словам (клавиши)
        actions = self._extract_key_actions(text)

        return actions

    def _extract_key_actions(self, text: str) -> List[Action]:
        """Извлечь действия клавиш и текстовые фрагменты."""
        actions = []

        # Сортируем по длине (сначала длинные фразы)
        for word, keys in sorted(KEY_MAP.items(), key=lambda x: -len(x[0])):
            pattern = r'(?i)(?<!\S)' + re.escape(word) + r'(?!\S)'
            parts = re.split(pattern, text)

            if len(parts) > 1:
                # Найдено ключевое слово — разбиваем
                result = []
                for i, part in enumerate(parts):
                    if part.strip():
                        result.extend(self._extract_key_actions(part))
                    if i < len(parts) - 1:
                        result.append(KeyAction(keys=keys))
                return result

        # Нет ключевых слов — обрабатываем как текст
        processed = self._process_text_fragment(text)
        if processed:
            actions.append(TextAction(text=processed))

        return actions

    def _process_text_fragment(self, text: str) -> str:
        """Обработать текстовый фрагмент (пунктуация, капитализация)."""
        # Заменяем слова на знаки препинания
        text = self._replace_punctuation(text)

        # Убираем лишние пробелы по краям
        text = text.strip()

        if not text:
            return ""

        # Добавляем буферизованный пробел от предыдущего фрагмента
        first_char = text[0]
        if self._pending_space and first_char not in NO_SPACE_BEFORE:
            text = " " + text

        # Буферизуем пробел для следующего фрагмента
        self._pending_space = True

        # Капитализируем
        text = self._apply_capitalization(text)

        return text

    def _replace_punctuation(self, text: str) -> str:
        """Заменить слова-команды на знаки препинания."""
        # Сортируем по длине (сначала длинные фразы)
        for word, punct in sorted(PUNCTUATION_MAP.items(), key=lambda x: -len(x[0])):
            # Ищем слово как отдельное (с пробелами или в начале/конце)
            pattern = r'(?<!\S)' + re.escape(word) + r'(?!\S)'
            text = re.sub(pattern, punct, text, flags=re.IGNORECASE)

        # Убираем пробелы перед знаками препинания
        for punct in NO_SPACE_BEFORE:
            text = text.replace(f" {punct}", punct)

        return text

    def _apply_capitalization(self, text: str) -> str:
        """Применить капитализацию."""
        if not text:
            return text

        result = []
        i = 0

        while i < len(text):
            char = text[i]

            if char.isalpha():
                if self._capitalize_next:
                    result.append(char.upper())
                    self._capitalize_next = False
                else:
                    result.append(char)
            else:
                result.append(char)
                # Проверяем нужно ли капитализировать следующее слово
                if char in CAPITALIZE_AFTER:
                    self._capitalize_next = True

            i += 1

        return "".join(result)

    def reset(self) -> None:
        """Сбросить состояние (начать новую диктовку)."""
        self._capitalize_next = True
        self._pending_space = False


# Глобальный экземпляр для использования между вызовами
_processor: Optional[TextPostProcessor] = None


def get_processor() -> TextPostProcessor:
    """Получить глобальный постобработчик."""
    global _processor
    if _processor is None:
        _processor = TextPostProcessor()
    return _processor


def process_text(text: str) -> List[Action]:
    """Обработать текст (удобная функция)."""
    return get_processor().process(text)


def reset_processor() -> None:
    """Сбросить состояние постобработчика."""
    get_processor().reset()
