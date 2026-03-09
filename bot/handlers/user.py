# ===================================================
# handlers/user.py — Клиентский флоу записи на маникюр
# ===================================================
# Полный цикл записи клиента:
#   1. Выбор услуги
#   2. Выбор даты в календаре
#   3. Выбор времени
#   4. Отправка номера телефона
#   5. Подтверждение и сохранение в БД
#
# FSM (Finite State Machine) следит за тем, на каком
# шаге находится каждый пользователь.
# ===================================================

import logging
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, Contact

from bot.states import BookingStates
from bot.keyboards import (
    get_services_keyboard,
    get_phone_keyboard,
    get_remove_keyboard,
    get_start_keyboard,
)
from bot.utils.calendar import (
    build_calendar,
    build_time_slots_keyboard,
    get_current_month_year,
)
from bot.utils.validators import (
    normalize_phone,
    is_valid_phone,
    format_date_ru,
    format_time_ru,
    format_status_ru,
)
from bot import database as db

logger = logging.getLogger(__name__)
router = Router()


# ===================================================
# ШАГ 1: НАЧАЛО ЗАПИСИ — ВЫБОР УСЛУГИ
# ===================================================

@router.callback_query(F.data == "start_booking")
async def handle_start_booking(callback: CallbackQuery, state: FSMContext):
    """
    Запускает процесс записи после нажатия кнопки "Записаться".
    Загружает список активных услуг из БД и показывает их как кнопки.

    Устанавливает состояние choosing_service — теперь бот
    ждёт нажатия на кнопку с услугой.
    """
    await callback.answer()

    # Загружаем только активные услуги (is_active = true)
    services = await db.get_all_services(active_only=True)

    if not services:
        await callback.message.edit_text(
            "😔 К сожалению, сейчас нет доступных услуг.\n"
            "Пожалуйста, свяжитесь с нами напрямую:\n"
            "📞 +7 (916) 123-45-67",
            reply_markup=get_start_keyboard(),
        )
        return

    # Переводим FSM в состояние выбора услуги
    await state.set_state(BookingStates.choosing_service)

    await callback.message.edit_text(
        text="💅 <b>Выберите услугу:</b>\n\n"
             "Нажмите на интересующую услугу для продолжения.",
        reply_markup=get_services_keyboard(services),
        parse_mode="HTML",
    )


@router.callback_query(BookingStates.choosing_service, F.data.startswith("service:"))
async def handle_service_selected(callback: CallbackQuery, state: FSMContext):
    """
    Обрабатывает выбор услуги.
    Сохраняет выбор в FSM-данные и переходит к календарю.

    F.data.startswith("service:") — фильтр callback_data.
    Срабатывает только на кнопки вида "service:uuid-here".

    BookingStates.choosing_service — фильтр состояния.
    Хэндлер активен только когда пользователь на шаге выбора услуги.
    """
    await callback.answer()

    # Извлекаем UUID услуги из callback_data
    # "service:550e8400-e29b-41d4-a716-446655440000" → берём всё после "service:"
    service_id = callback.data.split(":", 1)[1]

    # Загружаем данные об услуге из БД
    service = await db.get_service_by_id(service_id)

    if not service:
        await callback.answer("Услуга не найдена. Попробуйте ещё раз.", show_alert=True)
        return

    # Сохраняем выбор в FSM-данные
    # Эти данные живут пока пользователь в FSM-диалоге
    await state.update_data(
        service_id=service_id,
        service_name=service["name"],
        service_price=service["price"],
        service_duration=service["duration_min"],
    )

    # Переходим к следующему шагу — выбор даты
    await state.set_state(BookingStates.choosing_date)

    # Показываем календарь на текущий месяц
    year, month = get_current_month_year()
    available_dates = await db.get_available_dates(year, month)

    calendar_markup = build_calendar(year, month, available_dates)

    await callback.message.edit_text(
        text=(
            f"✅ Вы выбрали: <b>{service['name']}</b>\n"
            f"💰 Стоимость: {service['price']} ₽\n"
            f"⏱ Длительность: {service['duration_min']} мин\n\n"
            "📅 <b>Выберите удобную дату:</b>\n"
            "✅ — есть свободное время"
        ),
        reply_markup=calendar_markup,
        parse_mode="HTML",
    )


# ===================================================
# ШАГ 2: НАВИГАЦИЯ ПО КАЛЕНДАРЮ И ВЫБОР ДАТЫ
# ===================================================

@router.callback_query(BookingStates.choosing_date, F.data.startswith("cal_nav:"))
async def handle_calendar_navigation(callback: CallbackQuery, state: FSMContext):
    """
    Обрабатывает нажатия кнопок ◀ ▶ в календаре.
    Перерисовывает календарь на новый месяц.

    callback_data формат: "cal_nav:2024:4" (год:месяц куда переключить)
    """
    await callback.answer()

    # Парсим год и месяц из callback_data
    # "cal_nav:2024:4" → ["cal_nav", "2024", "4"]
    parts = callback.data.split(":")
    year = int(parts[1])
    month = int(parts[2])

    # Загружаем доступные даты для нового месяца
    available_dates = await db.get_available_dates(year, month)

    # Получаем данные FSM чтобы показать выбранную услугу
    fsm_data = await state.get_data()

    calendar_markup = build_calendar(year, month, available_dates)

    # Редактируем существующее сообщение (не отправляем новое)
    await callback.message.edit_text(
        text=(
            f"✅ Услуга: <b>{fsm_data.get('service_name')}</b>\n\n"
            "📅 <b>Выберите удобную дату:</b>\n"
            "✅ — есть свободное время"
        ),
        reply_markup=calendar_markup,
        parse_mode="HTML",
    )


@router.callback_query(BookingStates.choosing_date, F.data.startswith("cal_date:"))
async def handle_date_selected(callback: CallbackQuery, state: FSMContext):
    """
    Обрабатывает выбор конкретной даты в календаре.
    Загружает свободные временные слоты и показывает их как кнопки.

    callback_data формат: "cal_date:2024-03-15"
    """
    await callback.answer()

    # Извлекаем дату из callback_data
    selected_date = callback.data.split(":", 1)[1]  # "2024-03-15"

    # Загружаем доступные слоты для выбранной даты
    slots = await db.get_available_slots(selected_date)

    if not slots:
        # Слоты закончились пока пользователь смотрел календарь
        await callback.answer(
            "😔 К сожалению, на эту дату уже нет свободного времени.\n"
            "Пожалуйста, выберите другую дату.",
            show_alert=True,
        )
        return

    # Сохраняем выбранную дату в FSM
    await state.update_data(selected_date=selected_date)
    await state.set_state(BookingStates.choosing_time)

    # Форматируем дату для красивого отображения
    date_display = format_date_ru(selected_date)

    time_keyboard = build_time_slots_keyboard(slots)

    await callback.message.edit_text(
        text=(
            f"📅 Дата: <b>{date_display}</b>\n\n"
            "🕐 <b>Выберите удобное время:</b>"
        ),
        reply_markup=time_keyboard,
        parse_mode="HTML",
    )


# ===================================================
# ШАГ 3: ВЫБОР ВРЕМЕНИ
# ===================================================

@router.callback_query(BookingStates.choosing_time, F.data == "back_to_date")
async def handle_back_to_date(callback: CallbackQuery, state: FSMContext):
    """
    Возврат к выбору даты из экрана выбора времени.
    Перерисовывает календарь на текущий месяц.
    """
    await callback.answer()
    await state.set_state(BookingStates.choosing_date)

    fsm_data = await state.get_data()
    year, month = get_current_month_year()
    available_dates = await db.get_available_dates(year, month)
    calendar_markup = build_calendar(year, month, available_dates)

    await callback.message.edit_text(
        text=(
            f"✅ Услуга: <b>{fsm_data.get('service_name')}</b>\n\n"
            "📅 <b>Выберите удобную дату:</b>"
        ),
        reply_markup=calendar_markup,
        parse_mode="HTML",
    )


@router.callback_query(BookingStates.choosing_time, F.data.startswith("slot:"))
async def handle_time_selected(callback: CallbackQuery, state: FSMContext):
    """
    Обрабатывает выбор времени.
    Сохраняет слот в FSM и запрашивает номер телефона.

    callback_data формат: "slot:uuid:HH:MM"
    """
    await callback.answer()

    # Парсим callback_data
    # "slot:550e8400:10:00" → slot_id = "550e8400", time = "10:00"
    parts = callback.data.split(":")
    slot_id = parts[1]
    selected_time = f"{parts[2]}:{parts[3]}"  # Восстанавливаем "HH:MM"

    # Сохраняем слот в FSM
    await state.update_data(
        slot_id=slot_id,
        selected_time=selected_time,
    )

    # Переходим к запросу телефона
    await state.set_state(BookingStates.waiting_phone)

    fsm_data = await state.get_data()
    date_display = format_date_ru(fsm_data.get("selected_date", ""))

    # Показываем итоговую информацию перед подтверждением
    summary_text = (
        "📋 <b>Проверьте данные записи:</b>\n\n"
        f"💅 Услуга: <b>{fsm_data.get('service_name')}</b>\n"
        f"📅 Дата: <b>{date_display}</b>\n"
        f"🕐 Время: <b>{selected_time}</b>\n"
        f"💰 Стоимость: <b>{fsm_data.get('service_price')} ₽</b>\n\n"
        "📱 <b>Для подтверждения записи укажите номер телефона.</b>\n"
        "Нажмите кнопку ниже или введите номер вручную."
    )

    # Убираем Inline-клавиатуру и показываем Reply-кнопку телефона
    await callback.message.edit_text(
        text=summary_text,
        parse_mode="HTML",
    )

    # Отдельным сообщением отправляем Reply-клавиатуру с кнопкой телефона
    await callback.message.answer(
        text="👇 Нажмите кнопку для отправки номера:",
        reply_markup=get_phone_keyboard(),
    )


# ===================================================
# ШАГ 4: ПОЛУЧЕНИЕ НОМЕРА ТЕЛЕФОНА
# ===================================================

@router.message(BookingStates.waiting_phone, F.contact)
async def handle_phone_contact(message: Message, state: FSMContext):
    """
    Обрабатывает нажатие кнопки "Отправить мой номер".
    Telegram автоматически отправляет Contact-объект с верифицированным номером.

    F.contact — фильтр aiogram для сообщений с контактом.
    Этот способ предпочтительнее ручного ввода — номер гарантированно верный.
    """
    phone = normalize_phone(message.contact.phone_number)

    # Передаём обработку финальному хэндлеру
    await _complete_booking(message, state, phone)


@router.message(BookingStates.waiting_phone, F.text)
async def handle_phone_text(message: Message, state: FSMContext):
    """
    Обрабатывает ручной ввод номера телефона.
    Вызывается когда пользователь нажал "Ввести вручную"
    и напечатал номер текстом.

    Валидируем введённый номер перед сохранением.
    """
    phone_text = message.text.strip()

    if not is_valid_phone(phone_text):
        # Номер некорректный — просим ввести заново
        await message.answer(
            "❌ Некорректный номер телефона.\n\n"
            "Пожалуйста, введите номер в формате:\n"
            "<code>+7 916 123-45-67</code>\n"
            "<code>8 916 123-45-67</code>",
            parse_mode="HTML",
        )
        return

    phone = normalize_phone(phone_text)
    await _complete_booking(message, state, phone)


async def _complete_booking(message: Message, state: FSMContext, phone: str):
    """
    Финальный шаг: создаёт бронирование в БД.
    Вызывается как из handle_phone_contact(), так и из handle_phone_text().

    Вынесено в отдельную функцию чтобы не дублировать код
    (принцип DRY — Don't Repeat Yourself).

    Args:
        message: Объект сообщения Telegram
        state: FSM-контекст с данными записи
        phone: Нормализованный номер телефона
    """
    # Извлекаем все сохранённые данные из FSM
    fsm_data = await state.get_data()

    user = message.from_user
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()

    # Создаём бронирование в БД
    # database.create_booking() также блокирует выбранный слот
    booking = await db.create_booking(
        user_id=user.id,
        username=user.username,
        full_name=full_name or "Не указано",
        phone=phone,
        service_id=fsm_data["service_id"],
        slot_id=fsm_data["slot_id"],
        booking_date=fsm_data["selected_date"],
        booking_time=fsm_data["selected_time"] + ":00",  # Добавляем секунды
    )

    # Убираем Reply-клавиатуру с кнопкой телефона
    if booking:
        # Успешное создание бронирования
        date_display = format_date_ru(fsm_data["selected_date"])

        success_text = (
            "🎉 <b>Запись создана!</b>\n\n"
            f"💅 Услуга: <b>{fsm_data['service_name']}</b>\n"
            f"📅 Дата: <b>{date_display}</b>\n"
            f"🕐 Время: <b>{fsm_data['selected_time']}</b>\n"
            f"📱 Телефон: <b>{phone}</b>\n\n"
            "✅ Ваша заявка принята!\n"
            "Наш администратор позвонит вам в ближайшее время "
            "для подтверждения визита.\n\n"
            "До встречи в NailStory! 💅🌸"
        )

        await message.answer(
            text=success_text,
            reply_markup=get_remove_keyboard(),  # Убираем клавиатуру телефона
            parse_mode="HTML",
        )

        logger.info(
            f"Создано бронирование: пользователь={user.id}, "
            f"услуга={fsm_data['service_name']}, "
            f"дата={fsm_data['selected_date']}, "
            f"время={fsm_data['selected_time']}"
        )

    else:
        # Ошибка создания бронирования
        await message.answer(
            "😔 Произошла ошибка при создании записи.\n"
            "Пожалуйста, попробуйте ещё раз или свяжитесь с нами:\n"
            "📞 +7 (916) 123-45-67",
            reply_markup=get_remove_keyboard(),
        )

    # Сбрасываем FSM — диалог завершён
    await state.clear()

    # Показываем главное меню для новой записи
    await message.answer(
        "Чтобы записаться ещё раз, нажмите /start",
        reply_markup=get_start_keyboard(),
    )


# ===================================================
# ВОЗВРАТ К ВЫБОРУ УСЛУГИ
# ===================================================

@router.callback_query(F.data == "back_to_service")
async def handle_back_to_service(callback: CallbackQuery, state: FSMContext):
    """
    Возврат к выбору услуги (нажатие кнопки "Изменить").
    Сбрасываем состояние к первому шагу.
    """
    await callback.answer()
    await state.set_state(BookingStates.choosing_service)

    services = await db.get_all_services(active_only=True)

    if not services:
        await callback.message.edit_text(
            "Сейчас нет доступных услуг. Попробуйте позже.",
            reply_markup=get_start_keyboard(),
        )
        return

    await callback.message.edit_text(
        text="💅 <b>Выберите услугу:</b>",
        reply_markup=get_services_keyboard(services),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "cancel_booking")
async def handle_cancel_booking(callback: CallbackQuery, state: FSMContext):
    """
    Отменяет текущую запись через inline-кнопку.
    Возвращает на главный экран.
    """
    await callback.answer("Запись отменена")
    await state.clear()

    await callback.message.edit_text(
        text="❌ Запись отменена.\n\nВозвращайтесь когда будете готовы! 💅",
        reply_markup=get_start_keyboard(),
    )
