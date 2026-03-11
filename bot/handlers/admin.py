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
from typing import Callable, Dict, Any, Awaitable, Optional, Set

from bot.config import settings
from bot.states import AdminServiceStates, AdminSlotStates, AdminRescheduleStates, AdminBookingStates, AdminMgmtStates
from bot.keyboards import (
    get_admin_main_keyboard,
    get_admin_services_keyboard,
    get_admin_service_detail_keyboard,
    get_admin_duration_keyboard,
    get_admin_edit_skip_keyboard,
    get_admin_edit_duration_keyboard,
    get_admin_bookings_filter_keyboard,
    get_admin_booking_actions_keyboard,
    get_admin_pagination_keyboard,
    get_admin_schedule_keyboard,
    get_admin_time_slots_keyboard,
    get_admin_slots_list_keyboard,
    get_admin_admins_keyboard,
    get_admin_transfer_keyboard,
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
from bot.utils.calendar import build_time_slots_keyboard, build_admin_calendar, build_admin_bookings_calendar, get_current_month_year
from bot import database as db

logger = logging.getLogger(__name__)

BOOKINGS_PER_PAGE = 8


# ===================================================
# КЭШ АДМИНИСТРАТОРОВ
# ===================================================
# Хранит объединённый набор ID из .env и таблицы admins.
# Сбрасывается после add_admin / remove_admin.

_admin_cache: Optional[Set[int]] = None


def _get_admin_ids() -> Set[int]:
    """
    Возвращает множество Telegram ID всех администраторов:
    из .env (ADMIN_IDS) + из таблицы admins в БД.
    При первом вызове и после инвалидации делает sync-запрос к БД.
    """
    global _admin_cache
    if _admin_cache is not None:
        return _admin_cache

    env_ids: Set[int] = set(settings.get_admin_ids())
    db_ids: Set[int] = set()

    if db.supabase is not None:
        try:
            resp = db.supabase.table("admins").select("telegram_id").execute()
            db_ids = {row["telegram_id"] for row in (resp.data or [])}
        except Exception as e:
            logger.warning(f"Не удалось загрузить администраторов из БД: {e}")

    _admin_cache = env_ids | db_ids
    logger.debug(f"Кэш администраторов обновлён: {_admin_cache}")
    return _admin_cache


def _invalidate_admin_cache():
    """Сбрасывает кэш администраторов. Вызывать после add/remove admin."""
    global _admin_cache
    _admin_cache = None


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

        if user_id in _get_admin_ids():
            return await handler(event, data)

        # Не администратор — вежливая заглушка
        stub = (
            "🚫 Административная панель доступна только сотрудникам салона.\n\n"
            "Для записи используйте /start 💅"
        )
        if hasattr(event, "answer") and callable(event.answer):
            # CallbackQuery
            try:
                await event.answer("⛔ Нет доступа", show_alert=True)
            except Exception:
                pass
        elif hasattr(event, "message") and event.message:
            await event.message.answer(stub)
            await event.answer()
        elif hasattr(event, "answer"):
            # Message
            await event.answer(stub)
        return


router = Router()
router.message.middleware(AdminMiddleware())
router.callback_query.middleware(AdminMiddleware())


# ===================================================
# ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: ФОРМАТИРОВАНИЕ БРОНИРОВАНИЯ
# ===================================================

def format_booking_card(booking: Dict, comfort_prefs: Optional[str] = None) -> str:
    service_name = booking.get("services", {}).get("name", "Неизвестно")
    service_price = booking.get("services", {}).get("price", "—")
    date_display = format_date_ru(booking["booking_date"])
    time_display = format_time_ru(booking["booking_time"])
    status_display = format_status_ru(booking["status"])

    comfort_line = f"\n☕ Пожелания: {comfort_prefs}" if comfort_prefs else ""

    return (
        f"👤 <b>{booking['full_name']}</b>\n"
        f"📱 {booking['phone']}\n"
        f"{'@' + booking['username'] if booking.get('username') else ''}\n"
        f"💅 {service_name} — {service_price} ₽\n"
        f"📅 {date_display}, 🕐 {time_display}\n"
        f"Статус: {status_display}"
        f"{comfort_line}"
    )


async def _render_booking_detail(booking: Dict) -> str:
    """
    Формирует полный текст карточки бронирования.
    Подтягивает пожелания клиента из client_surveys по booking_id.
    """
    survey = await db.get_survey_by_booking_id(booking["id"])
    comfort = survey.get("comfort_prefs") if survey else None
    return "📋 <b>Детали бронирования</b>\n\n" + format_booking_card(booking, comfort_prefs=comfort)


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
# 3б. РЕДАКТИРОВАНИЕ УСЛУГИ
# ===================================================

async def _show_edit_name_step(target, service: dict) -> None:
    """Отображает шаг 1/3 редактирования: ввод нового названия."""
    text = (
        f"✏️ <b>Редактирование услуги</b>\n\n"
        f"Текущее название: <b>{service['name']}</b>\n\n"
        "Шаг 1/3: Введите <b>новое название</b> или пропустите:"
    )
    kb = get_admin_edit_skip_keyboard("edit_skip_name", "edit_cancel")
    if hasattr(target, "message"):
        await target.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
    else:
        await target.edit_text(text=text, reply_markup=kb, parse_mode="HTML")


async def _show_edit_duration_step(target, service: dict) -> None:
    """Отображает шаг 2/3 редактирования: выбор новой длительности."""
    text = (
        f"✏️ <b>Редактирование услуги</b>\n\n"
        f"Текущая длительность: <b>{service['duration_min']} мин</b>\n\n"
        "Шаг 2/3: Выберите <b>новую длительность</b> или пропустите:"
    )
    kb = get_admin_edit_duration_keyboard()
    if hasattr(target, "message"):
        await target.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
    else:
        await target.edit_text(text=text, reply_markup=kb, parse_mode="HTML")


async def _show_edit_price_step(target, service: dict) -> None:
    """Отображает шаг 3/3 редактирования: ввод новой цены."""
    text = (
        f"✏️ <b>Редактирование услуги</b>\n\n"
        f"Текущая цена: <b>{service['price']} ₽</b>\n\n"
        "Шаг 3/3: Введите <b>новую цену</b> (₽) или пропустите:"
    )
    kb = get_admin_edit_skip_keyboard("edit_skip_price", "edit_cancel")
    if hasattr(target, "message"):
        await target.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
    else:
        await target.edit_text(text=text, reply_markup=kb, parse_mode="HTML")


async def _apply_and_finish_edit(callback: CallbackQuery, state: FSMContext) -> None:
    """Собирает изменения из FSM, сохраняет в БД, показывает результат."""
    data = await state.get_data()
    service_id = data["edit_service_id"]
    new_name = data.get("edit_new_name")
    new_duration = data.get("edit_new_duration")
    new_price = data.get("edit_new_price")
    await state.clear()

    # Если ни одного поля не изменили
    if new_name is None and new_duration is None and new_price is None:
        service = await db.get_service_by_id(service_id)
        await callback.answer("Ничего не изменено", show_alert=False)
        if service:
            status_text = "✅ Активна" if service["is_active"] else "🔴 Скрыта"
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
        return

    success = await db.update_service(
        service_id,
        name=new_name,
        duration_min=new_duration,
        price=new_price,
    )

    service = await db.get_service_by_id(service_id)

    if success and service:
        status_text = "✅ Активна" if service["is_active"] else "🔴 Скрыта"
        await callback.message.edit_text(
            text=(
                "✅ <b>Услуга обновлена!</b>\n\n"
                f"💅 {service['name']}\n"
                f"⏱ {service['duration_min']} мин\n"
                f"💰 {service['price']} ₽\n"
                f"Статус: {status_text}"
            ),
            reply_markup=get_admin_service_detail_keyboard(service_id, service["is_active"]),
            parse_mode="HTML",
        )
    elif not success:
        # Скорее всего конфликт имени
        builder = InlineKeyboardBuilder()
        builder.button(text="✏️ Попробовать снова", callback_data=f"admin_svc_edit:{service_id}")
        builder.button(text="◀ К услуге", callback_data=f"admin_svc:{service_id}")
        builder.adjust(1)
        await callback.message.edit_text(
            text=(
                "❌ <b>Ошибка при сохранении</b>\n\n"
                "Возможно, услуга с таким названием уже существует.\n"
                "Попробуйте другое название."
            ),
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
    else:
        await callback.answer("✅ Обновлено", show_alert=False)


@router.callback_query(F.data.startswith("admin_svc_edit:"))
async def handle_admin_service_edit_start(callback: CallbackQuery, state: FSMContext):
    """Запускает флоу редактирования: загружает услугу в FSM, показывает шаг 1."""
    await callback.answer()
    service_id = callback.data.split(":", 1)[1]

    service = await db.get_service_by_id(service_id)
    if not service:
        await callback.answer("Услуга не найдена", show_alert=True)
        return

    await state.set_state(AdminServiceStates.waiting_edit_name)
    await state.update_data(edit_service_id=service_id)
    await _show_edit_name_step(callback, service)


@router.message(AdminServiceStates.waiting_edit_name, F.text)
async def handle_admin_edit_name_input(message: Message, state: FSMContext):
    """Шаг 1: администратор ввёл новое название."""
    name = message.text.strip()
    if len(name) < 3:
        await message.answer("❌ Название слишком короткое. Минимум 3 символа.")
        return
    if len(name) > 100:
        await message.answer("❌ Название слишком длинное. Максимум 100 символов.")
        return

    await state.update_data(edit_new_name=name)
    await state.set_state(AdminServiceStates.waiting_edit_duration)

    data = await state.get_data()
    service = await db.get_service_by_id(data["edit_service_id"])
    if service:
        await _show_edit_duration_step(message, service)


@router.message(AdminServiceStates.waiting_edit_name)
async def handle_admin_edit_name_invalid(message: Message):
    await message.answer("❌ Введите название услуги текстом.")


@router.callback_query(F.data == "edit_skip_name")
async def handle_admin_edit_name_skip(callback: CallbackQuery, state: FSMContext):
    """Шаг 1: пропустить изменение названия."""
    await callback.answer()
    await state.set_state(AdminServiceStates.waiting_edit_duration)

    data = await state.get_data()
    service = await db.get_service_by_id(data["edit_service_id"])
    if service:
        await _show_edit_duration_step(callback, service)


@router.callback_query(AdminServiceStates.waiting_edit_duration, F.data.startswith("duration:"))
async def handle_admin_edit_duration(callback: CallbackQuery, state: FSMContext):
    """Шаг 2: администратор выбрал новую длительность."""
    await callback.answer()
    duration = int(callback.data.split(":")[1])

    await state.update_data(edit_new_duration=duration)
    await state.set_state(AdminServiceStates.waiting_edit_price)

    data = await state.get_data()
    service = await db.get_service_by_id(data["edit_service_id"])
    if service:
        await _show_edit_price_step(callback, service)


@router.callback_query(F.data == "edit_skip_duration")
async def handle_admin_edit_duration_skip(callback: CallbackQuery, state: FSMContext):
    """Шаг 2: пропустить изменение длительности."""
    await callback.answer()
    await state.set_state(AdminServiceStates.waiting_edit_price)

    data = await state.get_data()
    service = await db.get_service_by_id(data["edit_service_id"])
    if service:
        await _show_edit_price_step(callback, service)


@router.message(AdminServiceStates.waiting_edit_price, F.text)
async def handle_admin_edit_price_input(message: Message, state: FSMContext):
    """Шаг 3: администратор ввёл новую цену — применяем все изменения."""
    price_str = message.text.strip()
    if not is_valid_price(price_str):
        await message.answer(
            "❌ Некорректная цена. Введите целое положительное число, например: <code>1500</code>",
            parse_mode="HTML",
        )
        return

    await state.update_data(edit_new_price=int(price_str))

    # Применяем через фиктивный callback (отправляем новое сообщение с результатом)
    data = await state.get_data()
    service_id = data["edit_service_id"]
    new_name = data.get("edit_new_name")
    new_duration = data.get("edit_new_duration")
    new_price = int(price_str)
    await state.clear()

    success = await db.update_service(service_id, name=new_name, duration_min=new_duration, price=new_price)
    service = await db.get_service_by_id(service_id)

    builder = InlineKeyboardBuilder()
    builder.button(text="💅 К услуге", callback_data=f"admin_svc:{service_id}")
    builder.button(text="◀ Список услуг", callback_data="admin:services")
    builder.adjust(1)

    if success and service:
        await message.answer(
            text=(
                "✅ <b>Услуга обновлена!</b>\n\n"
                f"💅 {service['name']}\n"
                f"⏱ {service['duration_min']} мин\n"
                f"💰 {service['price']} ₽"
            ),
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
    else:
        builder2 = InlineKeyboardBuilder()
        builder2.button(text="✏️ Попробовать снова", callback_data=f"admin_svc_edit:{service_id}")
        builder2.button(text="◀ К услуге", callback_data=f"admin_svc:{service_id}")
        builder2.adjust(1)
        await message.answer(
            text=(
                "❌ <b>Ошибка при сохранении</b>\n\n"
                "Возможно, услуга с таким названием уже существует."
            ),
            reply_markup=builder2.as_markup(),
            parse_mode="HTML",
        )


@router.message(AdminServiceStates.waiting_edit_price)
async def handle_admin_edit_price_invalid(message: Message):
    await message.answer(
        "❌ Введите цену числом, например: <code>1500</code>",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "edit_skip_price")
async def handle_admin_edit_price_skip(callback: CallbackQuery, state: FSMContext):
    """Шаг 3: пропустить изменение цены — применяем накопленные изменения."""
    await _apply_and_finish_edit(callback, state)


@router.callback_query(F.data == "edit_cancel")
async def handle_admin_edit_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена редактирования — возвращаемся на детали услуги."""
    await callback.answer("Редактирование отменено")
    data = await state.get_data()
    service_id = data.get("edit_service_id")
    await state.clear()

    if service_id:
        service = await db.get_service_by_id(service_id)
        if service:
            status_text = "✅ Активна" if service["is_active"] else "🔴 Скрыта"
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
            return

    # Фолбэк — список услуг
    services = await db.get_all_services(active_only=False)
    await callback.message.edit_text(
        text="💅 <b>Управление услугами</b>\n\nНажмите на услугу для управления:",
        reply_markup=get_admin_services_keyboard(services),
        parse_mode="HTML",
    )


# ===================================================
# 4. ПРОСМОТР БРОНИРОВАНИЙ
# ===================================================

@router.callback_query(F.data == "admin:bookings")
async def handle_admin_bookings(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()

    year, month = get_current_month_year()
    dates_with_bookings = await db.get_dates_with_bookings(year, month)

    await callback.message.edit_text(
        text=(
            "📋 <b>Бронирования</b>\n\n"
            "Выберите дату — увидите все записи на этот день.\n"
            "<i>📅 — на дату есть записи</i>"
        ),
        reply_markup=build_admin_bookings_calendar(year, month, dates_with_bookings),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_bk_cal_nav:"))
async def handle_admin_bk_cal_nav(callback: CallbackQuery):
    await callback.answer()

    _, year_str, month_str = callback.data.split(":")
    year, month = int(year_str), int(month_str)

    dates_with_bookings = await db.get_dates_with_bookings(year, month)

    await callback.message.edit_text(
        text=(
            "📋 <b>Бронирования</b>\n\n"
            "Выберите дату — увидите все записи на этот день.\n"
            "<i>📅 — на дату есть записи</i>"
        ),
        reply_markup=build_admin_bookings_calendar(year, month, dates_with_bookings),
        parse_mode="HTML",
    )


async def _show_bookings_for_date(message, date_str: str, edit: bool = False):
    """Показывает список бронирований на конкретную дату."""
    bookings = await db.get_all_bookings(date_filter=date_str)

    year = int(date_str[:4])
    month = int(date_str[5:7])
    back_cb = f"admin_bk_pick_date:{year}:{month}"

    builder = InlineKeyboardBuilder()

    if not bookings:
        builder.button(text="← Выбрать другую дату", callback_data=back_cb)
        text = (
            f"📋 <b>{format_date_ru(date_str)}</b>\n\n"
            "Записей на этот день нет."
        )
    else:
        status_icons = {"pending": "⏳", "confirmed": "✅", "cancelled": "❌"}
        for booking in bookings:
            time_str = format_time_ru(booking["booking_time"])
            icon = status_icons.get(booking["status"], "?")
            builder.button(
                text=f"{icon} {booking['full_name']} · {time_str}",
                callback_data=f"admin_bk_date_view:{booking['id']}"
            )
        builder.button(text="← Выбрать другую дату", callback_data=back_cb)
        builder.adjust(1)
        text = (
            f"📋 <b>{format_date_ru(date_str)}</b> — {len(bookings)} зап."
        )

    if edit:
        await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("admin_bk_cal_date:"))
async def handle_admin_bk_cal_date(callback: CallbackQuery):
    await callback.answer()

    date_str = callback.data.split(":", 1)[1]
    await _show_bookings_for_date(callback.message, date_str, edit=True)


@router.callback_query(F.data.startswith("admin_bk_pick_date:"))
async def handle_admin_bk_pick_date(callback: CallbackQuery):
    """Возврат к календарю бронирований на конкретный месяц."""
    await callback.answer()

    _, year_str, month_str = callback.data.split(":")
    year, month = int(year_str), int(month_str)

    dates_with_bookings = await db.get_dates_with_bookings(year, month)

    await callback.message.edit_text(
        text=(
            "📋 <b>Бронирования</b>\n\n"
            "Выберите дату — увидите все записи на этот день.\n"
            "<i>📅 — на дату есть записи</i>"
        ),
        reply_markup=build_admin_bookings_calendar(year, month, dates_with_bookings),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_bk_date_view:"))
async def handle_admin_bk_date_view(callback: CallbackQuery):
    """Открывает карточку бронирования с кнопкой возврата к списку за дату."""
    await callback.answer()

    # Формат: "admin_bk_date_view:{booking_uuid}" — дату берём из бронирования
    booking_id = callback.data.split(":", 1)[1]

    booking = await db.get_booking_by_id(booking_id)
    if not booking:
        await callback.answer("Бронирование не найдено", show_alert=True)
        return

    date_str = booking["booking_date"]  # YYYY-MM-DD из объекта бронирования

    await callback.message.edit_text(
        text=await _render_booking_detail(booking),
        reply_markup=get_admin_booking_actions_keyboard(
            booking_id,
            booking["status"],
            back_cb=f"admin_bk_cal_date:{date_str}",
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_bk_filter:"))
async def handle_admin_bookings_filter(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    filter_type = callback.data.split(":", 1)[1]

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

    await callback.message.edit_text(
        text=await _render_booking_detail(booking),
        reply_markup=get_admin_booking_actions_keyboard(
            booking_id, booking["status"],
            back_cb=f"admin_bk_cal_date:{booking['booking_date']}",
        ),
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
                text=await _render_booking_detail(booking),
                reply_markup=get_admin_booking_actions_keyboard(
                    booking_id, booking["status"],
                    back_cb=f"admin_bk_cal_date:{booking['booking_date']}",
                ),
                parse_mode="HTML",
            )
    else:
        await callback.answer("❌ Ошибка. Попробуйте ещё раз.", show_alert=True)


@router.callback_query(F.data.startswith("admin_bk_cancel:"))
async def handle_admin_booking_cancel_prompt(callback: CallbackQuery):
    """Показывает экран подтверждения отмены."""
    await callback.answer()

    booking_id = callback.data.split(":", 1)[1]

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, отменить", callback_data=f"admin_bk_cancel_do:{booking_id}")
    builder.button(text="← Нет, назад", callback_data=f"admin_bk_date_view:{booking_id}")
    builder.adjust(1)

    await callback.message.edit_text(
        text=(
            "⚠️ <b>Отменить запись?</b>\n\n"
            "Это действие нельзя отменить.\n"
            "Запись будет удалена, слот освобождён и снова станет доступен для записи."
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_bk_cancel_do:"))
async def handle_admin_booking_cancel_do(callback: CallbackQuery):
    """Выполняет фактическое удаление бронирования."""
    await callback.answer()

    booking_id = callback.data.split(":", 1)[1]

    booking = await db.get_booking_by_id(booking_id)
    if not booking:
        await callback.answer("Бронирование не найдено", show_alert=True)
        return

    date_str = booking["booking_date"]
    year, month = int(date_str[:4]), int(date_str[5:7])

    success = await db.delete_booking(booking_id)

    if success:
        await callback.answer("✅ Запись отменена. Слот освобождён.", show_alert=True)

        builder = InlineKeyboardBuilder()
        builder.button(text="← К записям за эту дату", callback_data=f"admin_bk_cal_date:{date_str}")
        builder.button(text="📅 Выбрать другую дату", callback_data=f"admin_bk_pick_date:{year}:{month}")
        builder.button(text="◀ Меню", callback_data="admin:main")
        builder.adjust(1)

        await callback.message.edit_text(
            text="✅ Запись отменена. Слот освобождён.",
            reply_markup=builder.as_markup(),
        )
    else:
        await callback.answer("❌ Ошибка. Попробуйте ещё раз.", show_alert=True)


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

    old_slot = await db.get_slot_by_date_time(booking["booking_date"], booking["booking_time"])

    await state.set_state(AdminRescheduleStates.waiting_new_date)
    await state.update_data(
        reschedule_booking_id=booking_id,
        reschedule_old_date=booking["booking_date"],
        reschedule_old_time=booking["booking_time"],
        reschedule_old_slot_id=old_slot["id"] if old_slot else None,
    )

    year, month = get_current_month_year()
    dates_with_slots = await db.get_dates_with_available_slots(year, month)

    await callback.message.edit_text(
        text=(
            f"📅 <b>Перенос бронирования</b>\n\n"
            f"Клиент: {booking['full_name']}\n"
            f"Текущая дата: {format_date_ru(booking['booking_date'])}, "
            f"{format_time_ru(booking['booking_time'])}\n\n"
            "Выберите <b>новую дату</b>:\n"
            "<i>📅 — есть свободные слоты</i>"
        ),
        reply_markup=build_admin_calendar(
            year, month, dates_with_slots,
            nav_prefix="admin_rs_cal_nav",
            date_prefix="admin_rs_cal_date",
        ),
        parse_mode="HTML",
    )


@router.callback_query(AdminRescheduleStates.waiting_new_date, F.data.startswith("admin_rs_cal_nav:"))
async def handle_admin_rs_cal_nav(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    _, year_str, month_str = callback.data.split(":")
    year, month = int(year_str), int(month_str)

    fsm_data = await state.get_data()
    booking = await db.get_booking_by_id(fsm_data["reschedule_booking_id"])

    dates_with_slots = await db.get_dates_with_available_slots(year, month)

    await callback.message.edit_text(
        text=(
            f"📅 <b>Перенос бронирования</b>\n\n"
            f"Клиент: {booking['full_name']}\n"
            f"Текущая дата: {format_date_ru(booking['booking_date'])}, "
            f"{format_time_ru(booking['booking_time'])}\n\n"
            "Выберите <b>новую дату</b>:\n"
            "<i>📅 — есть свободные слоты</i>"
        ),
        reply_markup=build_admin_calendar(
            year, month, dates_with_slots,
            nav_prefix="admin_rs_cal_nav",
            date_prefix="admin_rs_cal_date",
        ),
        parse_mode="HTML",
    )


@router.callback_query(AdminRescheduleStates.waiting_new_date, F.data.startswith("admin_rs_cal_date:"))
async def handle_admin_rs_cal_date(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]

    slots = await db.get_available_slots(date_str)

    if not slots:
        await callback.answer(
            f"На {format_date_ru(date_str)} нет свободных слотов. Выберите другую дату.",
            show_alert=True,
        )
        return

    await state.update_data(reschedule_new_date=date_str)
    await state.set_state(AdminRescheduleStates.waiting_new_time)

    await callback.message.edit_text(
        text=f"📅 Новая дата: <b>{format_date_ru(date_str)}</b>\n\n🕐 Выберите новое время:",
        reply_markup=build_time_slots_keyboard(slots),
        parse_mode="HTML",
    )


@router.callback_query(AdminRescheduleStates.waiting_new_time, F.data == "back_to_date")
async def handle_admin_rs_back_to_calendar(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору даты из выбора времени при переносе."""
    await callback.answer()
    fsm_data = await state.get_data()
    booking = await db.get_booking_by_id(fsm_data["reschedule_booking_id"])

    await state.set_state(AdminRescheduleStates.waiting_new_date)

    year, month = get_current_month_year()
    dates_with_slots = await db.get_dates_with_available_slots(year, month)

    await callback.message.edit_text(
        text=(
            f"📅 <b>Перенос бронирования</b>\n\n"
            f"Клиент: {booking['full_name']}\n"
            f"Текущая дата: {format_date_ru(booking['booking_date'])}, "
            f"{format_time_ru(booking['booking_time'])}\n\n"
            "Выберите <b>новую дату</b>:\n"
            "<i>📅 — есть свободные слоты</i>"
        ),
        reply_markup=build_admin_calendar(
            year, month, dates_with_slots,
            nav_prefix="admin_rs_cal_nav",
            date_prefix="admin_rs_cal_date",
        ),
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

    year, month = get_current_month_year()
    dates_with_slots = await db.get_dates_with_any_slots(year, month)

    await callback.message.edit_text(
        text="📅 <b>Добавить рабочий день</b>\n\nВыберите дату:\n📅 — уже есть слоты",
        reply_markup=build_admin_calendar(year, month, dates_with_slots),
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


# Catch-хендлер для нетекстовых сообщений на шаге даты (контексты bookings/view_slots)
@router.message(AdminSlotStates.waiting_date)
async def handle_admin_sched_date_invalid(message: Message):
    await message.answer(
        "❌ Введите дату текстом в формате <code>ДД.ММ.ГГГГ</code>",
        parse_mode="HTML",
    )


@router.callback_query(AdminSlotStates.waiting_date, F.data.startswith("admin_cal_nav:"))
async def handle_admin_cal_nav(callback: CallbackQuery, state: FSMContext):
    """Навигация по месяцам в админском календаре."""
    await callback.answer()
    _, year_str, month_str = callback.data.split(":")
    year, month = int(year_str), int(month_str)

    dates_with_slots = await db.get_dates_with_any_slots(year, month)

    await callback.message.edit_text(
        text="📅 <b>Добавить рабочий день</b>\n\nВыберите дату:\n📅 — уже есть слоты",
        reply_markup=build_admin_calendar(year, month, dates_with_slots),
        parse_mode="HTML",
    )


@router.callback_query(AdminSlotStates.waiting_date, F.data.startswith("admin_cal_date:"))
async def handle_admin_cal_date(callback: CallbackQuery, state: FSMContext):
    """Выбор даты в админском календаре — переход к выбору временных слотов."""
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]  # "YYYY-MM-DD"

    await state.update_data(sched_date=date_str)
    await state.set_state(AdminSlotStates.waiting_time)

    await callback.message.edit_text(
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


# ===================================================
# 9. УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ
# ===================================================


async def _resolve_owner_id() -> Optional[int]:
    # Возвращает актуальный Telegram ID владельца:
    # 1. Сначала смотрит в БД (role='owner') — источник правды после передачи.
    # 2. Если в БД нет — берёт из .env (OWNER_ID или первый ADMIN_IDS).
    db_owner = await db.get_db_owner_id()
    if db_owner:
        return db_owner
    return settings.get_owner_id()


async def _show_admins_menu(
    target: Message,
    edit: bool = False,
    viewer_id: Optional[int] = None,
) -> None:
    # Отображает экран управления администраторами.
    # Список всех администраторов:
    #   • Владелец: помечается 👑, кнопок управления нет
    #   • Обычные admin из БД: кнопка 🗑 (только для viewer=owner)
    #   • Env-admins (без записи в БД): отображаются только в тексте
    # Управляющие кнопки видит только владелец.
    db_admins = await db.get_all_admins()
    owner_id = await _resolve_owner_id()
    env_ids = settings.get_admin_ids()

    # Bootstrap: если владелец ещё не в БД — добавляем автоматически
    if owner_id and not any(a["telegram_id"] == owner_id for a in db_admins):
        username = await db.get_username_by_user_id(owner_id)
        await db.ensure_owner_in_db(owner_id, username)
        _invalidate_admin_cache()
        db_admins = await db.get_all_admins()

    db_admin_map = {a["telegram_id"]: a for a in db_admins}

    # Строим единый список: env первыми, затем из БД без дублей
    all_ids = list(dict.fromkeys(env_ids + [a["telegram_id"] for a in db_admins]))

    lines = ["👥 <b>Администраторы NailStory</b>\n"]

    if not all_ids:
        lines.append("Список пуст.")
    else:
        for tid in all_ids:
            full_name, uname = await db.get_user_display_info(tid)
            if not uname and tid in db_admin_map:
                uname = db_admin_map[tid].get("username")

            if full_name and uname:
                label = f"{full_name} (@{uname})"
            elif full_name:
                label = f"{full_name} (ID {tid})"
            elif uname:
                label = f"@{uname}"
            else:
                label = f"ID {tid}"

            if tid == owner_id:
                lines.append(f"  👑 {label} — <b>владелец</b>")
            else:
                lines.append(f"  • {label}")

    is_owner = (viewer_id is not None and viewer_id == owner_id)
    if is_owner and len(db_admins) > 1:
        lines.append("\nНажмите на администратора чтобы удалить:")

    text = "\n".join(lines)
    kb = get_admin_admins_keyboard(db_admins, owner_id=owner_id, viewer_id=viewer_id)

    if edit:
        await target.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
    else:
        await target.answer(text=text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "admin:admins")
async def handle_admin_admins(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await _show_admins_menu(callback.message, edit=True, viewer_id=callback.from_user.id)


# -------------------------------------------------------
# Добавление администратора (только владелец)
# -------------------------------------------------------

@router.callback_query(F.data == "admin_mgmt:add")
async def handle_admin_mgmt_add(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    owner_id = await _resolve_owner_id()
    if callback.from_user.id != owner_id:
        await callback.answer("⛔ Только владелец может добавлять администраторов", show_alert=True)
        return

    await state.set_state(AdminMgmtStates.waiting_new_admin_id)

    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="admin:admins")

    await callback.message.edit_text(
        text=(
            "👥 <b>Добавление администратора</b>\n\n"
            "Введите <b>@юзернейм</b> или <b>числовой Telegram ID</b> нового администратора.\n\n"
            "💡 <i>По юзернейму поиск работает, только если пользователь уже записывался через бот.\n"
            "Если не найден — попросите прислать Telegram ID "
            "(можно узнать у бота @userinfobot) и введите число.</i>"
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.message(AdminMgmtStates.waiting_new_admin_id, F.text)
async def handle_admin_mgmt_username_input(message: Message, state: FSMContext):
    raw = message.text.strip()
    clean = raw.lstrip("@").strip()

    if not clean:
        builder = InlineKeyboardBuilder()
        builder.button(text="❌ Отмена", callback_data="admin:admins")
        await message.answer(
            "❌ Введите @юзернейм или числовой Telegram ID",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        return

    user_id: Optional[int] = None
    username: Optional[str] = None

    if clean.isdigit():
        user_id = int(clean)
        username = await db.get_username_by_user_id(user_id)
    else:
        username = clean
        user_id = await db.find_user_id_by_username(username)

        if user_id is None:
            builder = InlineKeyboardBuilder()
            builder.button(text="❌ Отмена", callback_data="admin:admins")
            await message.answer(
                f"❌ Пользователь @{username} не найден в системе.\n\n"
                "Этот способ работает, только если пользователь уже записывался через бот.\n\n"
                "Попросите его прислать Telegram ID "
                "(можно узнать у бота @userinfobot) и введите число.",
                reply_markup=builder.as_markup(),
            )
            return

    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="◀ К администраторам", callback_data="admin:admins")

    display = f"@{username}" if username else f"ID {user_id}"

    owner_id = await _resolve_owner_id()
    if user_id == owner_id:
        await message.answer(
            f"ℹ️ {display} уже является владельцем.",
            reply_markup=builder.as_markup(),
        )
        return

    db_admins = await db.get_all_admins()
    already = any(a["telegram_id"] == user_id for a in db_admins)
    if already:
        await message.answer(
            f"ℹ️ {display} уже является администратором.",
            reply_markup=builder.as_markup(),
        )
        return

    ok = await db.add_admin(telegram_id=user_id, username=username, role="admin")

    if ok:
        _invalidate_admin_cache()
        await message.answer(
            f"✅ Администратор {display} добавлен.",
            reply_markup=builder.as_markup(),
        )
    else:
        await message.answer(
            "❌ Не удалось добавить администратора. Попробуйте ещё раз.",
            reply_markup=builder.as_markup(),
        )


@router.message(AdminMgmtStates.waiting_new_admin_id)
async def handle_admin_mgmt_username_input_invalid(message: Message):
    await message.answer(
        "❌ Введите @юзернейм, например: <code>@manager</code>",
        parse_mode="HTML",
    )


# -------------------------------------------------------
# Удаление администратора (только владелец)
# -------------------------------------------------------

@router.callback_query(F.data.startswith("admin_mgmt:remove:"))
async def handle_admin_mgmt_remove(callback: CallbackQuery):
    await callback.answer()

    owner_id = await _resolve_owner_id()
    viewer_id = callback.from_user.id

    if viewer_id != owner_id:
        await callback.answer("⛔ Только владелец может удалять администраторов", show_alert=True)
        return

    telegram_id = int(callback.data.split(":")[-1])

    if telegram_id == owner_id:
        await callback.answer("⛔ Владелец не может быть удалён", show_alert=True)
        return

    db_admins = await db.get_all_admins()
    admin_rec = next((a for a in db_admins if a["telegram_id"] == telegram_id), None)
    display = f"@{admin_rec['username']}" if admin_rec and admin_rec.get("username") else f"ID {telegram_id}"

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, удалить", callback_data=f"admin_mgmt:confirm_remove:{telegram_id}")
    builder.button(text="❌ Отмена", callback_data="admin:admins")
    builder.adjust(1)

    await callback.message.edit_text(
        text=f"⚠️ Удалить администратора <b>{display}</b>?",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_mgmt:confirm_remove:"))
async def handle_admin_mgmt_confirm_remove(callback: CallbackQuery):
    await callback.answer()

    owner_id = await _resolve_owner_id()

    if callback.from_user.id != owner_id:
        await callback.answer("⛔ Только владелец может удалять администраторов", show_alert=True)
        return

    telegram_id = int(callback.data.split(":")[-1])

    if telegram_id == owner_id:
        await callback.answer("⛔ Владелец не может быть удалён", show_alert=True)
        return

    ok = await db.remove_admin(telegram_id)
    if ok:
        _invalidate_admin_cache()

    await _show_admins_menu(callback.message, edit=True, viewer_id=callback.from_user.id)


# -------------------------------------------------------
# Передача владения (только владелец)
# -------------------------------------------------------

@router.callback_query(F.data == "admin_mgmt:transfer")
async def handle_admin_mgmt_transfer(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    owner_id = await _resolve_owner_id()
    if callback.from_user.id != owner_id:
        await callback.answer("⛔ Только владелец может передать владение", show_alert=True)
        return

    db_admins = await db.get_all_admins()
    candidates = [a for a in db_admins if a["telegram_id"] != owner_id]

    if not candidates:
        await callback.answer("Нет администраторов для передачи владения", show_alert=True)
        return

    await state.set_state(AdminMgmtStates.waiting_transfer_target)

    await callback.message.edit_text(
        text=(
            "🔄 <b>Передача владения</b>\n\n"
            "Выберите администратора, которому хотите передать статус владельца.\n\n"
            "⚠️ <i>После передачи вы станете обычным администратором.\n"
            "Отменить это действие сможет только новый владелец.</i>"
        ),
        reply_markup=get_admin_transfer_keyboard(db_admins, owner_id=owner_id),
        parse_mode="HTML",
    )


@router.callback_query(
    AdminMgmtStates.waiting_transfer_target,
    F.data.startswith("admin_mgmt:transfer_to:"),
)
async def handle_admin_mgmt_transfer_confirm_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    new_owner_id = int(callback.data.split(":")[-1])
    await state.update_data(new_owner_id=new_owner_id)

    db_admins = await db.get_all_admins()
    admin_rec = next((a for a in db_admins if a["telegram_id"] == new_owner_id), None)
    display = f"@{admin_rec['username']}" if admin_rec and admin_rec.get("username") else f"ID {new_owner_id}"

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, передать", callback_data=f"admin_mgmt:confirm_transfer:{new_owner_id}")
    builder.button(text="❌ Отмена", callback_data="admin:admins")
    builder.adjust(1)

    await callback.message.edit_text(
        text=(
            f"🔄 Передать владение пользователю <b>{display}</b>?\n\n"
            "После подтверждения вы станете обычным администратором."
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_mgmt:confirm_transfer:"))
async def handle_admin_mgmt_confirm_transfer(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()

    old_owner_id = callback.from_user.id
    new_owner_id = int(callback.data.split(":")[-1])

    current_owner = await _resolve_owner_id()
    if old_owner_id != current_owner:
        await callback.answer("⛔ Только владелец может передать владение", show_alert=True)
        return

    ok = await db.transfer_ownership(old_owner_id=old_owner_id, new_owner_id=new_owner_id)
    _invalidate_admin_cache()

    builder = InlineKeyboardBuilder()
    if ok:
        db_admins = await db.get_all_admins()
        admin_rec = next((a for a in db_admins if a["telegram_id"] == new_owner_id), None)
        display = f"@{admin_rec['username']}" if admin_rec and admin_rec.get("username") else f"ID {new_owner_id}"

        builder.button(text="◀ К администраторам", callback_data="admin:admins")
        await callback.message.edit_text(
            f"✅ Владение передано {display}.\nВы теперь обычный администратор.",
            reply_markup=builder.as_markup(),
        )
    else:
        builder.button(text="◀ Назад", callback_data="admin:admins")
        await callback.message.edit_text(
            "❌ Не удалось передать владение. Попробуйте ещё раз.",
            reply_markup=builder.as_markup(),
        )
