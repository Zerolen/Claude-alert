#!/usr/bin/env python3
"""Мигает кнопкой нужного окна-хоста в панели задач (стандартный Windows).

Зачем: когда у вас открыто несколько окон VSCode (или терминалов), один лишь
звук не подсказывает, какое из них зовёт. Эта функция заставляет кнопку именно
того окна, из которого работает Claude Code, мигать «жёлтым» в панели задач,
пока вы на него не переключитесь — обычная виндовс-логика FlashWindowEx.

Как находим «своё» окно: поднимаемся по дереву процессов от текущего процесса
к предкам и берём ближайшего предка, у которого есть видимое окно верхнего
уровня. Для интегрированного терминала VSCode это будет окно самого VSCode,
для внешнего терминала — окно терминала. Идём от ближнего предка к дальнему,
поэтому до окна проводника (explorer) дело не доходит.

Только стандартный WinAPI через ctypes — сторонних библиотек не нужно.
Можно запускать как скрипт для проверки:  python flash_window.py
"""
import ctypes
import os
import sys
from ctypes import wintypes

kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

# --- Toolhelp: карта процессов pid -> ppid ---------------------------------
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


# --- FlashWindowEx ----------------------------------------------------------
class FLASHWINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("hwnd", wintypes.HWND),
        ("dwFlags", wintypes.DWORD),
        ("uCount", wintypes.UINT),
        ("dwTimeout", wintypes.DWORD),
    ]


FLASHW_STOP = 0
FLASHW_CAPTION = 0x00000001
FLASHW_TRAY = 0x00000002        # мигать кнопкой в панели задач
FLASHW_ALL = 0x00000003
FLASHW_TIMER = 0x00000004
FLASHW_TIMERNOFG = 0x0000000C   # мигать, пока окно не выйдет на передний план

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

# Явные сигнатуры — иначе на 64-бит указатели (HWND/HANDLE) усекаются до int.
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.Process32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
kernel32.Process32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.FlashWindowEx.argtypes = [ctypes.POINTER(FLASHWINFO)]
user32.FlashWindowEx.restype = wintypes.BOOL

# --- подъём окна на передний план -----------------------------------------
SW_RESTORE = 9
user32.GetForegroundWindow.restype = wintypes.HWND
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL

# Окна рабочего стола/панели задач — никогда не мигаем ими.
_SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
                  "Button", "NotifyIconOverflowWindow"}


def _parent_map():
    """{pid: ppid} для всех процессов системы."""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        return {}
    parents = {}
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    try:
        if not kernel32.Process32First(snap, ctypes.byref(entry)):
            return {}
        while True:
            parents[entry.th32ProcessID] = entry.th32ParentProcessID
            if not kernel32.Process32Next(snap, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snap)
    return parents


def _ancestors(pid):
    """Список предков pid от ближнего к дальнему (включая сам pid)."""
    parents = _parent_map()
    chain, seen, cur = [], set(), pid
    while cur and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        cur = parents.get(cur, 0)
    return chain


def _window_title(hwnd):
    """Текст заголовка окна (пустая строка, если его нет)."""
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def _windows_by_pid():
    """{pid: [(hwnd, заголовок), ...]} для видимых окон верхнего уровня."""
    mapping = {}

    def cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            if cls.value not in _SHELL_CLASSES:
                mapping.setdefault(pid.value, []).append((hwnd, _window_title(hwnd)))
        return True

    proc = WNDENUMPROC(cb)  # держим ссылку, пока идёт EnumWindows
    user32.EnumWindows(proc, 0)
    return mapping


def _workspace_hint():
    """Имя рабочей папки проекта — его VSCode пишет в заголовок окна.

    Один процесс VSCode владеет окнами всех открытых воркспейсов, поэтому
    по заголовку приходится отличать «своё» окно от чужих. Claude Code
    задаёт CLAUDE_PROJECT_DIR в хуках; иначе берём текущую папку.
    """
    base = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return os.path.basename(os.path.normpath(base)) if base else ""


def _pick_window(windows, hint):
    """Из окон процесса выбрать самое подходящее.

    Если в заголовке есть имя рабочей папки (hint) — берём такое окно
    (это нужный воркспейс VSCode). Иначе — окно с самым длинным
    заголовком: почти всегда это главное окно, а не вспомогательное.
    """
    if hint:
        matches = [w for w in windows if hint.lower() in (w[1] or "").lower()]
        if matches:
            return max(matches, key=lambda t: len(t[1]))[0]
    return max(windows, key=lambda t: len(t[1]))[0]


def find_host_window(pid=None, hint=None):
    """HWND окна ближайшего предка, у которого есть видимое окно. Или None."""
    pid = pid or os.getpid()
    if hint is None:
        hint = _workspace_hint()
    wins = _windows_by_pid()
    for p in _ancestors(pid):
        if wins.get(p):
            return _pick_window(wins[p], hint)
    return None


def find_window_by_hint(hint):
    """HWND видимого окна, в заголовке которого встречается hint. Или None.

    В отличие от find_host_window, не опирается на дерево процессов — нужно для
    обработчика клика по тосту, который Windows запускает отдельным процессом
    (потомок проводника), уже не связанным с нашим окном. Из подходящих окон
    берём с самым длинным заголовком (обычно это главное окно воркспейса).
    """
    if not hint:
        return None
    hint_l = hint.lower()
    candidates = []
    for wins in _windows_by_pid().values():
        for hwnd, title in wins:
            if title and hint_l in title.lower():
                candidates.append((hwnd, title))
    if not candidates:
        return None
    return max(candidates, key=lambda t: len(t[1]))[0]


def activate_from_url(url):
    """Обработчик протокола claude-alert: — поднять окно по hint из URL.

    URL вида  claude-alert:raise?hint=<имя_проекта>. Если по hint окно не нашли,
    пробуем обычный поиск по дереву процессов как запасной вариант.
    """
    from urllib.parse import parse_qs, unquote
    hint = ""
    try:
        rest = url.split(":", 1)[1] if ":" in url else url
        query = rest.split("?", 1)[1] if "?" in rest else ""
        values = parse_qs(query).get("hint", [])
        hint = unquote(values[0]) if values else ""
    except Exception:  # noqa: BLE001
        hint = ""
    hwnd = find_window_by_hint(hint) if hint else None
    if not hwnd:
        hwnd = find_host_window()
    if not hwnd:
        return False
    return raise_window(hwnd)


def flash(hwnd, count=0, flags=FLASHW_TRAY | FLASHW_TIMERNOFG):
    """Мигнуть окном hwnd. count=0 + TIMERNOFG = пока не переключатся на окно."""
    info = FLASHWINFO()
    info.cbSize = ctypes.sizeof(FLASHWINFO)
    info.hwnd = hwnd
    info.dwFlags = flags
    info.uCount = count
    info.dwTimeout = 0
    return bool(user32.FlashWindowEx(ctypes.byref(info)))


def flash_host_window():
    """Найти своё окно-хост и мигнуть им. True, если окно нашлось."""
    hwnd = find_host_window()
    if not hwnd:
        return False
    flash(hwnd)
    return True


def raise_window(hwnd):
    """Вытащить окно hwnd поверх остальных и сделать активным.

    Windows не даёт фоновому процессу просто так перехватить фокус —
    SetForegroundWindow срабатывает только у потока, владеющего активным
    окном. Обходим это: на время «приклеиваемся» к потоку текущего
    переднего окна (AttachThreadInput), и тогда система разрешает смену
    фокуса. Свёрнутое окно сперва разворачиваем.
    """
    if not hwnd:
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)

    fg = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    our_thread = kernel32.GetCurrentThreadId()

    attached = False
    if fg_thread and fg_thread != our_thread:
        attached = bool(user32.AttachThreadInput(our_thread, fg_thread, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(our_thread, fg_thread, False)
    return True


def raise_host_window():
    """Найти своё окно-хост и поднять его наверх. True, если окно нашлось."""
    hwnd = find_host_window()
    if not hwnd:
        return False
    return raise_window(hwnd)


def is_host_window_foreground():
    """True, если окно-хост сейчас на переднем плане (в фокусе).

    Нужно, чтобы не дёргать пользователя звуком/миганием/тостом, когда он и так
    смотрит именно на это окно. Если своё окно не нашли — считаем, что оно не
    в фокусе (лучше лишний раз уведомить, чем промолчать).
    """
    hwnd = find_host_window()
    if not hwnd:
        return False
    return user32.GetForegroundWindow() == hwnd


if __name__ == "__main__":
    args = sys.argv[1:]
    # --activate-url <URI> — вызывается из обработчика протокола claude-alert:
    if "--activate-url" in args:
        i = args.index("--activate-url")
        url = args[i + 1] if i + 1 < len(args) else ""
        try:
            activate_from_url(url)
        except Exception as exc:  # noqa: BLE001
            print(f"activate: {exc}", file=sys.stderr)
        sys.exit(0)

    bring_up = "--raise" in args
    ok = raise_host_window() if bring_up else flash_host_window()
    if not ok:
        print("Не нашёл окно-хост", file=sys.stderr)
    sys.exit(0)
