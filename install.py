#!/usr/bin/env python3
"""Устанавливает звуковые хуки в settings.json текущего пользователя.

Запускать на любой машине (обычно через install.bat). Скрипт сам:
  * находит папку текущего пользователя (~/.claude);
  * прописывает абсолютный путь к play_sound.py на ЭТОЙ машине;
  * аккуратно вмёрживает хуки Stop, Notification, PermissionRequest и PreToolUse
    (на вопрос с вариантами ответа — AskUserQuestion), не трогая остальное;
  * регистрирует URL-протокол claude-alert: (HKCU), чтобы клик по тосту
    поднимал нужное окно;
  * делает резервную копию settings.json перед изменением.

Повторный запуск безопасен — старые записи этой фичи заменяются новыми
(удобно, если папку с проектом перенесли).
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PLAYER = SCRIPT_DIR / "play_sound.py"
# (событие Claude Code, аргумент --event, матчер или None)
# ВНИМАНИЕ: у разных событий matcher фильтрует РАЗНОЕ:
#   PreToolUse / PermissionRequest — по имени инструмента (Bash, Edit|Write, …);
#   Notification — по ТИПУ уведомления (permission_prompt, idle_prompt, …).
EVENTS = [
    ("Stop", "stop", None),
    # Notification сужаем до idle_prompt — это «Claude ждёт ввода» (простой ~60с).
    # Запросы разрешения здесь НЕ ловим: для них есть отдельное надёжное событие
    # PermissionRequest (ниже). Раньше всё висело на Notification без матчера, и
    # на permission_prompt оно срабатывало непоследовательно (на Bash звук был,
    # на Write — нет).
    ("Notification", "notification", "idle_prompt"),
    # Любой запрос разрешения (Write/Edit/Bash/MCP/…). Без матчера ловит все
    # инструменты. Срабатывает ТОЛЬКО когда диалог реально показывается, поэтому
    # на авто-одобренные вызовы не пищит (в отличие от PreToolUse).
    ("PermissionRequest", "permission", None),
    # Меню «выбери вариант» — это инструмент AskUserQuestion. Это не запрос
    # разрешения, поэтому ловим его через PreToolUse с матчером по имени.
    ("PreToolUse", "question", "AskUserQuestion"),
]
MARKER = "play_sound.py"  # как опознаём наши хуки при повторной установке


def launcher() -> str:
    """Полный путь к интерпретатору. pythonw — без мелькающего окна консоли."""
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    return str(pyw if pyw.exists() else exe)


def build_command(event_arg: str) -> str:
    # '& "..."' — обязательно для PowerShell, чтобы запустить exe по полному пути
    return f'& "{launcher()}" "{PLAYER}" --event {event_arg}'


def register_protocol() -> bool:
    """Регистрирует URL-протокол claude-alert: для клика по тосту.

    Клик по тосту открывает URI claude-alert:raise?hint=..., и Windows
    запускает зарегистрированную здесь команду, передавая ей URI как %1.
    Команда поднимает нужное окно (flash_window.py --activate-url). Ключи
    пишем в HKCU — права администратора не нужны. Здесь это ПРЯМАЯ команда
    для CreateProcess, без обёртки '& "..."' (её понимает только PowerShell).
    """
    import winreg
    fw = SCRIPT_DIR / "flash_window.py"
    command = f'"{launcher()}" "{fw}" --activate-url "%1"'
    base = r"Software\Classes\claude-alert"
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, "URL:Claude Alert")
            winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              base + r"\shell\open\command") as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, command)
        return True
    except OSError as exc:
        print(f"Не удалось зарегистрировать протокол claude-alert: {exc}",
              file=sys.stderr)
        return False


def is_ours(group: dict) -> bool:
    return any(MARKER in h.get("command", "") for h in group.get("hooks", []))


def main() -> int:
    if not PLAYER.exists():
        print(f"Не найден {PLAYER} — запускайте install из папки с play_sound.py",
              file=sys.stderr)
        return 1

    claude_dir = Path.home() / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    settings_path = claude_dir / "settings.json"

    # читаем существующие настройки (или начинаем с пустых)
    settings = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"settings.json повреждён ({e}); прерываю, чтобы не потерять данные",
                  file=sys.stderr)
            return 1
        backup = settings_path.with_suffix(
            f".json.bak-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(settings_path, backup)
        print(f"Резервная копия: {backup}")

    hooks = settings.setdefault("hooks", {})
    for event, arg, matcher in EVENTS:
        groups = [g for g in hooks.get(event, []) if not is_ours(g)]  # убираем старое
        group = {
            "hooks": [{
                "type": "command",
                "shell": "powershell",
                "command": build_command(arg),
            }]
        }
        if matcher is not None:
            group["matcher"] = matcher
        groups.append(group)
        hooks[event] = groups

    settings_path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    if register_protocol():
        print("Протокол claude-alert: зарегистрирован (клик по тосту фокусирует окно).")

    print(f"Готово. Хуки записаны в {settings_path}")
    print(f"Интерпретатор: {launcher()}")
    print(f"Плеер:         {PLAYER}")
    print("\nЧтобы хуки заработали — откройте /hooks в Claude Code или перезапустите его.")
    return 0


if __name__ == "__main__":
    # вывод кириллицы не должен падать на старых кодировках консоли
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    sys.exit(main())
