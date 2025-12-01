# Systemd интеграция

## Установка как user service

```bash
# Копируем unit файл
mkdir -p ~/.config/systemd/user
cp systemd/nerd-dictation-ex.service ~/.config/systemd/user/

# Перезагружаем systemd
systemctl --user daemon-reload

# Включаем автозапуск
systemctl --user enable nerd-dictation-ex

# Запускаем
systemctl --user start nerd-dictation-ex

# Проверяем статус
systemctl --user status nerd-dictation-ex
```

## Управление

```bash
# Перезапустить (например, после смены конфига)
systemctl --user restart nerd-dictation-ex

# Посмотреть логи
journalctl --user -u nerd-dictation-ex -f

# Остановить
systemctl --user stop nerd-dictation-ex

# Отключить автозапуск
systemctl --user disable nerd-dictation-ex
```

## Использование

После запуска daemon через systemd:

```bash
# Начать диктовку (мгновенно, модель уже в памяти)
nerd-dictation-ex begin

# Завершить
nerd-dictation-ex end
```

## Привязка клавиш

### Hyprland

```
bind = , F9, exec, nerd-dictation-ex begin
bind = , F10, exec, nerd-dictation-ex end
bind = , F11, exec, nerd-dictation-ex cancel
```

### Sway

```
bindsym F9 exec nerd-dictation-ex begin
bindsym F10 exec nerd-dictation-ex end
bindsym F11 exec nerd-dictation-ex cancel
```

## Troubleshooting

### Daemon не запускается

Проверьте логи:
```bash
journalctl --user -u nerd-dictation-ex --no-pager
```

### Нет звука (pw-cat не работает)

Убедитесь, что PipeWire запущен:
```bash
systemctl --user status pipewire
```

### Модель не загружается

Проверьте, что бэкенд установлен:
```bash
nerd-dictation-ex list-backends
```

И модель скачана:
```bash
nerd-dictation-vosk-setup --list
# или
nerd-dictation-gigaam-setup --check
```
