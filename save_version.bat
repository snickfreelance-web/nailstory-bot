@echo off
chcp 65001 >nul
echo ====================================================
echo  Сохранение стабильной версии
echo ====================================================

:: Определяем текущую ветку
for /f "tokens=*" %%i in ('git rev-parse --abbrev-ref HEAD') do set BRANCH=%%i

:: Если на feature-ветке — мёрджим в main
if not "%BRANCH%"=="main" (
    echo.
    echo Текущая ветка: %BRANCH%
    echo Сливаем в main...
    git checkout main
    git merge feature/%BRANCH:feature/=% --no-ff -m "feat: merge %BRANCH%"
    if errorlevel 1 (
        echo.
        echo ОШИБКА при слиянии! Реши конфликты вручную, затем запусти скрипт снова.
        pause
        exit /b 1
    )
    git branch -d %BRANCH%
    echo Ветка %BRANCH% удалена.
)

:: Пушим main на GitHub
echo.
echo Пушим main на GitHub...
git push origin main

:: Показываем ВСЕ существующие теги с датой и описанием
echo.
echo ====================================================
echo  Все сохранённые версии:
echo ====================================================
git log --tags --simplify-by-decoration --pretty="format:  %%d   %%s   (%%as)" | findstr /i "tag:"
echo.
echo ====================================================
echo.

:: Запрашиваем номер версии
set /p VERSION=Номер новой версии (напр. 1.1):
if "%VERSION%"=="" (
    echo Версия не указана. Отмена.
    pause
    exit /b 1
)

:: Проверяем что тег не существует
git tag | findstr /x "v%VERSION%" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo ОШИБКА: тег v%VERSION% уже существует! Выбери другой номер.
    pause
    exit /b 1
)

echo.
set /p COMMENT=Краткое описание (что добавлено/исправлено):
if "%COMMENT%"=="" set COMMENT=stable version v%VERSION%

:: Создаём аннотированный тег и пушим
git tag -a v%VERSION% -m "%COMMENT%"
git push origin v%VERSION%

echo.
echo ====================================================
echo  ГОТОВО!
echo  Версия v%VERSION% сохранена: %COMMENT%
echo.
echo  GitHub Releases:
echo  https://github.com/snickfreelance-web/nailstory-bot/releases/tag/v%VERSION%
echo ====================================================
pause
