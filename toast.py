#!/usr/bin/env python3
"""Показывает всплывающее уведомление (toast) Windows. Без сторонних библиотек.

Зачем: звук говорит «Claude зовёт», но при нескольких открытых окнах не ясно,
какое именно. Тост пишет в тексте имя проекта, а по клику поднимает наверх
именно то окно (через кастомный протокол claude-alert:, см. install.py).

Как показываем: штатный WinRT-API уведомлений (Windows.UI.Notifications)
дёргаем из PowerShell. Чтобы тост вообще появился без регистрации ярлыка в
меню «Пуск», берём «чужой», но всегда зарегистрированный AppUserModelID самого
PowerShell — обычный приём. Поэтому в шапке уведомления будет «Windows
PowerShell»; зато не нужен установщик COM-активатора.

Клик: атрибут launch + activationType="protocol" — Windows просто открывает
URI claude-alert:..., как ссылку. Это не требует COM-сервера активации,
в отличие от кнопок с activationType="foreground".

Можно запускать как скрипт для проверки:
    python toast.py "Заголовок" "Текст" --launch "claude-alert:raise?hint=proj"
"""
import base64
import subprocess
import sys
from xml.sax.saxutils import escape, quoteattr

# AppUserModelID PowerShell — позволяет тосту появиться без своего ярлыка.
DEFAULT_AUMID = (
    r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}"
    r"\WindowsPowerShell\v1.0\powershell.exe"
)


def build_xml(title: str, message: str, launch: str | None = None) -> str:
    """Собрать XML тоста (шаблон ToastGeneric). Текст безопасно экранируется."""
    if launch:
        # quoteattr добавит кавычки и экранирует спецсимволы внутри атрибута.
        launch_attr = f" launch={quoteattr(launch)} activationType=\"protocol\""
    else:
        launch_attr = ""
    return (
        f"<toast{launch_attr}>"
        "<visual><binding template=\"ToastGeneric\">"
        f"<text>{escape(title)}</text>"
        f"<text>{escape(message)}</text>"
        "</binding></visual>"
        "</toast>"
    )


def _build_ps(xml: str, aumid: str) -> str:
    """PowerShell-скрипт, который загружает XML и показывает тост."""
    xml_ps = xml.replace("'", "''")      # экранируем для одинарных кавычек PS
    aumid_ps = aumid.replace("'", "''")
    return (
        "$ErrorActionPreference='Stop';"
        "[void][Windows.UI.Notifications.ToastNotificationManager,"
        "Windows.UI.Notifications,ContentType=WindowsRuntime];"
        "[void][Windows.Data.Xml.Dom.XmlDocument,"
        "Windows.Data.Xml.Dom,ContentType=WindowsRuntime];"
        "$x=New-Object Windows.Data.Xml.Dom.XmlDocument;"
        f"$x.LoadXml('{xml_ps}');"
        "$t=New-Object Windows.UI.Notifications.ToastNotification $x;"
        "[Windows.UI.Notifications.ToastNotificationManager]::"
        f"CreateToastNotifier('{aumid_ps}').Show($t);"
    )


def show(title: str, message: str, launch: str | None = None,
         aumid: str = DEFAULT_AUMID) -> bool:
    """Показать тост. Запускает PowerShell в фоне и сразу возвращается."""
    ps = _build_ps(build_xml(title, message, launch), aumid)
    # -EncodedCommand принимает base64 от UTF-16LE — обходим все проблемы с
    # кавычками и кириллицей в командной строке.
    encoded = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
    cmd = ["powershell", "-NoProfile", "-NonInteractive",
           "-EncodedCommand", encoded]

    # CREATE_NO_WINDOW — без мелькающего окна консоли.
    # CREATE_BREAKAWAY_FROM_JOB — как в play_sound.play_detached: на хуке
    # PreToolUse Claude убивает дерево процессов хука сразу после возврата, и без
    # breakaway тост не успевает показаться.
    # ВАЖНО: DETACHED_PROCESS здесь НЕ используем. С ним WinRT-уведомление
    # создаётся без ошибки, но баннер не доставляется (процесс теряет привязку к
    # интерактивной сессии). Проверено: DETACHED — нет тоста, без него — есть.
    CREATE_NO_WINDOW = 0x08000000
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    CREATE_BREAKAWAY_FROM_JOB = 0x01000000
    base_flags = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(cmd, creationflags=base_flags | CREATE_BREAKAWAY_FROM_JOB,
                         close_fds=True)
        return True
    except OSError:
        try:
            subprocess.Popen(cmd, creationflags=base_flags, close_fds=True)
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"toast: {exc}", file=sys.stderr)
            return False
    except Exception as exc:  # noqa: BLE001
        print(f"toast: {exc}", file=sys.stderr)
        return False


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Показать toast-уведомление Windows.")
    parser.add_argument("title", help="заголовок уведомления")
    parser.add_argument("message", nargs="?", default="", help="текст уведомления")
    parser.add_argument("--launch", help="URI для открытия по клику (claude-alert:...)")
    parser.add_argument("--aumid", default=DEFAULT_AUMID, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    ok = show(args.title, args.message, args.launch, args.aumid)
    return 0 if ok else 1


if __name__ == "__main__":
    # Никогда не валим хук ненулевым кодом из-за проблем с уведомлением.
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"toast: {exc}", file=sys.stderr)
        sys.exit(0)
