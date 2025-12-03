# nerd-dictation-ex

Расширенная версия [nerd-dictation](https://github.com/ideasman42/nerd-dictation) с модульной архитектурой и подключаемыми бэкендами распознавания речи.

## Возможности

- **Daemon с моделью в памяти**: Мгновенный отклик, модель загружается один раз
- **Подключаемые бэкенды**: Устанавливаются отдельно как Python-пакеты
- **Автоустановка моделей**: Скрипты для скачивания моделей
- **Переключение через конфиг**: TOML-файл для настройки
- **Wayland/X11/TTY**: Работает везде через ydotool/dotool
- **Systemd интеграция**: Автозапуск daemon при логине
- **Оптимизирован для русского языка**

## Архитектура

```
nerd-dictation-ex          # Ядро (CLI, конфиг, аудио)
├── nerd-dictation-vosk    # Бэкенд Vosk (CPU)
└── nerd-dictation-gigaam  # Бэкенд GigaAM (GPU)
```

Каждый бэкенд — отдельный pip-пакет со своими зависимостями.

## Сравнение бэкендов

| Бэкенд | Стриминг | GPU | WER (русский) | Пунктуация |
|--------|----------|-----|---------------|------------|
| Vosk   | ✅ Да    | ❌  | ~33%          | ❌         |
| GigaAM | ❌ Batch | ✅  | ~5-7%         | ✅ (e2e)   |

## Установка

### Зависимости (Arch Linux)

```bash
# Аудио захват
sudo pacman -S pipewire-pulse  # для pw-cat (рекомендуется)

# Симуляция ввода
yay -S ydotool                 # для Wayland (рекомендуется)
```

### Установка ядра

```bash
git clone https://github.com/marcusmae/nerd-dictation-ex
cd nerd-dictation-ex
pip install -e .
```

### Установка бэкендов

#### Vosk (CPU, потоковый)

```bash
# Установка пакета
cd backends/vosk
pip install -e .

# Установка модели
nerd-dictation-vosk-setup --model small   # ~45MB
# или
nerd-dictation-vosk-setup --model large   # ~1.5GB, лучше качество
```

#### GigaAM (GPU, высокое качество)

```bash
# Установка пакета
cd backends/gigaam
pip install -e .

# Установка GigaAM и проверка GPU
nerd-dictation-gigaam-setup
```

## Конфигурация

```bash
mkdir -p ~/.config/nerd-dictation-ex
cp config/default.toml ~/.config/nerd-dictation-ex/config.toml
```

Отредактируйте `~/.config/nerd-dictation-ex/config.toml`:

```toml
[general]
backend = "vosk"        # или "gigaam"
input_method = "ydotool"

[vosk]
model_path = "~/.local/share/vosk/vosk-model-ru"

[gigaam]
model_name = "v3_ctc"   # или v3_e2e_rnnt для лучшего качества
device = "cuda"         # или "cpu"
```

## Использование

### Рекомендуемый workflow (daemon)

```bash
# 1. Запустить daemon (модель загружается в память)
nerd-dictation-ex daemon start

# 2. Диктовка (мгновенный отклик!)
nerd-dictation-ex begin    # Начать
nerd-dictation-ex end      # Завершить
nerd-dictation-ex cancel   # Отменить

# 3. Управление daemon
nerd-dictation-ex daemon status              # Статус
nerd-dictation-ex daemon reload -b gigaam    # Сменить бэкенд
nerd-dictation-ex daemon stop                # Остановить
```

### Без daemon (медленный старт)

```bash
# Модель загружается каждый раз (~3-10 сек)
nerd-dictation-ex begin --no-daemon &
nerd-dictation-ex end
```

### Systemd (автозапуск)

```bash
# Установить и включить
cp systemd/nerd-dictation-ex.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now nerd-dictation-ex

# Теперь daemon запускается при логине
```

### Привязка к клавишам

#### Вариант 1: Клавиатура (i3/Sway/Hyprland)

Для i3/Sway (`~/.config/i3/config` или `~/.config/sway/config`):

```
bindsym $mod+Shift+grave exec /path/to/nerd-dictation-ex toggle
```

Для Hyprland (`~/.config/hypr/hyprland.conf`):

```
bind = $mod SHIFT, grave, exec, /path/to/nerd-dictation-ex toggle
```

#### Вариант 2: Кнопка мыши/тачпада (xbindkeys)

Для привязки к средней кнопке мыши или тачпада:

```bash
# Установить xbindkeys
sudo pacman -S xbindkeys  # Arch Linux

# Создать конфиг
cat > ~/.xbindkeysrc << 'EOF'
"/path/to/nerd-dictation-ex toggle"
  b:2
EOF

# Запустить
xbindkeys
```

Добавьте автозапуск в конфиг оконного менеджера:

```
# i3/Sway
exec --no-startup-id xbindkeys

# Hyprland
exec-once = xbindkeys
```

Коды кнопок: `b:1` — левая, `b:2` — средняя, `b:3` — правая.

## Создание своего бэкенда

1. Создайте структуру:

```
backends/my_backend/
├── pyproject.toml
├── README.md
└── src/nerd_dictation_mybackend/
    ├── __init__.py
    ├── backend.py
    └── setup.py        # скрипт установки моделей
```

2. В `backend.py`:

```python
from nerd_dictation_ex.backends.base import ASRBackend, ASRResult

class MyBackend(ASRBackend):
    name = "my_backend"
    supports_streaming = True

    def load_model(self, model_path, **kwargs):
        ...

    def transcribe_stream(self, audio_stream, sample_rate=16000):
        for chunk in audio_stream:
            yield ASRResult(text="...", is_final=True)

    def transcribe_file(self, audio_path):
        ...
```

3. В `pyproject.toml`:

```toml
[project.entry-points."nerd_dictation_ex.backends"]
my_backend = "nerd_dictation_mybackend:MyBackend"
```

4. Установите: `pip install -e backends/my_backend`

## Структура проекта

```
nerd-dictation-ex/
├── src/nerd_dictation_ex/       # Ядро
│   ├── __init__.py
│   ├── cli.py                   # CLI
│   └── backends/
│       ├── __init__.py          # Динамическая загрузка
│       └── base.py              # Базовый класс ASRBackend
├── backends/
│   ├── vosk/                    # nerd-dictation-vosk
│   │   ├── pyproject.toml
│   │   └── src/nerd_dictation_vosk/
│   └── gigaam/                  # nerd-dictation-gigaam
│       ├── pyproject.toml
│       └── src/nerd_dictation_gigaam/
├── config/
│   └── default.toml
├── pyproject.toml
└── README.md
```

## Лицензия

GPL-3.0 (как оригинальный nerd-dictation)

## Благодарности

- [nerd-dictation](https://github.com/ideasman42/nerd-dictation) — оригинальный проект
- [Vosk](https://alphacephei.com/vosk/) — Alphacephei
- [GigaAM](https://github.com/salute-developers/GigaAM) — Сбер
