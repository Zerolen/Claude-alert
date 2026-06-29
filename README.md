# Claude-alert

Звуковые уведомления для [Claude Code](https://claude.com/claude-code) на Windows.
Проигрывает звук, когда Claude завершает ответ (`Stop`), присылает уведомление
(`Notification`) или показывает меню с вариантами ответа (`AskUserQuestion`), —
чтобы не пропускать момент, когда нужна ваша реакция.

Работает на встроенном `winmm` (MCI) через `ctypes` — сторонние библиотеки не нужны,
только Python 3.

## Установка

1. Установите [Python 3](https://www.python.org/) (если ещё нет).
2. Дважды кликните по **`install.bat`**.

Скрипт сам:

* находит папку `~/.claude` текущего пользователя;
* прописывает абсолютный путь к `play_sound.py` на этой машине;
* аккуратно вмёрживает хуки `Stop`, `Notification` и `PreToolUse`
  (звук на меню `AskUserQuestion`) в `settings.json`, не трогая остальное;
* делает резервную копию `settings.json` перед изменением.

Повторный запуск безопасен — старые записи этой фичи заменяются новыми
(удобно, если папку с проектом перенесли).

После установки откройте `/hooks` в Claude Code или перезапустите его, чтобы хуки заработали.

## Настройка звуков

Звуки и громкость для каждого события задаются в [`sounds.json`](sounds.json):

```json
{
  "stop": {
    "file": "sounds/yes-success.wav",
    "volume": 100
  },
  "notification": {
    "file": "sounds/zaeblo-vse.wav",
    "volume": 100
  },
  "question": {
    "file": "sounds/zaeblo-vse.wav",
    "volume": 100
  }
}
```

* `question` — звук на меню с вариантами ответа (инструмент `AskUserQuestion`).

* `file` — путь к `.wav` или `.mp3` (относительный путь считается от папки проекта);
* `volume` — громкость в процентах `0..100`.

## Проверка вручную

```bash
python play_sound.py --event stop
python play_sound.py "C:\Windows\Media\chimes.wav" --volume 50
python play_sound.py beep.mp3 -v 100
```

## Файлы

| Файл | Назначение |
|------|------------|
| `install.bat` / `install.py` | Установка хуков в `settings.json` |
| `play_sound.py` | Проигрывание звука с регулировкой громкости |
| `sounds.json` | Какой звук и громкость для каждого события |
| `sounds/` | Сами звуковые файлы |
