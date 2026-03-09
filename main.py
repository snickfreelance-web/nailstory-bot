# ===================================================
# main.py — Точка входа в приложение
# ===================================================
# Здесь происходит:
#   1. Настройка логирования
#   2. Создание объекта Bot и Dispatcher
#   3. Регистрация всех роутеров (handlers)
#   4. Запуск polling (long polling = бот опрашивает Telegram)
#
# Для деплоя на VPS можно заменить polling на webhook —
# это описано в комментарии в конце файла.
# ===================================================

import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from bot.config import settings
from bot.handlers import common, user, admin


# ===================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ===================================================
# Логи показывают в консоли что происходит в боте.
# Уровень INFO — показываем информационные сообщения.
# В продакшене можно добавить запись в файл.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


# ===================================================
# ГЛАВНАЯ АСИНХРОННАЯ ФУНКЦИЯ
# ===================================================

async def main():
    """
    Основная функция запуска бота.
    Помечена как async потому что aiogram работает на asyncio —
    асинхронной библиотеке Python для конкурентного выполнения кода.

    Asyncio позволяет боту обрабатывать сотни пользователей
    одновременно в одном потоке, без создания отдельного потока
    для каждого пользователя.
    """

    logger.info("🚀 Запуск бота NailStory...")
    logger.info(f"Администраторы: {settings.get_admin_ids()}")

    # ---------------------------------------------------
    # Создаём объект бота
    # ---------------------------------------------------
    # Bot — это основной объект для отправки сообщений в Telegram.
    # DefaultBotProperties(parse_mode=ParseMode.HTML) — устанавливаем
    # HTML-форматирование по умолчанию для всех сообщений.
    # Это избавляет от необходимости указывать parse_mode=HTML каждый раз.
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # ---------------------------------------------------
    # Создаём диспетчер
    # ---------------------------------------------------
    # Dispatcher — маршрутизатор событий от Telegram.
    # Он принимает обновления (updates) и направляет их
    # нужным хэндлерам через зарегистрированные роутеры.
    #
    # MemoryStorage — хранит FSM-данные в оперативной памяти.
    # Плюсы: простота, скорость.
    # Минусы: при перезапуске бота данные теряются.
    # Для продакшена можно заменить на RedisStorage.
    dp = Dispatcher()

    # ---------------------------------------------------
    # Регистрируем роутеры в правильном порядке
    # ---------------------------------------------------
    # ВАЖНО: порядок регистрации роутеров имеет значение!
    # Хэндлеры проверяются по очереди — первый подходящий выигрывает.
    #
    # Порядок:
    #   1. admin — сначала проверяем admin-команды
    #   2. user  — затем клиентский флоу записи
    #   3. common — в конце общие хэндлеры (/start, catch-all)
    #
    # catch-all хэндлер в common.py должен быть последним,
    # иначе он поглотит все сообщения до их обработки.
    dp.include_router(admin.router)
    dp.include_router(user.router)
    dp.include_router(common.router)

    # ---------------------------------------------------
    # Удаляем webhook (на случай если был установлен ранее)
    # ---------------------------------------------------
    # При переключении между polling и webhook нужно явно
    # сбросить предыдущий режим.
    await bot.delete_webhook(drop_pending_updates=True)
    # drop_pending_updates=True — игнорируем накопившиеся
    # сообщения, пока бот был выключен

    logger.info("✅ Бот запущен и готов к работе!")

    # ---------------------------------------------------
    # Запускаем polling
    # ---------------------------------------------------
    # Polling = бот каждые несколько секунд спрашивает Telegram:
    # "Есть ли новые сообщения?" → получает список → обрабатывает.
    #
    # allowed_updates=dp.resolve_used_update_types() —
    # автоматически определяет какие типы обновлений нужны
    # исходя из зарегистрированных хэндлеров.
    # Это снижает лишний трафик.
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        # При остановке бота закрываем соединение с Telegram API
        await bot.session.close()
        logger.info("🛑 Бот остановлен")


# ===================================================
# ЗАПУСК
# ===================================================

if __name__ == "__main__":
    """
    Точка входа при запуске: python -m bot.main
    или: python main.py (из директории nailstory-bot/)

    asyncio.run() запускает event loop и выполняет main()
    до завершения (или до Ctrl+C).
    """
    asyncio.run(main())


# ===================================================
# КАК ПЕРЕЙТИ НА WEBHOOK (для VPS)
# ===================================================
# Webhook — Telegram сам отправляет обновления на ваш сервер.
# Преимущество: мгновенная реакция, меньше нагрузки.
# Требует: HTTPS-домен или IP, открытый порт.
#
# Замените start_polling на:
#
#   from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
#   from aiohttp import web
#
#   WEBHOOK_URL = "https://your-domain.com/bot"
#   WEBHOOK_PATH = "/bot"
#
#   async def on_startup(app):
#       await bot.set_webhook(WEBHOOK_URL)
#
#   app = web.Application()
#   SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
#   setup_application(app, dp, bot=bot)
#   app.on_startup.append(on_startup)
#   web.run_app(app, host="0.0.0.0", port=8080)
