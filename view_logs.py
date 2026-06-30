#!/usr/bin/env python3
"""Утилита для просмотра логов воспроизведения звуков.

Примеры:
    python view_logs.py              # показать последние 10 событий
    python view_logs.py -n 20        # показать последние 20 событий
    python view_logs.py --errors     # показать только ошибки
    python view_logs.py --skipped    # показать только пропущенные звуки
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
LOGS_DIR = SCRIPT_DIR / "logs"


def load_logs(days: int = 7) -> list:
    """Загружает логи за последние N дней."""
    logs = []
    start_date = datetime.now() - timedelta(days=days)

    if not LOGS_DIR.exists():
        return logs

    for log_file in sorted(LOGS_DIR.glob("*.jsonl")):
        try:
            file_date = datetime.strptime(log_file.stem, "%Y-%m-%d")
            if file_date >= start_date:
                with open(log_file, encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            logs.append(json.loads(line))
        except (ValueError, json.JSONDecodeError):
            pass

    # Сортируем по timestamp
    logs.sort(key=lambda x: x.get("timestamp", ""))
    return logs


def format_log_entry(entry: dict, index: int) -> str:
    """Форматирует одну запись лога для вывода."""
    ts = entry.get("timestamp", "?")
    # Парсим ISO время и форматируем покороче
    try:
        dt = datetime.fromisoformat(ts)
        ts_short = dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        ts_short = ts

    event = entry.get("event") or entry.get("file", "?")
    volume = entry.get("volume", "?")

    # Статус (выполнено, пропущено, ошибка)
    if entry.get("error"):
        status = f"❌ ERROR: {entry['error']}"
    elif entry.get("skipped"):
        status = f"⏭️  SKIPPED: {entry.get('skip_reason', '?')}"
    else:
        status = "✅ PLAYED"
        if entry.get("actions"):
            actions = ", ".join(entry["actions"].keys())
            status += f" ({actions})"

    context_info = ""
    context = entry.get("context", {})
    if context.get("project"):
        context_info += f" | Project: {context['project']}"

    return f"{index:3d}. [{ts_short}] {event:30s} (vol: {volume:3}%) {status}{context_info}"


def main():
    parser = argparse.ArgumentParser(
        description="Просмотр логов воспроизведения звуков"
    )
    parser.add_argument(
        "-n", "--number", type=int, default=10,
        help="количество последних событий (по умолчанию 10)"
    )
    parser.add_argument(
        "-d", "--days", type=int, default=7,
        help="количество дней для загрузки (по умолчанию 7)"
    )
    parser.add_argument(
        "--errors", action="store_true",
        help="показать только события с ошибками"
    )
    parser.add_argument(
        "--skipped", action="store_true",
        help="показать только пропущенные звуки"
    )
    parser.add_argument(
        "--played", action="store_true",
        help="показать только воспроизведённые звуки"
    )
    args = parser.parse_args()

    logs = load_logs(args.days)

    # Фильтруем если нужно
    if args.errors:
        logs = [log for log in logs if log.get("error")]
    elif args.skipped:
        logs = [log for log in logs if log.get("skipped")]
    elif args.played:
        logs = [log for log in logs if not log.get("error") and not log.get("skipped")]

    if not logs:
        print("Нет логов для отображения.")
        return 0

    # Берём последние N
    logs = logs[-args.number:]

    print(f"\n{'Последние события воспроизведения звуков':^80}")
    print("=" * 80)

    for i, log in enumerate(logs, 1):
        print(format_log_entry(log, i))

    print("=" * 80)
    print(f"Всего: {len(logs)} событий")
    return 0


if __name__ == "__main__":
    sys.exit(main())
