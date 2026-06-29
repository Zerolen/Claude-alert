#!/usr/bin/env python3
"""Проигрывает звук (wav/mp3) с регулировкой громкости на Windows.

Использует встроенный winmm (MCI) через ctypes — сторонних библиотек не нужно.

Примеры:
    python play_sound.py --event stop
    python play_sound.py "C:\\Windows\\Media\\chimes.wav" --volume 50
    python play_sound.py beep.mp3 -v 100

Громкость задаётся в процентах 0..100.
События (--event) и их звуки/громкость настраиваются в sounds.json
рядом с этим скриптом.
"""
import argparse
import ctypes
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "sounds.json"


def _mci(command: str):
    """Отправляет одну MCI-команду, возвращает (код_ошибки, ответ)."""
    buf = ctypes.create_unicode_buffer(255)
    err = ctypes.windll.winmm.mciSendStringW(
        ctypes.c_wchar_p(command), buf, 254, 0
    )
    return err, buf.value


def play(file_path: str, volume: int = 100) -> int:
    """Проигрывает файл с заданной громкостью (0..100). Блокирует до конца."""
    path = Path(file_path).expanduser()
    if not path.is_absolute():
        path = (SCRIPT_DIR / path).resolve()
    if not path.exists():
        print(f"Файл не найден: {path}", file=sys.stderr)
        return 1

    volume = max(0, min(100, int(volume)))
    mci_volume = round(volume * 10)  # MCI: 0..1000

    alias = "claude_alert_snd"
    # type mpegvideo проигрывает и wav, и mp3, и поддерживает громкость
    err, _ = _mci(f'open "{path}" type mpegvideo alias {alias}')
    if err:
        # запасной вариант: дать MCI определить устройство по расширению
        err, _ = _mci(f'open "{path}" alias {alias}')
        if err:
            print(f"Не удалось открыть файл (MCI ошибка {err})", file=sys.stderr)
            return 1
    try:
        _mci(f"setaudio {alias} volume to {mci_volume}")
        _mci(f"play {alias} wait")
    finally:
        _mci(f"close {alias}")
    return 0


def load_event(event: str):
    """Возвращает (file, volume) для события из sounds.json."""
    if not CONFIG_PATH.exists():
        print(f"Нет файла конфигурации: {CONFIG_PATH}", file=sys.stderr)
        return None
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Ошибка в {CONFIG_PATH}: {e}", file=sys.stderr)
        return None
    entry = cfg.get(event)
    if not entry:
        print(f"Событие '{event}' не описано в {CONFIG_PATH}", file=sys.stderr)
        return None
    return entry.get("file"), int(entry.get("volume", 100))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Проигрывает звук (wav/mp3) с регулировкой громкости."
    )
    parser.add_argument("file", nargs="?", help="путь к wav/mp3 файлу")
    parser.add_argument(
        "-v", "--volume", type=int, default=None,
        help="громкость 0..100 (по умолчанию 100, либо из sounds.json)",
    )
    parser.add_argument(
        "-e", "--event",
        help="имя события из sounds.json (например stop, notification)",
    )
    args = parser.parse_args(argv)

    if args.event:
        loaded = load_event(args.event)
        if not loaded:
            return 1
        file_path, vol = loaded
        if args.volume is not None:  # CLI перекрывает конфиг
            vol = args.volume
    elif args.file:
        file_path, vol = args.file, (args.volume if args.volume is not None else 100)
    else:
        parser.error("укажите файл или --event")
        return 2

    return play(file_path, vol)


if __name__ == "__main__":
    # Никогда не валим хук ненулевым кодом из-за проблем со звуком
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"play_sound: {exc}", file=sys.stderr)
        sys.exit(0)
