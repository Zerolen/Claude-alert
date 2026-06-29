@echo off
rem Установка звуковых хуков для текущего пользователя Windows.
rem Двойной клик по этому файлу — и всё настроится.
setlocal
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel%==0 (
    python "%~dp0install.py"
    goto done
)

where py >nul 2>nul
if %errorlevel%==0 (
    py "%~dp0install.py"
    goto done
)

echo Python не найден. Установите Python 3 с https://www.python.org/ и повторите.

:done
echo.
pause
