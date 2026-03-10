# ===================================================
# handlers/admin.py — Полная административная панель
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
from bot.states import AdminServiceStates, AdminSlotStates, AdminRescheduleStates, AdminBookingStates
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
    is_valid_phone,
    normalize_phone,
)
from bot.utils.calendar import build_time_slots_keyboard
from bot import database as db

logger = logging.getLogger(__name__)

BOOKINGS_PER_PAGE = 8


# ===================================================
# MIDDLEWARE: ПРОВЕРКА ПРАВ АДМИНИСТРАТОРА
# ===================================================

class AdminMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user_id = None

        if hasattr(event, "from_user") and event.from_user:
            user_id = event.from_user.id
        elif hasattr(event, "message") and event.message:
            user_id = event.message.from_user.id

        admin_ids = settings.get_admin_ids()

        if user_id not in admin_ids:
            if hasattr(event, "answer"):
                await event.answer("⛔ У вас нет доступа к этой команде.")
            elif hasattr(event, "message"):
                await event.message.answer("⛔ У вас нет доступа.")
                await event.answer()
            return

        return await handler(event, data)


router = Router()
router.message.middleware(AdminMiddleware())
router.callback_query.middleware(AdminMiddleware())


# ===================================================
# ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: ФОРМАТИРОВАНИЕ БРОНИРОВАНИЯ
# ===================================================

def format_booking_card(booking: Dict) -> str:
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
        f"Статус: {status_display}"
    )


# ===================================================
# 1. ГЛАВНОЕ МЕНЮ АДМИНИСТРАТОРА
# ===================================================

@router.message(Command("admin"))
async def handle_admin_command(message: Message, state: FSMContext):
    await state.clear()
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
    await callback.answer()

    total = await db.get_bookings_count()
    pending = await db.get_bookings_count("pending")
    confirmed = await db.get_bookings_count("confirmed")
    cancelled = await db.get_bookings_count("cancelled")

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
    await callback.answer()
    await state.clear()

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
    await callback.answer()

    action = callback.data.split(":", 1)[1]

    if action == "add":
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
                f"Статус: {status_text}"
            ),
            reply_markup=get_admin_service_detail_keyboard(service_id, service["is_active"]),
            parse_mode="HTML",
        )


# ФИX #2: добавлен F.text — защита от нетекстовых сообщений
@router.message(AdminServiceStates.waiting_name, F.text)
async def handle_admin_service_name(message: Message, state: FSMContext):
    name = message.text.strip()

    if len(name) < 3:
        await message.answer("❌ Название слишком короткое. Введите минимум 3 символа.")
        return

    if len(name) > 100:
        await message.answer("❌ Название слишком длинное. Максимум 100 символов.")
        return

    await state.update_data(service_name=name)
    await state.set_state(AdminServiceStates.waiting_duration)

    await message.answer(
        text=(
            f"✅ Название: <b>{name}</b>\n\n"
            "Шаг 2/3: Выберите <b>длительность</b> услуги:"
        ),
        reply_markup=get_admin_duration_keyboard(),
        parse_mode="HTML",
    )


# Catch-хендлер для нетекстовых сообщений на шаге названия
@router.message(AdminServiceStates.waiting_name)
async def handle_admin_service_name_invalid(message: Message):
    await message.answer("❌ Пожалуйста, введите название услуги текстом.")


@router.callback_query(AdminServiceStates.waiting_duration, F.data.startswith("duration:"))
async def handle_admin_service_duration(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    duration = int(callback.data.split(":")[1])
    await state.update_data(service_duration=duration)
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


# ФИX #2: добавлен F.text
# ФИX #3: state.clear() только при успехе — при ошибке можно повторить
@router.message(AdminServiceStates.waiting_price, F.text)
async def handle_admin_service_price(message: Message, state: FSMContext):
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

    service = await db.add_service(
        name=fsm_data["service_name"],
        duration_min=fsm_data["service_duration"],
        price=price,
    )

    if service:
        # ФИX #3: очищаем состояние только при успехе
        await state.clear()

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
        # DB-ошибка: повтор той же цены не поможет → очищаем состояние
        await state.clear()
        builder = InlineKeyboardBuilder()
        builder.button(text="◀ К списку услуг", callback_data="admin:services")
        await message.answer(
            "❌ <b>Ошибка при добавлении услуги.</b>\n\n"
            "Проверьте, что в <code>.env</code> указан ключ "
            "<b>service_role</b> от Supabase (не anon).\n\n"
            "Settings → API → service_role (secret)",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )


# Catch-хендлер для нетекстовых сообщений на шаге цены
@router.message(AdminServiceStates.waiting_price)
async def handle_admin_service_price_invalid(message: Message):
    await message.answer(
        "❌ Введите цену числом, например: <code>1500</code>",
        parse_mode="HTML",
    )


# ФИX #1: убран первый callback.answer() — теперь отвечаем один раз с нужным текстом
@router.callback_query(F.data.startswith("admin_svc_hide:"))
async def handle_admin_service_hide(callback: CallbackQuery):
    service_id = callback.data.split(":", 1)[1]
    success = await db.toggle_service_status(service_id, False)

    if success:
        await callback.answer("🔴 Услуга скрыта от клиентов", show_alert=True)
        services = await db.get_all_services(active_only=False)
        await callback.message.edit_reply_markup(
            reply_markup=get_admin_services_keyboard(services)
        )
    else:
        await callback.answer("❌ Ошибка. Попробуйте ещё раз.", show_alert=True)


# ФИX #1: убран первый callback.answer()
@router.callback_query(F.data.startswith("admin_svc_show:"))
async def handle_admin_service_show(callback: CallbackQuery):
    service_id = callback.data.split(":", 1)[1]
    success = await db.toggle_service_status(service_id, True)

    if success:
        await callback.answer("✅ Услуга снова доступна клиентам", show_alert=True)
        services = await db.get_all_services(active_only=False)
        await callback.message.edit_reply_markup(
            reply_markup=get_admin_services_keyboard(services)
        )
    else:
        await callback.answer("❌ Ошибка. Попробуйте ещё раз.", show_alert=True)


@router.callback_query(F.data.startswith("admin_svc_del:"))
async def handle_admin_service_delete(callback: CallbackQuery):
    await callback.answer()
    service_id = callback.data.split(":", 1)[1]

    has_bookings = await db.service_has_bookings(service_id)

    if has_bookings:
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
    await callback.answer()

    filter_type = callback.data.split(":", 1)[1]

    if filter_type == "date":
        await state.set_state(AdminSlotStates.waiting_date)
        await state.update_data(filter_context="bookings")

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

    lines = [f"📋 <b>Бронирования</b> (стр. {page + 1}/{total_pages}, всего: {total})\n"]

    builder = InlineKeyboardBuilder()

    for i, booking in enumerate(bookings, start=1):
        service_name = booking.get("services", {}).get("name", "?")
        time_str = format_time_ru(booking["booking_time"])
        date_str = format_date_ru(booking["booking_date"])
        status_icon = {"pending": "⏳", "confirmed": "✅", "cancelled": "❌"}.get(booking["status"], "?")

        lines.append(
            f"{i}. {status_icon} {booking['full_name']}\n"
            f"   {service_name} | {date_str} {time_str}"
        )

        builder.button(
            text=f"{i}. {booking['full_name'][:20]}",
            callback_data=f"admin_bk_view:{booking['id']}"
        )

    text = "\n".join(lines)

    builder.adjust(2)
    pagination_kb = get_admin_pagination_keyboard(page, total_pages, filter_type)

    for btn_row in pagination_kb.inline_keyboard:
        builder.row(*btn_row)

    if edit:
        await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("admin_bk_page:"))
async def handle_admin_bookings_page(callback: CallbackQuery):
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
    await callback.answer()

    page = int(callback.data.split(":")[1])
    await _show_bookings_page(callback.message, page=page, filter_type="all", edit=True)


# ===================================================
# 5. ДЕТАЛЬНЫЙ ПРОСМОТР И ДЕЙСТВИЯ С БРОНИРОВАНИЕМ
# ===================================================

@router.callback_query(F.data.startswith("admin_bk_view:"))
async def handle_admin_booking_view(callback: CallbackQuery, state: FSMContext):
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
    await callback.answer()

    booking_id = callback.data.split(":", 1)[1]
    success = await db.update_booking_status(booking_id, "confirmed")

    if success:
        await callback.answer("✅ Бронирование подтверждено!", show_alert=True)
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
    await callback.answer()

    booking_id = callback.data.split(":", 1)[1]

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
    await callback.answer()

    booking_id = callback.data.split(":", 1)[1]

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
    await callback.answer()

    booking_id = callback.data.split(":", 1)[1]
    booking = await db.get_booking_by_id(booking_id)

    if not booking:
        await callback.answer("Бронирование не найдено", show_alert=True)
        return

    await state.set_state(AdminRescheduleStates.waiting_new_date)
    await state.update_data(
        reschedule_booking_id=booking_id,
        reschedule_old_date=booking["booking_date"],
        reschedule_old_time=booking["booking_time"],
    )

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


# ФИX #2: добавлен F.text
@router.message(AdminRescheduleStates.waiting_new_date, F.text)
async def handle_admin_reschedule_date(message: Message, state: FSMContext):
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

    slots = await db.get_available_slots(date_str)

    if not slots:
        await message.answer(
            f"😔 На {format_date_ru(date_str)} нет свободных слотов.\n"
            "Введите другую дату или добавьте слоты в разделе 'Расписание'."
        )
        return

    await state.update_data(reschedule_new_date=date_str)
    await state.set_state(AdminRescheduleStates.waiting_new_time)

    time_keyboard = build_time_slots_keyboard(slots)

    await message.answer(
        text=f"📅 Новая дата: <b>{format_date_ru(date_str)}</b>\n\n🕐 Выберите новое время:",
        reply_markup=time_keyboard,
        parse_mode="HTML",
    )


# Catch-хендлер для нетекстовых сообщений
@router.message(AdminRescheduleStates.waiting_new_date)
async def handle_admin_reschedule_date_invalid(message: Message):
    await message.answer(
        "❌ Введите дату текстом в формате <code>ДД.ММ.ГГГГ</code>",
        parse_mode="HTML",
    )


@router.callback_query(AdminRescheduleStates.waiting_new_time, F.data.startswith("slot:"))
async def handle_admin_reschedule_time(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    parts = callback.data.split(":")
    new_slot_id = parts[1]
    new_time = f"{parts[2]}:{parts[3]}:00"

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
    await callback.answer()
    await state.set_state(AdminSlotStates.waiting_date)
    await state.update_data(filter_context="schedule")

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


# ФИX #2: добавлен F.text
# ФИX #4: добавлена ветка view_slots — теперь "Просмотр дня" показывает существующие слоты
@router.message(AdminSlotStates.waiting_date, F.text)
async def handle_admin_sched_date(message: Message, state: FSMContext):
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
        await state.clear()
        await _show_bookings_page(
            message,
            page=0,
            filter_type="date",
            date_filter=date_str,
            edit=False,
        )
        return

    # ФИX #4: контекст view_slots — показываем существующие слоты дня
    if context == "view_slots":
        await state.clear()
        slots = await db.get_all_slots_for_date(date_str)

        if not slots:
            builder = InlineKeyboardBuilder()
            builder.button(text="◀ К расписанию", callback_data="admin:schedule")
            await message.answer(
                f"📅 <b>{format_date_ru(date_str)}</b>\n\nНа этот день слотов нет.",
                reply_markup=builder.as_markup(),
                parse_mode="HTML",
            )
            return

        await message.answer(
            text=f"📅 <b>{format_date_ru(date_str)}</b>\n\n🟢 — свободен  🔴 — занят",
            reply_markup=get_admin_slots_list_keyboard(slots),
            parse_mode="HTML",
        )
        return

    # Контекст schedule: показываем выбор временных слотов для добавления
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


# Catch-хендлер для нетекстовых сообщений на шаге даты
@router.message(AdminSlotStates.waiting_date)
async def handle_admin_sched_date_invalid(message: Message):
    await message.answer(
        "❌ Введите дату текстом в формате <code>ДД.ММ.ГГГГ</code>",
        parse_mode="HTML",
    )


@router.callback_query(AdminSlotStates.waiting_time, F.data.startswith("admin_add_slot:"))
async def handle_admin_add_slot(callback: CallbackQuery, state: FSMContext):
    time_str = callback.data.split(":", 1)[1]

    fsm_data = await state.get_data()
    date_str = fsm_data.get("sched_date")

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
    await callback.answer("✅ Расписание сохранено!")
    await state.clear()

    await callback.message.edit_text(
        text="✅ Расписание обновлено!\n\nВыберите действие:",
        reply_markup=get_admin_schedule_keyboard(),
    )


@router.callback_query(F.data == "admin_sched:view_day")
async def handle_admin_sched_view_day(callback: CallbackQuery, state: FSMContext):
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


# ФИX #1: убран первый callback.answer()
@router.callback_query(F.data.startswith("admin_del_slot:"))
async def handle_admin_delete_slot(callback: CallbackQuery):
    slot_id = callback.data.split(":", 1)[1]
    success = await db.delete_time_slot(slot_id)

    if success:
        await callback.answer("🗑 Слот удалён", show_alert=True)
    else:
        await callback.answer("❌ Ошибка удаления", show_alert=True)


# ===================================================
# 8. СОЗДАНИЕ БРОНИРОВАНИЯ АДМИНИСТРАТОРОМ (новый флоу)
# ===================================================

@router.callback_query(F.data == "admin:create_booking")
async def handle_admin_create_booking_start(callback: CallbackQuery, state: FSMContext):
    """Запускает флоу ручного создания бронирования администратором."""
    await callback.answer()

    services = await db.get_all_services(active_only=True)

    if not services:
        await callback.answer("❌ Нет активных услуг. Сначала добавьте услуги.", show_alert=True)
        return

    await state.set_state(AdminBookingStates.waiting_service)

    builder = InlineKeyboardBuilder()
    for svc in services:
        builder.button(
            text=f"💅 {svc['name']} — {svc['price']} ₽",
            callback_data=f"admin_cb_svc:{svc['id']}"
        )
    builder.button(text="❌ Отмена", callback_data="admin:main")
    builder.adjust(1)

    await callback.message.edit_text(
        text="➕ <b>Создать бронирование</b>\n\nШаг 1/5: Выберите услугу:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(AdminBookingStates.waiting_service, F.data.startswith("admin_cb_svc:"))
async def handle_admin_create_booking_service(callback: CallbackQuery, state: FSMContext):
    """Шаг 1: выбор услуги → ввод даты."""
    await callback.answer()

    service_id = callback.data.split(":", 1)[1]
    service = await db.get_service_by_id(service_id)

    if not service:
        await callback.answer("Услуга не найдена", show_alert=True)
        return

    await state.update_data(
        cb_service_id=service_id,
        cb_service_name=service["name"],
        cb_service_price=service["price"],
        cb_service_duration=service["duration_min"],
    )
    await state.set_state(AdminBookingStates.waiting_date)

    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="admin:main")

    await callback.message.edit_text(
        text=(
            f"✅ Услуга: <b>{service['name']}</b>\n\n"
            "Шаг 2/5: Введите дату записи:\n"
            "<i>Формат: ДД.ММ.ГГГГ (например, 25.03.2024)</i>"
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.message(AdminBookingStates.waiting_date, F.text)
async def handle_admin_create_booking_date(message: Message, state: FSMContext):
    """Шаг 2: ввод даты → выбор слота времени."""
    parsed = parse_date(message.text.strip())

    if not parsed:
        await message.answer(
            "❌ Некорректная дата или дата в прошлом.\n"
            "Введите дату в формате <code>ДД.ММ.ГГГГ</code>",
            parse_mode="HTML",
        )
        return

    year, month, day, date_obj = parsed
    date_str = date_obj.strftime("%Y-%m-%d")

    slots = await db.get_available_slots(date_str)

    if not slots:
        await message.answer(
            f"😔 На {format_date_ru(date_str)} нет свободных слотов.\n"
            "Введите другую дату или добавьте слоты в разделе 'Расписание'."
        )
        return

    await state.update_data(cb_date=date_str)
    await state.set_state(AdminBookingStates.waiting_time)

    fsm_data = await state.get_data()
    time_keyboard = build_time_slots_keyboard(slots)

    await message.answer(
        text=(
            f"✅ Услуга: <b>{fsm_data['cb_service_name']}</b>\n"
            f"✅ Дата: <b>{format_date_ru(date_str)}</b>\n\n"
            "Шаг 3/5: Выберите время:"
        ),
        reply_markup=time_keyboard,
        parse_mode="HTML",
    )


@router.message(AdminBookingStates.waiting_date)
async def handle_admin_create_booking_date_invalid(message: Message):
    await message.answer(
        "❌ Введите дату текстом в формате <code>ДД.ММ.ГГГГ</code>",
        parse_mode="HTML",
    )


@router.callback_query(AdminBookingStates.waiting_time, F.data.startswith("slot:"))
async def handle_admin_create_booking_time(callback: CallbackQuery, state: FSMContext):
    """Шаг 3: выбор времени → ввод имени клиента."""
    await callback.answer()

    parts = callback.data.split(":")
    slot_id = parts[1]
    selected_time = f"{parts[2]}:{parts[3]}"

    await state.update_data(cb_slot_id=slot_id, cb_time=selected_time)
    await state.set_state(AdminBookingStates.waiting_name)

    fsm_data = await state.get_data()

    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="admin:main")

    await callback.message.edit_text(
        text=(
            f"✅ Услуга: <b>{fsm_data['cb_service_name']}</b>\n"
            f"✅ Дата: <b>{format_date_ru(fsm_data['cb_date'])}</b>\n"
            f"✅ Время: <b>{selected_time}</b>\n\n"
            "Шаг 4/5: Введите <b>имя клиента</b>:"
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.message(AdminBookingStates.waiting_name, F.text)
async def handle_admin_create_booking_name(message: Message, state: FSMContext):
    """Шаг 4: ввод имени → ввод телефона."""
    name = message.text.strip()

    if len(name) < 2:
        await message.answer("❌ Имя слишком короткое. Введите минимум 2 символа.")
        return

    await state.update_data(cb_client_name=name)
    await state.set_state(AdminBookingStates.waiting_phone)

    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="admin:main")

    await message.answer(
        text=(
            f"✅ Имя клиента: <b>{name}</b>\n\n"
            "Шаг 5/5: Введите <b>номер телефона</b> клиента:\n"
            "<i>Например: +79161234567 или 89161234567</i>"
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.message(AdminBookingStates.waiting_name)
async def handle_admin_create_booking_name_invalid(message: Message):
    await message.answer("❌ Введите имя клиента текстом.")


@router.message(AdminBookingStates.waiting_phone, F.text)
async def handle_admin_create_booking_phone(message: Message, state: FSMContext):
    """Шаг 5: ввод телефона → создание бронирования в БД."""
    phone_text = message.text.strip()

    if not is_valid_phone(phone_text):
        await message.answer(
            "❌ Некорректный номер телефона.\n"
            "Введите в формате: <code>+79161234567</code> или <code>89161234567</code>",
            parse_mode="HTML",
        )
        return

    phone = normalize_phone(phone_text)
    fsm_data = await state.get_data()

    booking = await db.create_booking(
        user_id=message.from_user.id,
        username=message.from_user.username,
        full_name=fsm_data["cb_client_name"],
        phone=phone,
        service_id=fsm_data["cb_service_id"],
        slot_id=fsm_data["cb_slot_id"],
        booking_date=fsm_data["cb_date"],
        booking_time=fsm_data["cb_time"] + ":00",
    )

    if booking:
        await state.clear()

        builder = InlineKeyboardBuilder()
        builder.button(text="📋 Посмотреть запись", callback_data=f"admin_bk_view:{booking['id']}")
        builder.button(text="➕ Создать ещё", callback_data="admin:create_booking")
        builder.button(text="◀ Главное меню", callback_data="admin:main")
        builder.adjust(1)

        await message.answer(
            text=(
                "✅ <b>Бронирование создано!</b>\n\n"
                f"👤 Клиент: <b>{fsm_data['cb_client_name']}</b>\n"
                f"📱 Телефон: <b>{phone}</b>\n"
                f"💅 Услуга: <b>{fsm_data['cb_service_name']}</b>\n"
                f"📅 Дата: <b>{format_date_ru(fsm_data['cb_date'])}</b>\n"
                f"🕐 Время: <b>{fsm_data['cb_time']}</b>\n"
                f"💰 Стоимость: <b>{fsm_data['cb_service_price']} ₽</b>"
            ),
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
    else:
        # DB-ошибка: очищаем состояние, чтобы admin не застрял
        await state.clear()
        builder = InlineKeyboardBuilder()
        builder.button(text="◀ Главное меню", callback_data="admin:main")
        await message.answer(
            "❌ <b>Ошибка при создании бронирования.</b>\n\n"
            "Проверьте, что в <code>.env</code> указан ключ "
            "<b>service_role</b> от Supabase (не anon).\n\n"
            "Settings → API → service_role (secret)",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )


@router.message(AdminBookingStates.waiting_phone)
async def handle_admin_create_booking_phone_invalid(message: Message):
    await message.answer(
        "❌ Введите номер телефона текстом, например: <code>+79161234567</code>",
        parse_mode="HTML",
    )
