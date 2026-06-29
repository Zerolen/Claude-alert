#!/usr/bin/env python3
"""Удаляет звуковые хуки этой фичи из settings.json текущего пользователя.

Обратная операция к install.py. Скрипт сам:
  * находит папку текущего пользователя (~/.claude);
  * удаляет ТОЛЬКО наши группы хуков (опознаём по play_sound.py),
    не трогая остальные хуки и настройки;
  * убирает опустевшие массивы событий и пустой раздел "hooks";
  * делает резервную копию settings.json перед изменением.

Повторный запуск безопасен — если наших хуков уже нет, файл не меняется.
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

MARKER = "play_sound.py"  # как опознаём наши хуки


def is_ours(group: dict) -> bool:
    return any(MARKER in h.get("command", "") for h in group.get("hooks", []))


def main() -> int:
    claude_dir = Path.home() / ".claude"
    settings_path = claude_dir / "settings.json"

    if not settings_path.exists():
        print(f"settings.json не найден ({settings_path}) — удалять нечего.")
        return 0

    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"settings.json повреждён ({e}); прерываю, чтобы не потерять данные",
              file=sys.stderr)
        return 1

    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        print("Раздел hooks отсутствует — наших хуков нет.")
        return 0

    removed = 0
    for event in list(hooks.keys()):
        groups = hooks.get(event, [])
        kept = [g for g in groups if not is_ours(g)]
        removed += len(groups) - len(kept)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]  # массив опустел — убираем событие целиком

    if removed == 0:
        print("Наших хуков в settings.json не найдено — изменений нет.")
        return 0

    if not hooks:
        del settings["hooks"]  # раздел опустел — убираем его

    # резервная копия только когда реально что-то меняем
    backup = settings_path.with_suffix(
        f".json.bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(settings_path, backup)
    print(f"Резервная копия: {backup}")

    settings_path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    print(f"Готово. Удалено групп хуков: {removed}. Файл: {settings_path}")
    print("\nЧтобы изменения вступили в силу — откройте /hooks в Claude Code "
          "или перезапустите его.")
    return 0


if __name__ == "__main__":
    # вывод кириллицы не должен падать на старых кодировках консоли
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    sys.exit(main())
