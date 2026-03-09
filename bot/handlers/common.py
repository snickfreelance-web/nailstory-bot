# ===================================================
# handlers/common.py — Общие хэндлеры и middleware
# ===================================================
# Содержит:
#   - Middleware проверки прав администратора
#   - Хэндлер команды /start
#   - Хэндлер /cancel (отмена текущего диалога)
#   - Хэндлер показа контактов
#   - Хэндлер неизвестных сообщений (catch-all)
# ===================================================

import logging
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import settings
from bot.keyboards import get_start_keyboard

logger = logging.getLogger(__name__)

# Router — это мини-приложение внутри aiogram.
# Каждый файл handlers/ имеет свой Router.
# В main.py все роутеры подключаются к главному диспетчеру.
router = Router()


# ===================================================
# ТЕКСТ ПРИВЕТСТВЕННОГО СООБЩЕНИЯ
# ===================================================

WELCOME_TEXT = """
💅 Добро пожаловать в <b>NailStory</b>!

Мы — студия маникюра и педикюра в самом центре города.
Работаем с любовью к каждому ногтю с 2018 года 🌸

✨ <b>Почему выбирают нас:</b>
• Только сертифицированные мастера
• Безопасные материалы премиум-класса
• Стерильные инструменты для каждого клиента
• Уютная атмосфера и бесплатный чай/кофе

🕐 <b>Режим работы:</b> Пн–Сб 10:00–20:00

Готовы записать вас на идеальный маникюр! 👇
"""


# ===================================================
# ХЭНДЛЕРЫ
# ===================================================

@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext):
    """
    Обрабатывает команду /start.
    Это первое, что видит пользователь при открытии бота.

    Действия:
    1. Сбрасываем любое предыдущее состояние FSM
       (на случай если пользователь был в середине записи)
    2. Отправляем приветственное сообщение с кнопками

    Args:
        message: Объект сообщения от Telegram
        state: FSM-контекст для управления состояниями
    """
    # Сбрасываем состояние — начинаем чистый диалог
    await state.clear()

    logger.info(f"Пользователь {message.from_user.id} ({message.from_user.username}) запустил бота")

    await message.answer(
        text=WELCOME_TEXT,
        reply_markup=get_start_keyboard(),
        parse_mode="HTML",  # Включаем HTML-форматирование для <b>жирного</b>
    )


@router.message(Command("cancel"))
@router.message(F.text.lower() == "отмена")
async def handle_cancel(message: Message, state: FSMContext):
    """
    Обрабатывает команду /cancel и текст "отмена".
    Позволяет пользователю прервать текущий диалог в любой момент.

    F.text.lower() == "отмена" — фильтр aiogram для текстовых сообщений.
    Декораторы можно комбинировать: хэндлер срабатывает на оба варианта.
    """
    current_state = await state.get_state()

    if current_state is None:
        # Пользователь не в активном диалоге
        await message.answer(
            "Нет активного действия для отмены.\n"
            "Нажмите /start чтобы начать запись 💅"
        )
        return

    # Очищаем FSM-данные (выбранная услуга, дата и т.д.)
    await state.clear()

    await message.answer(
        "❌ Запись отменена.\n"
        "Нажмите /start чтобы начать заново.",
        reply_markup=get_start_keyboard(),
    )


@router.callback_query(F.data == "back_to_main")
async def handle_back_to_main(callback: CallbackQuery, state: FSMContext):
    """
    Обрабатывает нажатие кнопки "Назад" в главное меню.
    Callback — это нажатие на Inline-кнопку.

    Нужно обязательно вызвать callback.answer() —
    это убирает "часики" на кнопке в Telegram.
    """
    await state.clear()
    await callback.answer()  # Подтверждаем обработку callback

    await callback.message.edit_text(
        text=WELCOME_TEXT,
        reply_markup=get_start_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "show_contacts")
async def handle_show_contacts(callback: CallbackQuery):
    """
    Показывает контактную информацию студии.
    Данные жёстко заданы в тексте — в продакшене
    можно вынести в конфиг или таблицу БД.
    """
    await callback.answer()

    contacts_text = (
        "📞 <b>Контакты NailStory</b>\n\n"
        "📍 Адрес: ул. Цветочная, 15\n"
        "📱 Телефон: +7 (916) 123-45-67\n"
        "📲 WhatsApp: +7 (916) 123-45-67\n"
        "🌐 Instagram: @nailstory_official\n\n"
        "🕐 Работаем: Пн–Сб 10:00–20:00\n"
        "🚇 Метро: 5 минут пешком от ст. Парк культуры"
    )

    # Строим клавиатуру с кнопкой возврата
    builder = InlineKeyboardBuilder()
    builder.button(text="◀ Назад", callback_data="back_to_main")

    await callback.message.edit_text(
        text=contacts_text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.in_({"cal_ignore", "ignore"}))
async def handle_ignore_callback(callback: CallbackQuery):
    """
    "Поглощает" нажатия на декоративные кнопки.
    Без этого хэндлера Telegram будет показывать бесконечные
    "часики" на кнопках-заглушках (заголовки календаря, дни недели и т.д.)

    callback.answer() без текста — тихое подтверждение,
    никакого попапа пользователь не видит.
    """
    await callback.answer()


@router.message()
async def handle_unknown(message: Message, state: FSMContext):
    """
    Catch-all хэндлер — срабатывает на любое сообщение,
    которое не обработал ни один другой хэндлер.

    ⚠️ Этот хэндлер должен быть ПОСЛЕДНИМ в списке роутеров
    в main.py, иначе он будет перехватывать все сообщения.

    Проверяем состояние FSM:
    - Если пользователь в диалоге записи → подсказываем что делать
    - Если не в диалоге → предлагаем начать запись
    """
    current_state = await state.get_state()

    if current_state:
        await message.answer(
            "👆 Пожалуйста, используйте кнопки для навигации.\n"
            "Или нажмите /cancel для отмены текущего действия."
        )
    else:
        await message.answer(
            "Нажмите /start чтобы записаться на маникюр 💅"
        )
