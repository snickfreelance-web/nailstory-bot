@echo off
chcp 65001 >nul
title NailStory Bot

cd /d "%~dp0"

:: Проверяем: работает ли pydantic_core в текущем venv
if exist "venv" (
    venv\Scripts\python.exe -c "import pydantic_core" 2>nul
    if errorlevel 1 (
        echo [1/4] Несовместимые пакеты найдены. Пересоздаём окружение...
        rmdir /s /q venv
    )
)

:: Создаём venv если не существует
if not exist "venv\Scripts\activate.bat" (
    echo [1/4] Создаём виртуальное окружение...
    python -m venv venv
)

:: Активируем venv
call venv\Scripts\activate.bat

:: Обновляем pip и устанавливаем зависимости
echo [2/4] Обновляем pip...
python -m pip install --upgrade pip -q

echo [3/4] Устанавливаем зависимости...
pip install -r requirements.txt -q

:: Запускаем бота
echo [4/4] Запускаем бота...
echo.
python main.py

echo.
echo Бот остановлен. Нажмите любую клавишу для закрытия.
pause >nul
