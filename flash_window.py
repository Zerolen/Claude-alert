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
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.FlashWindowEx.argtypes = [ctypes.POINTER(FLASHWINFO)]
user32.FlashWindowEx.restype = wintypes.BOOL

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


def _windows_by_pid():
    """{pid: [(hwnd, длина_заголовка), ...]} для видимых окон верхнего уровня."""
    mapping = {}

    def cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            if cls.value not in _SHELL_CLASSES:
                title_len = user32.GetWindowTextLengthW(hwnd)
                mapping.setdefault(pid.value, []).append((hwnd, title_len))
        return True

    proc = WNDENUMPROC(cb)  # держим ссылку, пока идёт EnumWindows
    user32.EnumWindows(proc, 0)
    return mapping


def find_host_window(pid=None):
    """HWND окна ближайшего предка, у которого есть видимое окно. Или None."""
    pid = pid or os.getpid()
    wins = _windows_by_pid()
    for p in _ancestors(pid):
        if wins.get(p):
            # из нескольких окон процесса берём с самым длинным заголовком —
            # это почти всегда главное окно, а не вспомогательное.
            return max(wins[p], key=lambda t: t[1])[0]
    return None


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


if __name__ == "__main__":
    if not flash_host_window():
        print("Не нашёл окно-хост для мигания", file=sys.stderr)
    sys.exit(0)
