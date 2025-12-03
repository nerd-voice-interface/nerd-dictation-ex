"""
Постобработка распознанного текста.

- Замена слов на знаки препинания
- Капитализация после точки/!/?
- Капитализация в начале диктовки
"""

import re
from typing import Optional


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

    def process(self, text: str) -> str:
        """
        Обработать текст: заменить слова на пунктуацию, капитализировать.

        Args:
            text: Распознанный текст

        Returns:
            Обработанный текст
        """
        if not text:
            return text

        # Заменяем слова на знаки препинания
        text = self._replace_punctuation(text)

        # Убираем лишние пробелы по краям
        text = text.strip()

        if not text:
            return text

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


def process_text(text: str) -> str:
    """Обработать текст (удобная функция)."""
    return get_processor().process(text)


def reset_processor() -> None:
    """Сбросить состояние постобработчика."""
    get_processor().reset()
