# ===================================================
# handlers/admin.py — Полная административная панель
# ===================================================
# Все хэндлеры для администраторов бота.
# Доступ только для пользователей из ADMIN_IDS.
#
# Разделы:
#   1. Middleware проверки прав
#   2. Главное меню /admin
#   3. Управление услугами (CRUD)
#   4. Просмотр бронирований (с фильтрами и пагинацией)
#   5. Действия с бронированиями (подтвердить/перенести/отменить/удалить)
#   6. Управление расписанием (слоты)
#   7. Статистика
# ===================================================

import logging
from datetime import date
from aiogram import Router, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, TelegramObject
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import Callable, Dict, Any, Awaitable

from bot.config import settings
from bot.states import AdminServiceStates, AdminSlotStates, AdminRescheduleStates
from bot.keyboards import (
    get_admin_main_keyboard,
    get_admin_services_keyboard,
    get_admin_service_detail_keyboard,
    get_admin_duration_keyboard,
    get_admin_bookings_filter_keyboard,
    get_admin_booking_actions_keyboard,
    get_admin_pagination_keyboard,
    get_admin_schedule_keyboard,
    get_admin_time_slots_keyboard,
    get_admin_slots_list_keyboard,
    get_delete_confirm_keyboard,
)
from bot.utils.validators import (
    format_date_ru,
    format_time_ru,
    format_status_ru,
    is_valid_price,
    parse_date,
)
from bot import database as db

logger = logging.getLogger(__name__)

# Количество бронирований на одной странице (пагинация)
BOOKINGS_PER_PAGE = 8


# ===================================================
# MIDDLEWARE: ПРОВЕРКА ПРАВ АДМИНИСТРАТОРА
# ===================================================

class AdminMiddleware(BaseMiddleware):
    """
    Middleware — промежуточный слой обработки запросов.
    Вызывается ПЕРЕД каждым хэндлером в этом роутере.

    Проверяет, является ли пользователь администратором.
    Если нет — отправляет сообщение об отказе и прерывает обработку.

    Преимущество middleware перед отдельной проверкой в каждом хэндлере:
    — DRY: не нужно повторять проверку в каждой функции
    — Безопасность: невозможно случайно забыть добавить проверку
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        """
        Метод вызывается для каждого события (сообщение или callback).

        Args:
            handler: Следующий хэндлер в цепочке (или следующий middleware)
            event: Событие от Telegram (Message или CallbackQuery)
            data: Словарь с дополнительными данными (FSM, бот и т.д.)
        """
        # Определяем ID пользователя независимо от типа события
        user_id = None

        if hasattr(event, "from_user") and event.from_user:
            user_id = event.from_user.id
        elif hasattr(event, "message") and event.message:
            user_id = event.message.from_user.id

        admin_ids = settings.get_admin_ids()

        if user_id not in admin_ids:
            # Пользователь не является администратором
            if hasattr(event, "answer"):
                await event.answer("⛔ У вас нет доступа к этой команде.")
            elif hasattr(event, "message"):
                await event.message.answer("⛔ У вас нет доступа.")
                await event.answer()
            return  # Прерываем обработку — хэндлер не вызывается

        # Пользователь — администратор, продолжаем обработку
        return await handler(event, data)


# Создаём роутер и добавляем middleware
router = Router()
router.message.middleware(AdminMiddleware())
router.callback_query.middleware(AdminMiddleware())


# ===================================================
# ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: ФОРМАТИРОВАНИЕ БРОНИРОВАНИЯ
# ===================================================

def format_booking_card(booking: Dict) -> str:
    """
    Форматирует данные бронирования в читаемую карточку.
    Используется в списке и детальном просмотре.

    Args:
        booking: Словарь с данными бронирования (включая services)

    Returns:
        Отформатированная строка для отправки в Telegram
    """
    service_name = booking.get("services", {}).get("name", "Неизвестно")
    service_price = booking.get("services", {}).get("price", "—")
    date_display = format_date_ru(booking["booking_date"])
    time_display = format_time_ru(booking["booking_time"])
    status_display = format_status_ru(booking["status"])

    return (
        f"👤 <b>{booking['full_name']}</b>\n"
        f"📱 {booking['phone']}\n"
        f"{'@' + booking['username'] if booking.get('username') else ''}\n"
        f"💅 {service_name} — {service_price} ₽\n"
        f"📅 {date_display}, 🕐 {time_display}\n"
        f"Статус: {status_display}\n"
        f"🆔 <code>{booking['id'][:8]}...</code>"
    )


# ===================================================
# 1. ГЛАВНОЕ МЕНЮ АДМИНИСТРАТОРА
# ===================================================

@router.message(Command("admin"))
async def handle_admin_command(message: Message, state: FSMContext):
    """
    Точка входа в админ-панель.
    Доступна по команде /admin.
    Middleware уже проверил права — если мы здесь, пользователь — администратор.
    """
    await state.clear()  # Сбрасываем любые активные состояния

    logger.info(f"Администратор {message.from_user.id} открыл панель")

    await message.answer(
        text=(
            "🔧 <b>Панель администратора NailStory</b>\n\n"
            "Выберите раздел для управления:"
        ),
        reply_markup=get_admin_main_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:main")
async def handle_admin_main_menu(callback: CallbackQuery, state: FSMContext):
    """
    Возврат в главное меню админки из любого подраздела.
    """
    await callback.answer()
    await state.clear()

    await callback.message.edit_text(
        text="🔧 <b>Панель администратора</b>\n\nВыберите раздел:",
        reply_markup=get_admin_main_keyboard(),
        parse_mode="HTML",
    )


# ===================================================
# 2. СТАТИСТИКА
# ===================================================

@router.callback_query(F.data == "admin:stats")
async def handle_admin_stats(callback: CallbackQuery):
    """
    Показывает сводную статистику по бронированиям.
    """
    await callback.answer()

    # Загружаем счётчики параллельно
    total = await db.get_bookings_count()
    pending = await db.get_bookings_count("pending")
    confirmed = await db.get_bookings_count("confirmed")
    cancelled = await db.get_bookings_count("cancelled")

    # Загружаем записи на сегодня
    today_str = date.today().strftime("%Y-%m-%d")
    today_bookings = await db.get_upcoming_bookings_for_date(today_str)

    builder = InlineKeyboardBuilder()
    builder.button(text="◀ Главное меню", callback_data="admin:main")

    await callback.message.edit_text(
        text=(
            "📊 <b>Статистика NailStory</b>\n\n"
            f"📋 Всего бронирований: <b>{total}</b>\n"
            f"⏳ Ожидают подтверждения: <b>{pending}</b>\n"
            f"✅ Подтверждены: <b>{confirmed}</b>\n"
            f"❌ Отменены: <b>{cancelled}</b>\n\n"
            f"📅 Записей на сегодня: <b>{len(today_bookings)}</b>"
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


# ===================================================
# 3. УПРАВЛЕНИЕ УСЛУГАМИ
# ===================================================

@router.callback_query(F.data == "admin:services")
async def handle_admin_services(callback: CallbackQuery, state: FSMContext):
    """
    Открывает раздел управления услугами.
    Загружает ВСЕ услуги (включая скрытые от клиентов).
    """
    await callback.answer()
    await state.clear()

    # active_only=False — показываем все услуги в админке
    services = await db.get_all_services(active_only=False)

    if not services:
        text = "💅 <b>Управление услугами</b>\n\nУслуг пока нет. Добавьте первую!"
    else:
        text = (
            "💅 <b>Управление услугами</b>\n\n"
            "✅ — активна (видна клиентам)\n"
            "🔴 — скрыта (не видна клиентам)\n\n"
            "Нажмите на услугу для управления:"
        )

    await callback.message.edit_text(
        text=text,
        reply_markup=get_admin_services_keyboard(services),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_svc:"))
async def handle_admin_service_action(callback: CallbackQuery, state: FSMContext):
    """
    Обрабатывает нажатие на конкретную услугу в списке.
    Показывает детальную карточку услуги с кнопками управления.

    callback_data:
        "admin_svc:uuid"  — просмотр конкретной услуги
        "admin_svc:add"   — начало добавления новой услуги
    """
    await callback.answer()

    action = callback.data.split(":", 1)[1]

    if action == "add":
        # Начинаем добавление новой услуги
        await state.set_state(AdminServiceStates.waiting_name)

        builder = InlineKeyboardBuilder()
        builder.button(text="❌ Отмена", callback_data="admin:services")

        await callback.message.edit_text(
            text=(
                "➕ <b>Добавление новой услуги</b>\n\n"
                "Шаг 1/3: Введите <b>название</b> услуги:\n\n"
                "<i>Пример: Маникюр классический</i>"
            ),
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
    else:
        # Просматриваем конкретную услугу
        service_id = action
        service = await db.get_service_by_id(service_id)

        if not service:
            await callback.answer("Услуга не найдена", show_alert=True)
            return

        status_text = "✅ Активна (видна клиентам)" if service["is_active"] else "🔴 Скрыта от клиентов"

        await callback.message.edit_text(
            text=(
                f"💅 <b>{service['name']}</b>\n\n"
                f"💰 Цена: {service['price']} ₽\n"
                f"⏱ Длительность: {service['duration_min']} мин\n"
                f"Статус: {status_text}\n"
                f"🆔 <code>{service['id']}</code>"
            ),
            reply_markup=get_admin_service_detail_keyboard(service_id, service["is_active"]),
            parse_mode="HTML",
        )


@router.message(AdminServiceStates.waiting_name)
async def handle_admin_service_name(message: Message, state: FSMContext):
    """
    Получает название новой услуги от администратора.
    Шаг 1 из 3 при добавлении услуги.
    """
    name = message.text.strip()

    if len(name) < 3:
        await message.answer("❌ Название слишком короткое. Введите минимум 3 символа.")
        return

    if len(name) > 100:
        await message.answer("❌ Название слишком длинное. Максимум 100 символов.")
        return

    # Сохраняем название в FSM
    await state.update_data(service_name=name)

    # Переходим к выбору длительности
    await state.set_state(AdminServiceStates.waiting_duration)

    await message.answer(
        text=(
            f"✅ Название: <b>{name}</b>\n\n"
            "Шаг 2/3: Выберите <b>длительность</b> услуги:"
        ),
        reply_markup=get_admin_duration_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(AdminServiceStates.waiting_duration, F.data.startswith("duration:"))
async def handle_admin_service_duration(callback: CallbackQuery, state: FSMContext):
    """
    Получает длительность услуги через кнопку.
    Шаг 2 из 3. Используем кнопки вместо ввода числа — удобнее и безопаснее.
    """
    await callback.answer()

    duration = int(callback.data.split(":")[1])
    await state.update_data(service_duration=duration)

    # Переходим к вводу цены
    await state.set_state(AdminServiceStates.waiting_price)

    fsm_data = await state.get_data()

    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="admin:services")

    await callback.message.edit_text(
        text=(
            f"✅ Название: <b>{fsm_data['service_name']}</b>\n"
            f"✅ Длительность: <b>{duration} мин</b>\n\n"
            "Шаг 3/3: Введите <b>цену</b> услуги в рублях:\n\n"
            "<i>Только цифры, например: 1500</i>"
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.message(AdminServiceStates.waiting_price)
async def handle_admin_service_price(message: Message, state: FSMContext):
    """
    Получает цену услуги и создаёт услугу в БД.
    Финальный шаг (3 из 3) добавления услуги.
    """
    price_str = message.text.strip()

    if not is_valid_price(price_str):
        await message.answer(
            "❌ Некорректная цена.\n"
            "Введите целое положительное число, например: <code>1500</code>",
            parse_mode="HTML",
        )
        return

    price = int(price_str)
    fsm_data = await state.get_data()

    # Создаём услугу в БД
    service = await db.add_service(
        name=fsm_data["service_name"],
        duration_min=fsm_data["service_duration"],
        price=price,
    )

    await state.clear()

    if service:
        builder = InlineKeyboardBuilder()
        builder.button(text="💅 К списку услуг", callback_data="admin:services")
        builder.button(text="➕ Добавить ещё", callback_data="admin_svc:add")
        builder.adjust(1)

        await message.answer(
            text=(
                "✅ <b>Услуга успешно добавлена!</b>\n\n"
                f"💅 {fsm_data['service_name']}\n"
                f"⏱ {fsm_data['service_duration']} мин\n"
                f"💰 {price} ₽"
            ),
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
    else:
        await message.answer("❌ Ошибка при добавлении услуги. Попробуйте ещё раз.")


@router.callback_query(F.data.startswith("admin_svc_hide:"))
async def handle_admin_service_hide(callback: CallbackQuery):
    """Скрывает услугу от клиентов (is_active = false)."""
    await callback.answer()
    service_id = callback.data.split(":", 1)[1]

    success = await db.toggle_service_status(service_id, False)

    if success:
        await callback.answer("🔴 Услуга скрыта от клиентов", show_alert=True)
    else:
        await callback.answer("❌ Ошибка. Попробуйте ещё раз.", show_alert=True)

    # Обновляем список услуг
    services = await db.get_all_services(active_only=False)
    await callback.message.edit_reply_markup(
        reply_markup=get_admin_services_keyboard(services)
    )


@router.callback_query(F.data.startswith("admin_svc_show:"))
async def handle_admin_service_show(callback: CallbackQuery):
    """Делает услугу видимой для клиентов (is_active = true)."""
    await callback.answer()
    service_id = callback.data.split(":", 1)[1]

    success = await db.toggle_service_status(service_id, True)

    if success:
        await callback.answer("✅ Услуга снова доступна клиентам", show_alert=True)
    else:
        await callback.answer("❌ Ошибка. Попробуйте ещё раз.", show_alert=True)

    services = await db.get_all_services(active_only=False)
    await callback.message.edit_reply_markup(
        reply_markup=get_admin_services_keyboard(services)
    )


@router.callback_query(F.data.startswith("admin_svc_del:"))
async def handle_admin_service_delete(callback: CallbackQuery):
    """
    Удаляет услугу из БД.
    Если у услуги есть бронирования — предлагает скрыть вместо удаления.
    """
    await callback.answer()
    service_id = callback.data.split(":", 1)[1]

    # Проверяем наличие бронирований
    has_bookings = await db.service_has_bookings(service_id)

    if has_bookings:
        # Нельзя удалить — есть история бронирований
        builder = InlineKeyboardBuilder()
        builder.button(text="🔴 Скрыть вместо удаления", callback_data=f"admin_svc_hide:{service_id}")
        builder.button(text="◀ Назад", callback_data=f"admin_svc:{service_id}")
        builder.adjust(1)

        await callback.message.edit_text(
            text=(
                "⚠️ <b>Невозможно удалить услугу</b>\n\n"
                "У этой услуги есть история бронирований.\n"
                "Удаление нарушит целостность данных.\n\n"
                "Вы можете <b>скрыть</b> услугу — она не будет видна клиентам, "
                "но история записей сохранится."
            ),
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        return

    # Можно удалить — бронирований нет
    success = await db.delete_service(service_id)

    if success:
        await callback.answer("🗑 Услуга удалена", show_alert=True)
        services = await db.get_all_services(active_only=False)

        await callback.message.edit_text(
            text=(
                "💅 <b>Управление услугами</b>\n\n"
                "Нажмите на услугу для управления:"
            ),
            reply_markup=get_admin_services_keyboard(services),
            parse_mode="HTML",
        )
    else:
        await callback.answer("❌ Ошибка удаления. Попробуйте ещё раз.", show_alert=True)


# ===================================================
# 4. ПРОСМОТР БРОНИРОВАНИЙ
# ===================================================

@router.callback_query(F.data == "admin:bookings")
async def handle_admin_bookings(callback: CallbackQuery, state: FSMContext):
    """
    Открывает раздел просмотра бронирований.
    Показывает клавиатуру фильтрации.
    """
    await callback.answer()
    await state.clear()

    await callback.message.edit_text(
        text=(
            "📋 <b>Бронирования</b>\n\n"
            "Выберите фильтр для отображения записей:"
        ),
        reply_markup=get_admin_bookings_filter_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_bk_filter:"))
async def handle_admin_bookings_filter(callback: CallbackQuery, state: FSMContext):
    """
    Применяет выбранный фильтр и показывает список бронирований.

    callback_data: "admin_bk_filter:all|pending|confirmed|cancelled|date"
    """
    await callback.answer()

    filter_type = callback.data.split(":", 1)[1]

    if filter_type == "date":
        # Запрашиваем дату у администратора текстом
        await state.set_state(AdminSlotStates.waiting_date)
        await state.update_data(filter_context="bookings")  # Помним зачем просим дату

        builder = InlineKeyboardBuilder()
        builder.button(text="❌ Отмена", callback_data="admin:bookings")

        await callback.message.edit_text(
            text=(
                "📅 Введите дату для просмотра бронирований:\n\n"
                "<i>Формат: ДД.ММ.ГГГГ (например, 15.03.2024)</i>"
            ),
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        return

    # Загружаем бронирования с пагинацией
    status = None if filter_type == "all" else filter_type
    await _show_bookings_page(callback.message, page=0, filter_type=filter_type, status=status, edit=True)


async def _show_bookings_page(
    message,
    page: int,
    filter_type: str,
    status: str = None,
    date_filter: str = None,
    edit: bool = False
):
    """
    Вспомогательная функция отображения страницы бронирований.
    Вынесена отдельно чтобы переиспользовать в нескольких хэндлерах.

    Args:
        message: Объект сообщения для редактирования/отправки
        page: Номер страницы (0-based)
        filter_type: Тип фильтра для передачи в кнопки пагинации
        status: SQL-фильтр по статусу
        date_filter: SQL-фильтр по дате
        edit: True = редактируем существующее, False = новое сообщение
    """
    offset = page * BOOKINGS_PER_PAGE
    bookings = await db.get_all_bookings(
        status_filter=status,
        date_filter=date_filter,
        limit=BOOKINGS_PER_PAGE,
        offset=offset,
    )

    total = await db.get_bookings_count(status_filter=status)
    total_pages = max(1, (total + BOOKINGS_PER_PAGE - 1) // BOOKINGS_PER_PAGE)

    if not bookings:
        builder = InlineKeyboardBuilder()
        builder.button(text="🔍 Изменить фильтр", callback_data="admin:bookings")
        builder.button(text="◀ Меню", callback_data="admin:main")
        builder.adjust(1)

        text = "📋 <b>Бронирования не найдены</b>\n\nПо данному фильтру записей нет."

        if edit:
            await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
        else:
            await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
        return

    # Строим список бронирований
    lines = [f"📋 <b>Бронирования</b> (стр. {page + 1}/{total_pages}, всего: {total})\n"]

    builder = InlineKeyboardBuilder()

    for i, booking in enumerate(bookings, start=1):
        service_name = booking.get("services", {}).get("name", "?")
        time_str = format_time_ru(booking["booking_time"])
        date_str = format_date_ru(booking["booking_date"])
        status_icon = {"pending": "⏳", "confirmed": "✅", "cancelled": "❌"}.get(booking["status"], "?")

        # Краткая строка для списка
        lines.append(
            f"{i}. {status_icon} {booking['full_name']}\n"
            f"   {service_name} | {date_str} {time_str}"
        )

        # Кнопка для открытия детальной карточки
        builder.button(
            text=f"{i}. {booking['full_name'][:20]}",
            callback_data=f"admin_bk_view:{booking['id']}"
        )

    text = "\n".join(lines)

    # Добавляем пагинацию
    builder.adjust(2)  # Кнопки бронирований по 2 в ряд
    pagination_kb = get_admin_pagination_keyboard(page, total_pages, filter_type)

    # Объединяем: список + пагинация
    for btn_row in pagination_kb.inline_keyboard:
        builder.row(*btn_row)

    if edit:
        await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("admin_bk_page:"))
async def handle_admin_bookings_page(callback: CallbackQuery):
    """
    Навигация по страницам списка бронирований.
    callback_data: "admin_bk_page:2:pending" (страница:фильтр)
    """
    await callback.answer()

    parts = callback.data.split(":")
    page = int(parts[1])
    filter_type = parts[2] if len(parts) > 2 else "all"

    status = None if filter_type == "all" else filter_type

    await _show_bookings_page(
        callback.message,
        page=page,
        filter_type=filter_type,
        status=status,
        edit=True,
    )


@router.callback_query(F.data.startswith("admin_bk_list:"))
async def handle_admin_back_to_list(callback: CallbackQuery):
    """Возврат к списку бронирований с сохранением страницы."""
    await callback.answer()

    page = int(callback.data.split(":")[1])
    await _show_bookings_page(callback.message, page=page, filter_type="all", edit=True)


# ===================================================
# 5. ДЕТАЛЬНЫЙ ПРОСМОТР И ДЕЙСТВИЯ С БРОНИРОВАНИЕМ
# ===================================================

@router.callback_query(F.data.startswith("admin_bk_view:"))
async def handle_admin_booking_view(callback: CallbackQuery, state: FSMContext):
    """
    Показывает детальную карточку бронирования.
    Открывается при нажатии на строку в списке.
    """
    await callback.answer()

    booking_id = callback.data.split(":", 1)[1]
    booking = await db.get_booking_by_id(booking_id)

    if not booking:
        await callback.answer("Бронирование не найдено", show_alert=True)
        return

    text = (
        "📋 <b>Детали бронирования</b>\n\n"
        + format_booking_card(booking)
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=get_admin_booking_actions_keyboard(booking_id, booking["status"]),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_bk_confirm:"))
async def handle_admin_booking_confirm(callback: CallbackQuery):
    """Подтверждает бронирование (pending → confirmed)."""
    await callback.answer()

    booking_id = callback.data.split(":", 1)[1]
    success = await db.update_booking_status(booking_id, "confirmed")

    if success:
        await callback.answer("✅ Бронирование подтверждено!", show_alert=True)
        # Обновляем карточку
        booking = await db.get_booking_by_id(booking_id)
        if booking:
            await callback.message.edit_text(
                text="📋 <b>Детали бронирования</b>\n\n" + format_booking_card(booking),
                reply_markup=get_admin_booking_actions_keyboard(booking_id, booking["status"]),
                parse_mode="HTML",
            )
    else:
        await callback.answer("❌ Ошибка. Попробуйте ещё раз.", show_alert=True)


@router.callback_query(F.data.startswith("admin_bk_cancel:"))
async def handle_admin_booking_cancel(callback: CallbackQuery):
    """Отменяет бронирование (любой статус → cancelled)."""
    await callback.answer()

    booking_id = callback.data.split(":", 1)[1]

    # Сначала освобождаем слот
    booking = await db.get_booking_by_id(booking_id)
    if booking:
        slot = await db.get_slot_by_date_time(booking["booking_date"], booking["booking_time"])
        if slot:
            await db.mark_slot_available(slot["id"])

    success = await db.update_booking_status(booking_id, "cancelled")

    if success:
        await callback.answer("❌ Бронирование отменено. Слот освобождён.", show_alert=True)
        booking = await db.get_booking_by_id(booking_id)
        if booking:
            await callback.message.edit_text(
                text="📋 <b>Детали бронирования</b>\n\n" + format_booking_card(booking),
                reply_markup=get_admin_booking_actions_keyboard(booking_id, booking["status"]),
                parse_mode="HTML",
            )
    else:
        await callback.answer("❌ Ошибка. Попробуйте ещё раз.", show_alert=True)


@router.callback_query(F.data.startswith("admin_bk_restore:"))
async def handle_admin_booking_restore(callback: CallbackQuery):
    """Восстанавливает отменённое бронирование (cancelled → pending)."""
    await callback.answer()

    booking_id = callback.data.split(":", 1)[1]

    # Проверяем: слот всё ещё свободен?
    booking = await db.get_booking_by_id(booking_id)
    if booking:
        slot = await db.get_slot_by_date_time(booking["booking_date"], booking["booking_time"])
        if slot and not slot["is_available"]:
            await callback.answer(
                "⚠️ Слот уже занят другим клиентом. Восстановление невозможно.",
                show_alert=True
            )
            return
        if slot:
            await db.mark_slot_unavailable(slot["id"])

    success = await db.update_booking_status(booking_id, "pending")

    if success:
        await callback.answer("🔄 Бронирование восстановлено", show_alert=True)
        booking = await db.get_booking_by_id(booking_id)
        if booking:
            await callback.message.edit_text(
                text="📋 <b>Детали бронирования</b>\n\n" + format_booking_card(booking),
                reply_markup=get_admin_booking_actions_keyboard(booking_id, booking["status"]),
                parse_mode="HTML",
            )


@router.callback_query(F.data.startswith("admin_bk_delete:"))
async def handle_admin_booking_delete_confirm_prompt(callback: CallbackQuery):
    """
    Запрашивает подтверждение перед удалением бронирования.
    Двойное подтверждение предотвращает случайное удаление.
    """
    await callback.answer()

    booking_id = callback.data.split(":", 1)[1]

    await callback.message.edit_text(
        text=(
            "🗑 <b>Удалить бронирование?</b>\n\n"
            "⚠️ Это действие нельзя отменить!\n"
            "Слот будет освобождён и станет доступен для записи."
        ),
        reply_markup=get_delete_confirm_keyboard(booking_id),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_bk_delete_confirm:"))
async def handle_admin_booking_delete(callback: CallbackQuery):
    """Выполняет окончательное удаление бронирования."""
    await callback.answer()

    booking_id = callback.data.split(":", 1)[1]
    success = await db.delete_booking(booking_id)

    if success:
        await callback.answer("🗑 Бронирование удалено", show_alert=True)

        builder = InlineKeyboardBuilder()
        builder.button(text="📋 К списку", callback_data="admin_bk_filter:all")
        builder.button(text="◀ Меню", callback_data="admin:main")
        builder.adjust(1)

        await callback.message.edit_text(
            text="✅ Бронирование удалено. Слот освобождён.",
            reply_markup=builder.as_markup(),
        )
    else:
        await callback.answer("❌ Ошибка удаления. Попробуйте ещё раз.", show_alert=True)


# ===================================================
# 6. ПЕРЕНОС БРОНИРОВАНИЯ
# ===================================================

@router.callback_query(F.data.startswith("admin_bk_reschedule:"))
async def handle_admin_reschedule_start(callback: CallbackQuery, state: FSMContext):
    """
    Начинает процесс переноса бронирования.
    Запрашивает новую дату.
    """
    await callback.answer()

    booking_id = callback.data.split(":", 1)[1]
    booking = await db.get_booking_by_id(booking_id)

    if not booking:
        await callback.answer("Бронирование не найдено", show_alert=True)
        return

    # Сохраняем данные переноса в FSM
    await state.set_state(AdminRescheduleStates.waiting_new_date)
    await state.update_data(
        reschedule_booking_id=booking_id,
        reschedule_old_date=booking["booking_date"],
        reschedule_old_time=booking["booking_time"],
    )

    # Ищем ID старого слота
    old_slot = await db.get_slot_by_date_time(booking["booking_date"], booking["booking_time"])
    if old_slot:
        await state.update_data(reschedule_old_slot_id=old_slot["id"])

    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"admin_bk_view:{booking_id}")

    await callback.message.edit_text(
        text=(
            f"📅 <b>Перенос бронирования</b>\n\n"
            f"Клиент: {booking['full_name']}\n"
            f"Текущая дата: {format_date_ru(booking['booking_date'])}, {format_time_ru(booking['booking_time'])}\n\n"
            "Введите <b>новую дату</b> для переноса:\n"
            "<i>Формат: ДД.ММ.ГГГГ (например, 20.03.2024)</i>"
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.message(AdminRescheduleStates.waiting_new_date)
async def handle_admin_reschedule_date(message: Message, state: FSMContext):
    """
    Получает новую дату переноса и показывает доступные слоты.
    """
    parsed = parse_date(message.text.strip())

    if not parsed:
        await message.answer(
            "❌ Некорректная дата или дата в прошлом.\n"
            "Введите дату в формате <code>ДД.ММ.ГГГГ</code>, например: <code>20.03.2024</code>",
            parse_mode="HTML",
        )
        return

    year, month, day, date_obj = parsed
    date_str = date_obj.strftime("%Y-%m-%d")

    # Загружаем свободные слоты
    slots = await db.get_available_slots(date_str)

    if not slots:
        await message.answer(
            f"😔 На {format_date_ru(date_str)} нет свободных слотов.\n"
            "Введите другую дату или добавьте слоты в разделе 'Расписание'."
        )
        return

    await state.update_data(reschedule_new_date=date_str)
    await state.set_state(AdminRescheduleStates.waiting_new_time)

    from bot.utils.calendar import build_time_slots_keyboard
    time_keyboard = build_time_slots_keyboard(slots)

    await message.answer(
        text=f"📅 Новая дата: <b>{format_date_ru(date_str)}</b>\n\n🕐 Выберите новое время:",
        reply_markup=time_keyboard,
        parse_mode="HTML",
    )


@router.callback_query(AdminRescheduleStates.waiting_new_time, F.data.startswith("slot:"))
async def handle_admin_reschedule_time(callback: CallbackQuery, state: FSMContext):
    """
    Получает новое время и выполняет перенос бронирования.
    """
    await callback.answer()

    parts = callback.data.split(":")
    new_slot_id = parts[1]
    new_time = f"{parts[2]}:{parts[3]}:00"  # HH:MM:SS

    fsm_data = await state.get_data()
    await state.clear()

    success = await db.reschedule_booking(
        booking_id=fsm_data["reschedule_booking_id"],
        old_slot_id=fsm_data.get("reschedule_old_slot_id", ""),
        new_slot_id=new_slot_id,
        new_date=fsm_data["reschedule_new_date"],
        new_time=new_time,
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="📋 К бронированию", callback_data=f"admin_bk_view:{fsm_data['reschedule_booking_id']}")
    builder.button(text="◀ Меню", callback_data="admin:main")
    builder.adjust(1)

    if success:
        await callback.message.edit_text(
            text=(
                "✅ <b>Бронирование перенесено!</b>\n\n"
                f"Новая дата: <b>{format_date_ru(fsm_data['reschedule_new_date'])}</b>\n"
                f"Новое время: <b>{new_time[:5]}</b>"
            ),
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            "❌ Ошибка при переносе. Попробуйте ещё раз.",
            reply_markup=builder.as_markup(),
        )


# ===================================================
# 7. УПРАВЛЕНИЕ РАСПИСАНИЕМ (СЛОТЫ)
# ===================================================

@router.callback_query(F.data == "admin:schedule")
async def handle_admin_schedule(callback: CallbackQuery, state: FSMContext):
    """Открывает раздел управления расписанием."""
    await callback.answer()
    await state.clear()

    await callback.message.edit_text(
        text=(
            "📅 <b>Управление расписанием</b>\n\n"
            "Здесь вы можете добавлять рабочие дни\n"
            "и управлять временными слотами."
        ),
        reply_markup=get_admin_schedule_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_sched:add_day")
async def handle_admin_sched_add_day(callback: CallbackQuery, state: FSMContext):
    """Запрашивает дату для создания нового рабочего дня."""
    await callback.answer()
    await state.set_state(AdminSlotStates.waiting_date)
    await state.update_data(filter_context="schedule")  # Контекст: добавление слотов

    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="admin:schedule")

    await callback.message.edit_text(
        text=(
            "📅 <b>Добавить рабочий день</b>\n\n"
            "Введите дату нового рабочего дня:\n"
            "<i>Формат: ДД.ММ.ГГГГ (например, 25.03.2024)</i>"
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.message(AdminSlotStates.waiting_date)
async def handle_admin_sched_date(message: Message, state: FSMContext):
    """
    Обрабатывает введённую дату.
    Если контекст = "schedule" → показываем слоты для добавления.
    Если контекст = "bookings" → показываем бронирования за день.
    """
    parsed = parse_date(message.text.strip())

    if not parsed:
        await message.answer(
            "❌ Некорректная дата или дата в прошлом.\n"
            "Формат: <code>ДД.ММ.ГГГГ</code>",
            parse_mode="HTML",
        )
        return

    year, month, day, date_obj = parsed
    date_str = date_obj.strftime("%Y-%m-%d")

    fsm_data = await state.get_data()
    context = fsm_data.get("filter_context", "schedule")

    if context == "bookings":
        # Показываем бронирования за выбранную дату
        await state.clear()
        await _show_bookings_page(
            message,
            page=0,
            filter_type="date",
            date_filter=date_str,
            edit=False,
        )
        return

    # Контекст schedule: показываем выбор временных слотов
    await state.update_data(sched_date=date_str)
    await state.set_state(AdminSlotStates.waiting_time)

    await message.answer(
        text=(
            f"📅 Дата: <b>{format_date_ru(date_str)}</b>\n\n"
            "🕐 Нажмите на время чтобы добавить рабочий слот.\n"
            "Нажмите <b>✅ Готово</b> когда добавите все нужные слоты."
        ),
        reply_markup=get_admin_time_slots_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(AdminSlotStates.waiting_time, F.data.startswith("admin_add_slot:"))
async def handle_admin_add_slot(callback: CallbackQuery, state: FSMContext):
    """
    Добавляет один временной слот для выбранной даты.
    Администратор нажимает кнопки по одной — каждое нажатие добавляет слот.
    """
    time_str = callback.data.split(":", 1)[1]  # "10:00"

    fsm_data = await state.get_data()
    date_str = fsm_data.get("sched_date")

    # Проверяем: нет ли уже такого слота
    existing = await db.get_slot_by_date_time(date_str, time_str)

    if existing:
        await callback.answer(f"⚠️ Слот {time_str} уже существует", show_alert=False)
        return

    result = await db.add_time_slot(date_str, time_str)

    if result:
        await callback.answer(f"✅ Слот {time_str} добавлен!")
    else:
        await callback.answer(f"❌ Ошибка добавления слота {time_str}", show_alert=True)


@router.callback_query(AdminSlotStates.waiting_time, F.data == "admin_sched:done")
async def handle_admin_sched_done(callback: CallbackQuery, state: FSMContext):
    """Завершает добавление слотов и возвращает в меню расписания."""
    await callback.answer("✅ Расписание сохранено!")
    await state.clear()

    await callback.message.edit_text(
        text="✅ Расписание обновлено!\n\nВыберите действие:",
        reply_markup=get_admin_schedule_keyboard(),
    )


@router.callback_query(F.data == "admin_sched:view_day")
async def handle_admin_sched_view_day(callback: CallbackQuery, state: FSMContext):
    """Запрашивает дату для просмотра слотов конкретного дня."""
    await callback.answer()
    await state.set_state(AdminSlotStates.waiting_date)
    await state.update_data(filter_context="view_slots")

    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="admin:schedule")

    await callback.message.edit_text(
        text=(
            "📅 Введите дату для просмотра расписания:\n"
            "<i>Формат: ДД.ММ.ГГГГ</i>"
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_del_slot:"))
async def handle_admin_delete_slot(callback: CallbackQuery):
    """Удаляет временной слот из расписания."""
    await callback.answer()

    slot_id = callback.data.split(":", 1)[1]
    success = await db.delete_time_slot(slot_id)

    if success:
        await callback.answer("🗑 Слот удалён", show_alert=True)
    else:
        await callback.answer("❌ Ошибка удаления", show_alert=True)
