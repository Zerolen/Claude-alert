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
import os
import subprocess
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

    # Уникальный alias на процесс — чтобы параллельные звуки не конфликтовали.
    alias = f"claude_alert_snd_{os.getpid()}"
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


def play_detached(file_path: str, volume: int = 100) -> int:
    """Запускает проигрывание в отдельном фоновом процессе и сразу возвращается.

    Нужно для хуков PreToolUse (AskUserQuestion, Bash): они блокируют появление
    меню/запроса до завершения хука. Раньше звук доигрывался целиком, и только
    потом Claude задавал вопрос. Теперь звук играет параллельно.
    """
    # pythonw.exe — без мелькающего окна консоли (как и в install.py)
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    launcher = str(pyw if pyw.exists() else exe)

    # DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP — отвязать от консоли хука.
    # CREATE_BREAKAWAY_FROM_JOB — ключевое для PreToolUse: Claude запускает такой
    # хук в Job-объекте и убивает всё его дерево процессов, как только хук вернул
    # управление (чтобы тут же показать меню/запрос). Без breakaway наш фоновый
    # процесс умирает раньше, чем успеет издать звук. Для Stop этого не нужно,
    # поэтому раньше звучал только он.
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    CREATE_BREAKAWAY_FROM_JOB = 0x01000000
    cmd = [launcher, str(Path(__file__).resolve()),
           "--_play-now", file_path, "--volume", str(volume)]
    base_flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(
            cmd,
            creationflags=base_flags | CREATE_BREAKAWAY_FROM_JOB,
            close_fds=True,
        )
    except OSError:
        # Job не разрешает breakaway — пробуем без него.
        try:
            subprocess.Popen(cmd, creationflags=base_flags, close_fds=True)
        except Exception as exc:  # noqa: BLE001
            print(f"play_detached: {exc}", file=sys.stderr)
            return play(file_path, volume)  # лучше с задержкой, чем без звука
    except Exception as exc:  # noqa: BLE001
        print(f"play_detached: {exc}", file=sys.stderr)
        return play(file_path, volume)
    return 0


def load_event(event: str):
    """Возвращает (file, volume, flash) для события из sounds.json."""
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
    return (entry.get("file"),
            int(entry.get("volume", 100)),
            bool(entry.get("flash", True)),
            bool(entry.get("raise", False)))


def flash_window():
    """Мигнуть кнопкой своего окна-хоста в панели задач. Ошибки не критичны."""
    try:
        from flash_window import flash_host_window
        flash_host_window()
    except Exception as exc:  # noqa: BLE001
        print(f"flash_window: {exc}", file=sys.stderr)


def raise_window():
    """Вытащить своё окно-хост поверх остальных. Ошибки не критичны."""
    try:
        from flash_window import raise_host_window
        raise_host_window()
    except Exception as exc:  # noqa: BLE001
        print(f"raise_window: {exc}", file=sys.stderr)


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
    parser.add_argument(
        "--flash", dest="flash", action="store_true", default=None,
        help="мигнуть окном-хостом в панели задач (перекрывает sounds.json)",
    )
    parser.add_argument(
        "--no-flash", dest="flash", action="store_false",
        help="не мигать окном (перекрывает sounds.json)",
    )
    parser.add_argument(
        "--raise", dest="raise_", action="store_true", default=None,
        help="вытащить окно-хост поверх остальных (перекрывает sounds.json)",
    )
    parser.add_argument(
        "--no-raise", dest="raise_", action="store_false",
        help="не поднимать окно наверх (перекрывает sounds.json)",
    )
    parser.add_argument(
        "--_play-now", dest="play_now", action="store_true",
        help=argparse.SUPPRESS,  # внутренний режим: синхронно играет в фоне-процессе
    )
    parser.add_argument(
        "--sync", dest="sync", action="store_true",
        help="играть синхронно (блокировать до конца), не в фоне",
    )
    args = parser.parse_args(argv)

    # Внутренний режим: нас запустил play_detached(), просто играем и выходим.
    if args.play_now:
        vol = args.volume if args.volume is not None else 100
        return play(args.file, vol)

    if args.event:
        loaded = load_event(args.event)
        if not loaded:
            return 1
        file_path, vol, do_flash, do_raise = loaded
        if args.volume is not None:  # CLI перекрывает конфиг
            vol = args.volume
        if args.flash is not None:   # CLI перекрывает конфиг
            do_flash = args.flash
        if args.raise_ is not None:  # CLI перекрывает конфиг
            do_raise = args.raise_
    elif args.file:
        file_path = args.file
        vol = args.volume if args.volume is not None else 100
        do_flash = bool(args.flash)  # для прямого файла по умолчанию не мигаем
        do_raise = bool(args.raise_)
    else:
        parser.error("укажите файл или --event")
        return 2

    # Мигание/подъём запускаем до звука: ОС реагирует сама и после выхода скрипта.
    if do_raise:
        raise_window()
    elif do_flash:
        flash_window()
    # По умолчанию звук играет в фоне, чтобы хук не блокировал появление
    # вопроса/запроса. --sync оставляет старое блокирующее поведение.
    if args.sync:
        return play(file_path, vol)
    return play_detached(file_path, vol)


if __name__ == "__main__":
    # Никогда не валим хук ненулевым кодом из-за проблем со звуком
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"play_sound: {exc}", file=sys.stderr)
        sys.exit(0)
