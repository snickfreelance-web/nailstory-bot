@echo off
chcp 65001 >nul
echo ====================================================
echo  Создание новой feature-ветки
echo ====================================================
echo.
echo Текущие ветки:
git branch -a
echo.
set /p FEATURE_NAME=Название фичи (латиницей через дефис, напр. add-notifications):
if "%FEATURE_NAME%"=="" (
    echo Имя не может быть пустым.
    pause
    exit /b 1
)

echo.
echo Переключаемся на main и обновляемся...
git checkout main
git pull origin main

echo.
echo Создаём ветку feature/%FEATURE_NAME%...
git checkout -b feature/%FEATURE_NAME%

echo.
echo ====================================================
echo  Ветка feature/%FEATURE_NAME% создана!
echo.
echo  Разрабатывай фичу и тестируй бота.
echo  Когда всё готово — запусти save_version.bat
echo  чтобы слить изменения в main и сохранить версию.
echo ====================================================
pause
