# ===================================================
# handlers/admin.py — Полная административная панель
# ===================================================

import logging
import calendar as cal_module
from datetime import date
from aiogram import Router, F, BaseMiddleware
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, TelegramObject, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import Callable, Dict, Any, Awaitable, Optional, Set

from bot.config import settings
from bot.states import (
    AdminServiceStates, AdminSlotStates, AdminRescheduleStates,
    AdminBookingStates, AdminMgmtStates,
    AdminScheduleRuleStates, AdminScheduleEditStates, AdminDefaultScheduleStates,
    AdminScheduleModeStates, AdminHourGridStates,
)
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
    get_schedule_mode_choice_keyboard,
    get_hour_grid_keyboard,
    get_admin_time_slots_keyboard,
    get_admin_slots_list_keyboard,
    get_admin_admins_keyboard,
    get_admin_transfer_keyboard,
    get_weekday_keyboard,
    get_hour_keyboard,
    get_slot_edit_keyboard,
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
from bot.utils.calendar import (
    build_time_slots_keyboard, build_admin_calendar,
    build_admin_bookings_calendar, build_admin_multiselect_calendar,
    get_current_month_year, MONTHS_RU,
)
from bot import database as db

logger = logging.getLogger(__name__)

BOOKINGS_PER_PAGE = 8


def _fmt_end_hour(h: int) -> str:
    """Форматирует конечный час расписания. end_hour=0 означает полночь (24:00)."""
    return "24:00" if h == 0 else f"{h:02d}:00"


def _fmt_schedule_range(start_h: int, end_h: int) -> str:
    """Форматирует диапазон рабочих часов. end_hour=0 → 24:00."""
    return f"{start_h:02d}:00–{_fmt_end_hour(end_h)}"


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


@router.callback_query(
    StateFilter(AdminRescheduleStates.waiting_new_date, AdminRescheduleStates.waiting_confirm),
    F.data.startswith("admin_rs_cal_date:"),
)
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
    """Выбрано время — показываем экран подтверждения переноса."""
    await callback.answer()

    parts = callback.data.split(":")
    new_slot_id = parts[1]
    new_time = f"{parts[2]}:{parts[3]}:00"

    fsm_data = await state.get_data()
    await state.update_data(reschedule_new_slot_id=new_slot_id, reschedule_new_time=new_time)
    await state.set_state(AdminRescheduleStates.waiting_confirm)

    booking = await db.get_booking_by_id(fsm_data["reschedule_booking_id"])
    new_date = fsm_data["reschedule_new_date"]

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, перенести", callback_data="admin_rs_confirm")
    builder.button(
        text="← Нет, назад к выбору времени",
        callback_data=f"admin_rs_cal_date:{new_date}",
    )
    builder.adjust(1)

    await callback.message.edit_text(
        text=(
            "📅 <b>Подтвердите перенос</b>\n\n"
            f"Клиент: {booking['full_name']}\n"
            f"Было: {format_date_ru(booking['booking_date'])}, "
            f"{format_time_ru(booking['booking_time'])}\n"
            f"Станет: <b>{format_date_ru(new_date)}, {format_time_ru(new_time)}</b>\n\n"
            "Это действие нельзя отменить. Запись будет перенесена, "
            "старый слот освободится и станет доступен для записи."
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(AdminRescheduleStates.waiting_confirm, F.data == "admin_rs_confirm")
async def handle_admin_reschedule_confirm(callback: CallbackQuery, state: FSMContext):
    """Выполняет фактический перенос после подтверждения."""
    await callback.answer()

    fsm_data = await state.get_data()
    await state.clear()

    success = await db.reschedule_booking(
        booking_id=fsm_data["reschedule_booking_id"],
        old_slot_id=fsm_data.get("reschedule_old_slot_id") or "",
        new_slot_id=fsm_data["reschedule_new_slot_id"],
        new_date=fsm_data["reschedule_new_date"],
        new_time=fsm_data["reschedule_new_time"],
    )

    builder = InlineKeyboardBuilder()
    builder.button(
        text="📋 К бронированию",
        callback_data=f"admin_bk_view:{fsm_data['reschedule_booking_id']}",
    )
    builder.button(text="◀ Меню", callback_data="admin:main")
    builder.adjust(1)

    if success:
        await callback.message.edit_text(
            text=(
                "✅ <b>Бронирование перенесено!</b>\n\n"
                f"Новая дата: <b>{format_date_ru(fsm_data['reschedule_new_date'])}</b>\n"
                f"Новое время: <b>{fsm_data['reschedule_new_time'][:5]}</b>"
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

async def _show_schedule_view_calendar(
    message, year: int, month: int, mode: str = None, edit: bool = True
):
    """
    Главная страница расписания: календарь + кнопки управления ниже.
    mode: "standard" | "monthly" — определяет набор кнопок.
    Все будущие дни кликабельны.
    """
    if mode is None:
        mode = await db.get_setting("schedule_mode") or "monthly"

    # В стандартном режиме автоподкидываем слоты при открытии
    if mode == "standard":
        rule = await db.get_default_schedule()
        if rule:
            await db.apply_default_schedule_for_months(24)

    dates_with_slots = await db.get_dates_with_any_slots(year, month)
    kb = build_admin_calendar(
        year, month, dates_with_slots,
        nav_prefix=f"admin_sched_vnav:{mode}",
        date_prefix="admin_sched_view_date",
    )

    # Режимные кнопки
    if mode == "standard":
        rule = await db.get_default_schedule()
        if rule:
            wd_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
            wd_list = " ".join(n for i, n in enumerate(wd_names) if rule["weekdays_mask"] & (1 << i))
            standard_label = (
                f"⚙️ Стандарт: {wd_list} · "
                f"{_fmt_schedule_range(rule['start_hour'], rule['end_hour'])} · {rule['interval_min']} мин"
            )
            kb.inline_keyboard.append(
                [InlineKeyboardButton(text=standard_label, callback_data="admin:default_schedule")]
            )
        else:
            kb.inline_keyboard.append(
                [InlineKeyboardButton(text="⚙️ Задать стандартное расписание", callback_data="admin:default_schedule")]
            )
    else:  # monthly
        kb.inline_keyboard.append(
            [InlineKeyboardButton(text="📅 Создать расписание на месяц", callback_data="admin:schedule_rule")]
        )

    kb.inline_keyboard.extend([
        [InlineKeyboardButton(text="🔄 Сменить режим", callback_data="sched_mode:change")],
        [InlineKeyboardButton(text="◀ Главное меню", callback_data="admin:main")],
    ])

    hint = "📌 <i>Нажмите на день для просмотра или редактирования</i>"
    text = f"📅 <b>Расписание</b>\n\n{hint}"
    if edit:
        await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "admin:schedule")
async def handle_admin_schedule(callback: CallbackQuery, state: FSMContext):
    """Точка входа в расписание. Если режим не выбран — показывает выбор."""
    await callback.answer()
    await state.clear()

    mode = await db.get_setting("schedule_mode")
    if not mode:
        await callback.message.edit_text(
            "📅 <b>Управление расписанием</b>\n\n"
            "Как вы хотите управлять расписанием?\n\n"
            "<b>Стандартное</b> — задаёте правило один раз (дни недели + часы), "
            "бот автоматически создаёт слоты на 24 месяца вперёд.\n\n"
            "<b>По месяцам</b> — составляете расписание вручную на каждый месяц.",
            reply_markup=get_schedule_mode_choice_keyboard(),
            parse_mode="HTML",
        )
        return

    year, month = get_current_month_year()
    await _show_schedule_view_calendar(callback.message, year, month, mode=mode)


@router.callback_query(F.data.startswith("sched_mode:"))
async def handle_sched_mode_choice(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор или смену режима расписания."""
    await callback.answer()
    action = callback.data.split(":", 1)[1]

    if action == "change":
        current = await db.get_setting("schedule_mode") or "не задан"
        labels = {"standard": "стандартное", "monthly": "по месяцам"}
        builder = InlineKeyboardBuilder()
        builder.button(text="📋 Стандартное расписание", callback_data="sched_mode:standard")
        builder.button(text="🗓 По месяцам вручную", callback_data="sched_mode:monthly")
        builder.button(text="← Назад", callback_data="admin:schedule")
        builder.adjust(1)
        await callback.message.edit_text(
            f"🔄 <b>Смена режима расписания</b>\n\n"
            f"Текущий режим: <b>{labels.get(current, current)}</b>\n\n"
            "⚠️ При смене режима все будущие слоты (кроме созданных вручную) "
            "будут удалены и пересозданы по новому правилу.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        return

    current_mode = await db.get_setting("schedule_mode")

    if action == "standard":
        await db.set_setting("schedule_mode", "standard")
        if current_mode != "standard":
            await callback.message.edit_text("⏳ Очищаю слоты и пересчитываю...", parse_mode="HTML")
            await db.clear_non_custom_future_slots()
        rule = await db.get_default_schedule()
        if not rule:
            # Нет стандарта — запускаем мастер настройки
            await state.set_state(AdminDefaultScheduleStates.waiting_weekdays)
            await state.update_data(default_weekdays=set())
            await callback.message.edit_text(
                "⚙️ <b>Стандартное расписание</b>\n\n"
                "Шаг 1 из 4 — Выберите <b>рабочие дни</b>:",
                reply_markup=get_weekday_keyboard(set(), cancel_cb="admin:schedule"),
                parse_mode="HTML",
            )
            return
        # Есть правило — регенерируем слоты
        await db.reset_default_schedule_slots()
        year, month = get_current_month_year()
        await _show_schedule_view_calendar(callback.message, year, month, mode="standard")

    elif action == "monthly":
        await db.set_setting("schedule_mode", "monthly")
        if current_mode != "monthly":
            await callback.message.edit_text("⏳ Очищаю слоты...", parse_mode="HTML")
            await db.clear_non_custom_future_slots()
        year, month = get_current_month_year()
        await _show_schedule_view_calendar(callback.message, year, month, mode="monthly")


@router.callback_query(F.data.startswith("admin_sched_vnav:"))
async def handle_admin_sched_view_nav(callback: CallbackQuery):
    """Навигация по месяцам в главном виде расписания."""
    await callback.answer()
    parts = callback.data.split(":")
    # Формат: admin_sched_vnav:{mode}:{year}:{month}
    mode = parts[1]
    year_str, month_str = parts[2], parts[3]
    await _show_schedule_view_calendar(
        callback.message, int(year_str), int(month_str), mode=mode
    )


@router.callback_query(F.data.startswith("admin_sched_view_date:"))
async def handle_admin_sched_view_date(callback: CallbackQuery, state: FSMContext):
    """Клик на день в просмотре расписания — показывает режим работы."""
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]

    slots = await db.get_all_slots_for_date(date_str)
    info = await db.get_day_schedule_info(date_str)
    year, month = int(date_str[:4]), int(date_str[5:7])

    builder = InlineKeyboardBuilder()
    if slots:
        free = sum(1 for s in slots if s["is_available"])
        booked = len(slots) - free
        info_str = ""
        if info:
            info_str = (
                f"\n🕐 <b>{info['start']} – {info['end_exclusive']}</b>\n"
                f"⏱ Интервал: {info['interval_min']} мин\n"
            )
        text = (
            f"📅 <b>{format_date_ru(date_str)}</b>"
            f"{info_str}\n"
            f"Слотов: {len(slots)} (свободных: {free}, занято: {booked})"
        )
        builder.button(text="✏️ Редактировать часы", callback_data=f"admin_sched_edit_day:{date_str}")
    else:
        text = f"📅 <b>{format_date_ru(date_str)}</b>\n\nРабочий день не создан."
        builder.button(text="➕ Создать рабочий день", callback_data=f"admin_sched_create_day:{date_str}")

    builder.button(text="← К расписанию", callback_data="admin:schedule")
    builder.button(text="◀ Главное меню", callback_data="admin:main")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


async def _show_hour_grid(message, date_str: str, state: FSMContext, is_new_day: bool = False):
    """Показывает сетку 24 часов для редактирования рабочего дня."""
    fsm = await state.get_data()
    active_hours = set(fsm.get("hgrid_active", []))
    interval_min = fsm.get("hgrid_interval", 60)
    info = await db.get_day_schedule_info(date_str)

    if info:
        time_hint = f"🕐 {info['start']} – {info['end_exclusive']} · {info['interval_min']} мин\n"
    else:
        time_hint = ""

    action = "новый день" if is_new_day else "редактирование"
    await message.edit_text(
        text=(
            f"📅 <b>{format_date_ru(date_str)}</b> — {action}\n\n"
            f"{time_hint}"
            "Выберите рабочие часы (✅ — включён, ⬜ — выключен):"
        ),
        reply_markup=get_hour_grid_keyboard(date_str, active_hours, interval_min, is_new_day),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_sched_edit_day:"))
async def handle_admin_sched_edit_day(callback: CallbackQuery, state: FSMContext):
    """Из просмотра дня → сетка часов для редактирования."""
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]

    active_hours = await db.get_active_hours_for_date(date_str)
    info = await db.get_day_schedule_info(date_str)
    interval_min = info["interval_min"] if info else 60

    await state.set_state(AdminHourGridStates.editing)
    await state.update_data(
        hgrid_date=date_str,
        hgrid_active=list(active_hours),
        hgrid_interval=interval_min,
        hgrid_original=list(active_hours),
    )
    await _show_hour_grid(callback.message, date_str, state, is_new_day=False)


@router.callback_query(F.data.startswith("admin_sched_create_day:"))
async def handle_admin_sched_create_day(callback: CallbackQuery, state: FSMContext):
    """Из просмотра пустого дня → сетка часов для нового дня."""
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]

    rule = await db.get_default_schedule()
    # Предзаполняем часы по стандарту (если есть), иначе пусто
    if rule:
        s, e = rule["start_hour"], rule["end_hour"]
        interval_min = rule["interval_min"]
        if e == 0:
            active_hours = set(range(s, 24))
        else:
            active_hours = set(range(s, e))
    else:
        active_hours = set()
        interval_min = 60

    await state.set_state(AdminHourGridStates.editing)
    await state.update_data(
        hgrid_date=date_str,
        hgrid_active=list(active_hours),
        hgrid_interval=interval_min,
        hgrid_original=[],
    )
    await _show_hour_grid(callback.message, date_str, state, is_new_day=True)


@router.callback_query(AdminHourGridStates.editing, F.data.startswith("hgrid_toggle:"))
async def handle_hgrid_toggle(callback: CallbackQuery, state: FSMContext):
    """Тоггл часа в сетке."""
    await callback.answer()
    parts = callback.data.split(":")
    date_str = parts[1]
    hour = int(parts[2])

    fsm = await state.get_data()
    active = set(fsm.get("hgrid_active", []))
    if hour in active:
        active.discard(hour)
    else:
        active.add(hour)
    await state.update_data(hgrid_active=list(active))
    await _show_hour_grid(callback.message, date_str, state, is_new_day=not fsm.get("hgrid_original"))


@router.callback_query(AdminHourGridStates.editing, F.data.startswith("hgrid_interval:"))
async def handle_hgrid_interval(callback: CallbackQuery, state: FSMContext):
    """Смена интервала в сетке."""
    await callback.answer()
    parts = callback.data.split(":")
    date_str = parts[1]
    interval_min = int(parts[2])

    fsm = await state.get_data()
    await state.update_data(hgrid_interval=interval_min)
    await _show_hour_grid(callback.message, date_str, state, is_new_day=not fsm.get("hgrid_original"))


@router.callback_query(AdminHourGridStates.editing, F.data.startswith("hgrid_save:"))
async def handle_hgrid_save(callback: CallbackQuery, state: FSMContext):
    """Сохранить изменения из сетки часов."""
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]

    fsm = await state.get_data()
    new_hours = set(fsm.get("hgrid_active", []))
    original_hours = set(fsm.get("hgrid_original", []))
    interval_min = fsm.get("hgrid_interval", 60)

    if not new_hours:
        await callback.answer("⚠️ Нужно выбрать хотя бы один час.", show_alert=True)
        return

    # Часы для удаления (были, теперь нет)
    hours_to_delete = original_hours - new_hours
    # Часы для добавления (не было, теперь есть)
    hours_to_add = new_hours - original_hours

    deleted = 0
    created = 0

    if hours_to_delete:
        deleted = await db.delete_slots_in_hours(date_str, hours_to_delete)

    if hours_to_add:
        # Создаём слоты для каждого нового часа
        for h in sorted(hours_to_add):
            start_time = f"{h:02d}:00"
            end_time = f"{(h + 1) % 24:02d}:00" if h < 23 else "00:00"
            result = await db.bulk_create_slots([date_str], start_time, end_time, interval_min)
            created += result.get("created", 0)

    # Если интервал изменился для существующих часов, пересоздаём их
    if not hours_to_delete and not hours_to_add and interval_min != (
        (await db.get_day_schedule_info(date_str) or {}).get("interval_min", interval_min)
    ):
        # Интервал изменился — удалить и пересоздать все незанятые слоты
        hours_with_free = set()
        all_slots = await db.get_all_slots_for_date(date_str)
        for s in all_slots:
            if s["is_available"]:
                hours_with_free.add(int(s["slot_time"][:2]))
        deleted += await db.delete_slots_in_hours(date_str, hours_with_free)
        for h in sorted(new_hours):
            start_time = f"{h:02d}:00"
            end_time = f"{(h + 1) % 24:02d}:00" if h < 23 else "00:00"
            result = await db.bulk_create_slots([date_str], start_time, end_time, interval_min)
            created += result.get("created", 0)

    await db.add_custom_day(date_str)
    await state.clear()

    year, month = int(date_str[:4]), int(date_str[5:7])
    await callback.answer(
        f"✅ Сохранено: +{created} слотов, -{deleted} удалено",
        show_alert=True,
    )
    await _show_schedule_view_calendar(callback.message, year, month)


@router.callback_query(AdminHourGridStates.editing, F.data.startswith("hgrid_delete:"))
async def handle_hgrid_delete(callback: CallbackQuery, state: FSMContext):
    """Удалить весь рабочий день из сетки."""
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]

    slots = await db.get_all_slots_for_date(date_str)
    booked = [s for s in slots if not s["is_available"]]
    if booked:
        await callback.answer(
            f"❌ Нельзя удалить: есть {len(booked)} забронированных записей.",
            show_alert=True,
        )
        return

    # Удаляем все слоты
    for s in slots:
        await db.delete_slot_by_id(s["id"])

    await db.add_custom_day(date_str)
    await state.clear()

    year, month = int(date_str[:4]), int(date_str[5:7])
    await callback.answer("✅ День удалён.", show_alert=True)
    await _show_schedule_view_calendar(callback.message, year, month)


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


# ===================================================
# 10. ГЕНЕРАТОР РАСПИСАНИЯ ПО ПРАВИЛУ
# ===================================================

@router.callback_query(F.data == "admin:schedule_rule")
async def handle_admin_schedule_rule(callback: CallbackQuery, state: FSMContext):
    """Точка входа. Шаг 1 — выбор дней недели."""
    await callback.answer()
    await state.set_state(AdminScheduleRuleStates.waiting_weekdays)
    await state.update_data(rule_weekdays=[])

    await callback.message.edit_text(
        text=(
            "📅 <b>Создать расписание на месяц</b>\n\n"
            "Шаг 1 из 4 — Выберите <b>рабочие дни</b>:\n"
            "<i>Нажмите на день, чтобы выбрать/снять выбор</i>"
        ),
        reply_markup=get_weekday_keyboard(set()),
        parse_mode="HTML",
    )


@router.callback_query(AdminScheduleRuleStates.waiting_weekdays, F.data.startswith("rule_wd:"))
async def handle_weekday_toggle(callback: CallbackQuery, state: FSMContext):
    """Переключить выбранный день недели."""
    await callback.answer()
    wd = int(callback.data.split(":")[1])
    fsm = await state.get_data()
    selected = set(fsm.get("rule_weekdays", []))
    if wd in selected:
        selected.discard(wd)
    else:
        selected.add(wd)
    await state.update_data(rule_weekdays=list(selected))
    await callback.message.edit_reply_markup(reply_markup=get_weekday_keyboard(selected))


@router.callback_query(AdminScheduleRuleStates.waiting_weekdays, F.data == "rule_wd_done")
async def handle_weekday_done(callback: CallbackQuery, state: FSMContext):
    """Подтверждение дней, шаг 2 — выбор времени начала."""
    fsm = await state.get_data()
    selected = set(fsm.get("rule_weekdays", []))
    if not selected:
        await callback.answer("Выберите хотя бы один день!", show_alert=True)
        return
    await callback.answer()
    await state.set_state(AdminScheduleRuleStates.waiting_start_time)

    await callback.message.edit_text(
        text=(
            "📅 <b>Создать расписание на месяц</b>\n\n"
            "Шаг 2 из 4 — Выберите <b>время начала</b> рабочего дня:"
        ),
        reply_markup=get_hour_keyboard(list(range(0, 24)), "rule_start", "admin:schedule_rule"),
        parse_mode="HTML",
    )


@router.callback_query(AdminScheduleRuleStates.waiting_start_time, F.data.startswith("rule_start:"))
async def handle_rule_start_time(callback: CallbackQuery, state: FSMContext):
    """Записать время начала, шаг 3 — время окончания."""
    await callback.answer()
    hour = int(callback.data.split(":")[1])
    await state.update_data(rule_start_hour=hour)
    await state.set_state(AdminScheduleRuleStates.waiting_end_time)

    await callback.message.edit_text(
        text=(
            "📅 <b>Создать расписание на месяц</b>\n\n"
            f"Начало: <b>{hour:02d}:00</b>\n\n"
            "Шаг 3 из 4 — Выберите <b>время окончания</b> рабочего дня:"
        ),
        reply_markup=get_hour_keyboard(
            list(range(hour + 1, 24)) + ([0] if hour > 0 else []),
            "rule_end", "admin:schedule_rule",
            special_labels={0: "00 (полночь)"},
        ),
        parse_mode="HTML",
    )


@router.callback_query(AdminScheduleRuleStates.waiting_end_time, F.data.startswith("rule_end:"))
async def handle_rule_end_time(callback: CallbackQuery, state: FSMContext):
    """Записать время окончания, шаг 4 — выбор интервала."""
    await callback.answer()
    hour = int(callback.data.split(":")[1])
    await state.update_data(rule_end_hour=hour)
    await state.set_state(AdminScheduleRuleStates.waiting_interval)

    fsm = await state.get_data()
    start_hour = fsm["rule_start_hour"]

    builder = InlineKeyboardBuilder()
    builder.button(text="⏱ 15 минут", callback_data="rule_interval:15")
    builder.button(text="⏱ 30 минут", callback_data="rule_interval:30")
    builder.button(text="⏱ 1 час", callback_data="rule_interval:60")
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="← Назад", callback_data="admin:schedule_rule"))

    await callback.message.edit_text(
        text=(
            "📅 <b>Создать расписание на месяц</b>\n\n"
            f"Начало: <b>{start_hour:02d}:00</b> — Конец: <b>{hour:02d}:00</b>\n\n"
            "Шаг 4 из 4 — Выберите <b>интервал</b> между записями:"
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(AdminScheduleRuleStates.waiting_interval, F.data.startswith("rule_interval:"))
async def handle_rule_interval(callback: CallbackQuery, state: FSMContext):
    """Запускает генерацию слотов и показывает результат."""
    await callback.answer()
    interval_min = int(callback.data.split(":")[1])
    fsm = await state.get_data()
    await state.clear()

    today = date.today()
    year, month = today.year, today.month
    last_day = cal_module.monthrange(year, month)[1]

    weekdays = set(fsm.get("rule_weekdays", []))
    start_hour = fsm["rule_start_hour"]
    end_hour = fsm["rule_end_hour"]

    dates = [
        date(year, month, d).strftime("%Y-%m-%d")
        for d in range(today.day, last_day + 1)
        if date(year, month, d).weekday() in weekdays
    ]

    if not dates:
        builder = InlineKeyboardBuilder()
        builder.button(text="← Расписание", callback_data="admin:schedule")
        await callback.message.edit_text(
            "😔 В оставшейся части месяца нет подходящих рабочих дней.\n"
            "Попробуйте выбрать другие дни недели.",
            reply_markup=builder.as_markup(),
        )
        return

    result = await db.bulk_create_slots(
        dates,
        f"{start_hour:02d}:00",
        f"{end_hour:02d}:00",
        interval_min,
    )
    # Месячный генератор не помечает даты как custom — при смене стандарта они перезапишутся
    created = result["created"]
    skipped = result["skipped"]

    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    wd_mask = sum(1 << w for w in weekdays)
    next_cb = f"rule_next:{next_year}:{next_month}:{wd_mask}:{start_hour}:{end_hour}:{interval_min}"

    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Посмотреть расписание", callback_data="admin:schedule")
    builder.button(text=f"📅 Создать на {MONTHS_RU[next_month]}", callback_data=next_cb)
    builder.button(text="◀ Главное меню", callback_data="admin:main")
    builder.adjust(1)

    skip_text = f"\nПропущено <b>{skipped}</b> (уже существовали)" if skipped else ""
    await callback.message.edit_text(
        text=(
            f"✅ <b>Расписание создано!</b>\n\n"
            f"Создано <b>{created}</b> слотов на <b>{len(dates)}</b> рабочих дней.{skip_text}\n\n"
            f"<i>Интервал {interval_min} мин · {start_hour:02d}:00 — {end_hour:02d}:00</i>"
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("rule_next:"))
async def handle_rule_next_month(callback: CallbackQuery, state: FSMContext):
    """Создаёт расписание по тому же правилу на следующий месяц."""
    await callback.answer()
    parts = callback.data.split(":")
    next_year = int(parts[1])
    next_month = int(parts[2])
    wd_mask = int(parts[3])
    start_hour = int(parts[4])
    end_hour = int(parts[5])
    interval_min = int(parts[6])

    weekdays = {i for i in range(7) if wd_mask & (1 << i)}
    last_day = cal_module.monthrange(next_year, next_month)[1]

    dates = [
        date(next_year, next_month, d).strftime("%Y-%m-%d")
        for d in range(1, last_day + 1)
        if date(next_year, next_month, d).weekday() in weekdays
    ]

    result = await db.bulk_create_slots(
        dates,
        f"{start_hour:02d}:00",
        f"{end_hour:02d}:00",
        interval_min,
    )
    # Месячный генератор не помечает даты как custom — при смене стандарта они перезапишутся
    created = result["created"]
    skipped = result["skipped"]

    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Посмотреть расписание", callback_data="admin:schedule")
    builder.button(text="◀ Главное меню", callback_data="admin:main")
    builder.adjust(1)

    skip_text = f"\nПропущено <b>{skipped}</b> (уже существовали)" if skipped else ""
    await callback.message.edit_text(
        text=(
            f"✅ <b>Расписание на {MONTHS_RU[next_month]} создано!</b>\n\n"
            f"Создано <b>{created}</b> слотов на <b>{len(dates)}</b> рабочих дней.{skip_text}\n\n"
            f"<i>Интервал {interval_min} мин · {start_hour:02d}:00 — {end_hour:02d}:00</i>"
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


# ===================================================
# 11. РЕДАКТОР РАСПИСАНИЯ
# ===================================================

async def _show_schedule_edit_calendar(message, year: int, month: int, edit: bool = True):
    """
    Показывает календарь редактора расписания.
    Если задано стандартное расписание — автоматически докидывает слоты
    на 24 месяца вперёд (только некастомные дни, только свободные).
    """
    # Авто-генерация по стандарту при открытии редактора
    rule = await db.get_default_schedule()
    if rule:
        await db.apply_default_schedule_for_months(24)

    dates_with_slots = await db.get_dates_with_any_slots(year, month)
    kb = build_admin_calendar(
        year, month, dates_with_slots,
        nav_prefix="admin_ed_cal_nav",
        date_prefix="admin_ed_cal_date",
    )

    # Добавляем кнопки управления под календарём
    kb.inline_keyboard.extend([
        [InlineKeyboardButton(text="🔲 Выбрать несколько дней", callback_data="admin_ed_multiselect")],
        [InlineKeyboardButton(text="← К расписанию", callback_data="admin:schedule")],
        [InlineKeyboardButton(text="◀ Главное меню", callback_data="admin:main")],
    ])

    hint = "<i>📅 — есть слоты  |  число — пустой день (нажмите чтобы создать)</i>"
    if rule:
        wd_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        wd_list = " ".join(n for i, n in enumerate(wd_names) if rule["weekdays_mask"] & (1 << i))
        hint += (
            f"\n\n⚙️ <b>Стандарт:</b> {wd_list} · "
            f"{_fmt_schedule_range(rule['start_hour'], rule['end_hour'])} · "
            f"{rule['interval_min']} мин"
        )

    text = "✏️ <b>Редактировать расписание</b>\n\n" + hint
    if edit:
        await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "admin:schedule_edit")
async def handle_admin_schedule_edit(callback: CallbackQuery, state: FSMContext):
    """Точка входа в редактор расписания."""
    await callback.answer()
    await state.clear()
    await state.set_state(AdminScheduleEditStates.waiting_date)
    year, month = get_current_month_year()
    await _show_schedule_edit_calendar(callback.message, year, month)


@router.callback_query(
    StateFilter(
        AdminScheduleEditStates.waiting_date,
        AdminScheduleEditStates.editing_slots,
        AdminScheduleEditStates.day_action,
        AdminScheduleEditStates.day_waiting_start,
        AdminScheduleEditStates.day_waiting_end,
        AdminScheduleEditStates.day_waiting_interval,
        AdminScheduleEditStates.extending_morning,
        AdminScheduleEditStates.extending_evening,
        AdminScheduleEditStates.changing_interval,
        AdminScheduleEditStates.multi_action,
    ),
    F.data.startswith("admin_ed_cal_nav:"),
)
async def handle_admin_ed_cal_nav(callback: CallbackQuery, state: FSMContext):
    """Навигация по месяцам в редакторе (работает из любого под-состояния)."""
    await callback.answer()
    _, year_str, month_str = callback.data.split(":")
    await state.set_state(AdminScheduleEditStates.waiting_date)
    await _show_schedule_edit_calendar(callback.message, int(year_str), int(month_str))


async def _show_day_action_menu(message, date_str: str, state: FSMContext):
    """Показывает меню действий для выбранного дня с существующими слотами."""
    await state.set_state(AdminScheduleEditStates.day_action)
    await state.update_data(edit_date=date_str, edit_dates=[date_str])

    slots = await db.get_all_slots_for_date(date_str)
    info = await db.get_day_schedule_info(date_str)

    free_count = sum(1 for s in slots if s["is_available"])
    booked_count = len(slots) - free_count

    info_line = ""
    if info:
        info_line = f"\n🕐 {info['start']} – {info['end_exclusive']} · {info['interval_min']} мин"

    year, month = int(date_str[:4]), int(date_str[5:7])

    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Редактировать слоты", callback_data=f"admin_ed_edit_slots:{date_str}")
    builder.button(text="➕ Продлить утром", callback_data=f"admin_ed_ext_m:{date_str}")
    builder.button(text="➕ Продлить вечером", callback_data=f"admin_ed_ext_e:{date_str}")
    builder.button(text="⏱ Изменить интервал", callback_data=f"admin_ed_chg_int:{date_str}")
    builder.button(text="🗑 Удалить весь день", callback_data=f"edit_day_delete:{date_str}")
    builder.button(text="← К редактору", callback_data=f"admin_ed_cal_nav:{year}:{month}")
    builder.button(text="← К расписанию", callback_data="admin:schedule")
    builder.button(text="◀ Главное меню", callback_data="admin:main")
    builder.adjust(1, 2, 1, 1, 1, 1, 1)

    await message.edit_text(
        text=(
            f"📅 <b>{format_date_ru(date_str)}</b>{info_line}\n\n"
            f"Слотов: {len(slots)} (свободных: {free_count}, занято: {booked_count})\n\n"
            "Выберите действие:"
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(
    StateFilter(AdminScheduleEditStates.waiting_date),
    F.data.startswith("admin_ed_cal_date:"),
)
async def handle_admin_ed_cal_date(callback: CallbackQuery, state: FSMContext):
    """Дата выбрана — если есть слоты: меню действий. Если нет: меню создания."""
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]

    slots = await db.get_all_slots_for_date(date_str)

    if not slots:
        # Показываем меню создания рабочего дня
        rule = await db.get_default_schedule()
        await state.set_state(AdminScheduleEditStates.day_waiting_start)
        await state.update_data(edit_date=date_str, edit_dates=[date_str])

        builder = InlineKeyboardBuilder()
        if rule:
            builder.button(
                text=f"✅ По стандарту ({_fmt_schedule_range(rule['start_hour'], rule['end_hour'])}, {rule['interval_min']} мин)",
                callback_data=f"ed_day_default:{date_str}",
            )
        builder.button(text="⚙️ Настроить вручную", callback_data="ed_day_manual")
        year, month = int(date_str[:4]), int(date_str[5:7])
        builder.button(text="← К редактору", callback_data=f"admin_ed_cal_nav:{year}:{month}")
        builder.button(text="← К расписанию", callback_data="admin:schedule")
        builder.button(text="◀ Главное меню", callback_data="admin:main")
        builder.adjust(1)

        await callback.message.edit_text(
            text=(
                f"📅 <b>{format_date_ru(date_str)}</b> — рабочий день не создан.\n\n"
                "Как создать слоты на этот день?"
            ),
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        return

    # Есть слоты — показываем меню действий
    await _show_day_action_menu(callback.message, date_str, state)


@router.callback_query(F.data.startswith("admin_ed_day_action:"))
async def handle_admin_ed_day_action(callback: CallbackQuery, state: FSMContext):
    """Возврат в меню действий дня из любого под-состояния."""
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]
    await _show_day_action_menu(callback.message, date_str, state)


@router.callback_query(
    AdminScheduleEditStates.day_action,
    F.data.startswith("admin_ed_edit_slots:"),
)
async def handle_ed_edit_slots(callback: CallbackQuery, state: FSMContext):
    """Из меню действий → переход к тогглам слотов."""
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]
    slots = await db.get_all_slots_for_date(date_str)
    await state.set_state(AdminScheduleEditStates.editing_slots)
    await state.update_data(edit_date=date_str, removed_ids=[])

    booked_count = sum(1 for s in slots if not s["is_available"])
    await callback.message.edit_text(
        text=(
            f"✏️ <b>Редактирование: {format_date_ru(date_str)}</b>\n\n"
            f"Слотов: {len(slots)} · Занято: {booked_count}\n\n"
            "✅ — активен  ❌ — будет удалён  🔒 — занят\n"
            "<i>Нажмите слот чтобы пометить для удаления</i>"
        ),
        reply_markup=get_slot_edit_keyboard(slots, set(), date_str),
        parse_mode="HTML",
    )


@router.callback_query(AdminScheduleEditStates.editing_slots, F.data.startswith("edit_slot_toggle:"))
async def handle_edit_slot_toggle(callback: CallbackQuery, state: FSMContext):
    """Переключить пометку слота для удаления."""
    await callback.answer()
    slot_id = callback.data.split(":", 1)[1]
    fsm = await state.get_data()
    removed_ids = set(fsm.get("removed_ids", []))
    date_str = fsm["edit_date"]

    if slot_id in removed_ids:
        removed_ids.discard(slot_id)
    else:
        removed_ids.add(slot_id)
    await state.update_data(removed_ids=list(removed_ids))

    slots = await db.get_all_slots_for_date(date_str)
    await callback.message.edit_reply_markup(
        reply_markup=get_slot_edit_keyboard(slots, removed_ids, date_str)
    )


@router.callback_query(AdminScheduleEditStates.editing_slots, F.data == "edit_slot_save")
async def handle_edit_slot_save(callback: CallbackQuery, state: FSMContext):
    """Применить изменения: удалить помеченные слоты из БД."""
    await callback.answer()
    fsm = await state.get_data()
    removed_ids = set(fsm.get("removed_ids", []))
    date_str = fsm["edit_date"]

    if not removed_ids:
        await callback.answer("Нет помеченных слотов для удаления.", show_alert=True)
        return

    deleted = 0
    for slot_id in removed_ids:
        if await db.delete_slot_by_id(slot_id):
            deleted += 1

    await db.add_custom_day(date_str)
    await state.clear()
    year, month = int(date_str[:4]), int(date_str[5:7])
    await callback.answer(f"✅ Сохранено, удалено слотов: {deleted}", show_alert=True)
    await _show_schedule_view_calendar(callback.message, year, month)


@router.callback_query(
    StateFilter(AdminScheduleEditStates.editing_slots, AdminScheduleEditStates.day_action),
    F.data.startswith("edit_day_delete:"),
)
async def handle_edit_day_delete_prompt(callback: CallbackQuery):
    """Запрос подтверждения удаления всего дня."""
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, удалить весь день", callback_data=f"edit_day_confirm:{date_str}")
    builder.button(text="← Нет, назад", callback_data=f"admin_ed_day_action:{date_str}")
    builder.adjust(1)

    await callback.message.edit_text(
        text=(
            f"⚠️ <b>Удалить все слоты за {format_date_ru(date_str)}?</b>\n\n"
            "Занятые бронированиями слоты не будут удалены.\n"
            "Это действие нельзя отменить."
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("edit_day_confirm:"))
async def handle_edit_day_confirm(callback: CallbackQuery, state: FSMContext):
    """Выполняет удаление всех свободных слотов дня."""
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]
    deleted = await db.delete_slots_for_date(date_str)
    # Помечаем как кастомный (пустой день тоже защищён от перезаписи стандартом)
    await db.add_custom_day(date_str)

    year, month = int(date_str[:4]), int(date_str[5:7])
    await state.set_state(AdminScheduleEditStates.waiting_date)
    await callback.answer(
        f"Удалено {deleted} слотов за {format_date_ru(date_str)}.",
        show_alert=True,
    )
    await _show_schedule_edit_calendar(callback.message, year, month)


@router.callback_query(AdminScheduleEditStates.editing_slots, F.data == "edit_slot_ignore")
async def handle_edit_slot_ignore(callback: CallbackQuery):
    """Заглушка для нажатия на занятый слот."""
    await callback.answer("Этот слот занят бронированием и не может быть удалён.")


# ===================================================
# 12. ПРОДЛЕНИЕ ДНЯ / СМЕНА ИНТЕРВАЛА (из меню действий)
# ===================================================

@router.callback_query(
    AdminScheduleEditStates.day_action,
    F.data.startswith("admin_ed_ext_m:"),
)
async def handle_ed_extend_morning(callback: CallbackQuery, state: FSMContext):
    """Продление дня утром — показывает часы до текущего начала."""
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]
    info = await db.get_day_schedule_info(date_str)
    current_start_h = int(info["start"][:2]) if info else 10

    hours = list(range(6, current_start_h))
    if not hours:
        await callback.answer("День уже начинается с 6:00, некуда продлевать.", show_alert=True)
        return

    await state.set_state(AdminScheduleEditStates.extending_morning)
    await state.update_data(edit_date=date_str, edit_dates=[date_str])

    start_txt = info["start"] if info else "?:??"
    await callback.message.edit_text(
        text=(
            f"➕ <b>Продлить утром · {format_date_ru(date_str)}</b>\n\n"
            f"Сейчас начинается: <b>{start_txt}</b>\n\n"
            "Выберите новое <b>время начала</b>:"
        ),
        reply_markup=get_hour_keyboard(hours, "ed_ext_m_h", f"admin_ed_day_action:{date_str}"),
        parse_mode="HTML",
    )


@router.callback_query(
    AdminScheduleEditStates.extending_morning,
    F.data.startswith("ed_ext_m_h:"),
)
async def handle_ed_extend_morning_apply(callback: CallbackQuery, state: FSMContext):
    """Добавляет слоты в утренней части."""
    await callback.answer()
    new_start_h = int(callback.data.split(":")[1])
    fsm = await state.get_data()
    date_str = fsm["edit_date"]
    info = await db.get_day_schedule_info(date_str)
    if not info:
        await callback.answer("Ошибка: не удалось получить инфо о дне.", show_alert=True)
        return

    # Добавляем слоты от нового начала до старого начала (не включая)
    result = await db.bulk_create_slots(
        [date_str],
        f"{new_start_h:02d}:00",
        info["start"],
        info["interval_min"],
    )
    await db.add_custom_day(date_str)
    await state.set_state(AdminScheduleEditStates.waiting_date)
    await callback.answer(
        f"✅ Добавлено {result.get('created', 0)} слотов утром.",
        show_alert=True,
    )
    year, month = int(date_str[:4]), int(date_str[5:7])
    await _show_schedule_edit_calendar(callback.message, year, month)


@router.callback_query(
    AdminScheduleEditStates.day_action,
    F.data.startswith("admin_ed_ext_e:"),
)
async def handle_ed_extend_evening(callback: CallbackQuery, state: FSMContext):
    """Продление дня вечером — показывает часы после текущего конца."""
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]
    info = await db.get_day_schedule_info(date_str)
    current_end_h = int(info["end"][:2]) if info else 18

    hours = list(range(current_end_h + 1, 24))
    if not hours:
        await callback.answer("День уже заканчивается в 23:00, некуда продлевать.", show_alert=True)
        return

    await state.set_state(AdminScheduleEditStates.extending_evening)
    await state.update_data(edit_date=date_str, edit_dates=[date_str])

    end_txt = info["end"] if info else "?:??"
    await callback.message.edit_text(
        text=(
            f"➕ <b>Продлить вечером · {format_date_ru(date_str)}</b>\n\n"
            f"Сейчас заканчивается: <b>{end_txt}</b>\n\n"
            "Выберите новое <b>время окончания</b>:"
        ),
        reply_markup=get_hour_keyboard(hours, "ed_ext_e_h", f"admin_ed_day_action:{date_str}"),
        parse_mode="HTML",
    )


@router.callback_query(
    AdminScheduleEditStates.extending_evening,
    F.data.startswith("ed_ext_e_h:"),
)
async def handle_ed_extend_evening_apply(callback: CallbackQuery, state: FSMContext):
    """Добавляет слоты в вечерней части."""
    await callback.answer()
    new_end_h = int(callback.data.split(":")[1])
    fsm = await state.get_data()
    date_str = fsm["edit_date"]
    info = await db.get_day_schedule_info(date_str)
    if not info:
        await callback.answer("Ошибка: не удалось получить инфо о дне.", show_alert=True)
        return

    # Добавляем слоты от (последний + интервал) до нового конца включительно
    result = await db.bulk_create_slots(
        [date_str],
        info["end_exclusive"],
        f"{new_end_h:02d}:00",
        info["interval_min"],
    )
    # Если new_end_h ровно = end_exclusive час, bulk_create_slots добавит один слот
    if result.get("created", 0) == 0:
        # Попробуем добавить хотя бы один слот — сам час
        result = await db.bulk_create_slots(
            [date_str],
            info["end_exclusive"],
            f"{new_end_h:02d}:59",
            info["interval_min"],
        )

    await db.add_custom_day(date_str)
    await state.set_state(AdminScheduleEditStates.waiting_date)
    await callback.answer(
        f"✅ Добавлено {result.get('created', 0)} слотов вечером.",
        show_alert=True,
    )
    year, month = int(date_str[:4]), int(date_str[5:7])
    await _show_schedule_edit_calendar(callback.message, year, month)


@router.callback_query(
    AdminScheduleEditStates.day_action,
    F.data.startswith("admin_ed_chg_int:"),
)
async def handle_ed_change_interval_prompt(callback: CallbackQuery, state: FSMContext):
    """Показывает выбор нового интервала для одного дня."""
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]
    info = await db.get_day_schedule_info(date_str)

    await state.set_state(AdminScheduleEditStates.changing_interval)
    await state.update_data(edit_date=date_str, edit_dates=[date_str])

    current_txt = f" (текущий: {info['interval_min']} мин)" if info else ""
    builder = InlineKeyboardBuilder()
    builder.button(text="⏱ 15 минут", callback_data="ed_chg_int:15")
    builder.button(text="⏱ 30 минут", callback_data="ed_chg_int:30")
    builder.button(text="⏱ 1 час", callback_data="ed_chg_int:60")
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="← Назад", callback_data=f"admin_ed_day_action:{date_str}"))

    await callback.message.edit_text(
        text=(
            f"⏱ <b>Изменить интервал · {format_date_ru(date_str)}</b>\n\n"
            f"Свободные слоты будут удалены и пересозданы с новым интервалом{current_txt}.\n\n"
            "Выберите новый интервал:"
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(
    AdminScheduleEditStates.changing_interval,
    F.data.startswith("ed_chg_int:"),
)
async def handle_ed_change_interval_apply(callback: CallbackQuery, state: FSMContext):
    """Удаляет свободные слоты и пересоздаёт с новым интервалом."""
    await callback.answer()
    new_interval = int(callback.data.split(":")[1])
    fsm = await state.get_data()
    dates = fsm.get("edit_dates") or [fsm.get("edit_date")]
    dates = [d for d in dates if d]

    total_created = 0
    for date_str in dates:
        info = await db.get_day_schedule_info(date_str)
        if not info:
            continue
        await db.delete_slots_for_date(date_str)
        result = await db.bulk_create_slots(
            [date_str],
            info["start"],
            info["end_exclusive"],
            new_interval,
        )
        await db.add_custom_day(date_str)
        total_created += result.get("created", 0)

    await state.set_state(AdminScheduleEditStates.waiting_date)
    await callback.answer(
        f"✅ Интервал изменён. Создано {total_created} слотов.",
        show_alert=True,
    )
    first = dates[0] if dates else None
    year = int(first[:4]) if first else get_current_month_year()[0]
    month = int(first[5:7]) if first else get_current_month_year()[1]
    await _show_schedule_edit_calendar(callback.message, year, month)


# ===================================================
# 12.5. МУЛЬТИВЫБОР ДНЕЙ
# ===================================================

async def _show_multiselect_calendar(message, year: int, month: int, selected_dates: list, edit: bool = True):
    """Показывает календарь мультивыбора дней."""
    dates_with_slots = await db.get_dates_with_any_slots(year, month)
    kb = build_admin_multiselect_calendar(year, month, dates_with_slots, selected_dates)
    n = len(selected_dates)
    text = (
        "🔲 <b>Выбор дней для редактирования</b>\n\n"
        f"Выбрано: <b>{n}</b> {_plural_days(n)}\n"
        "<i>Нажмите на день чтобы добавить/убрать из выбора</i>"
    )
    if edit:
        await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")


def _plural_days(n: int) -> str:
    if 11 <= n % 100 <= 14:
        return "дней"
    r = n % 10
    if r == 1:
        return "день"
    if 2 <= r <= 4:
        return "дня"
    return "дней"


@router.callback_query(
    AdminScheduleEditStates.waiting_date,
    F.data == "admin_ed_multiselect",
)
async def handle_ed_multiselect_start(callback: CallbackQuery, state: FSMContext):
    """Переход в режим мультивыбора дней."""
    await callback.answer()
    await state.set_state(AdminScheduleEditStates.selecting_days)
    await state.update_data(selected_dates=[])
    year, month = get_current_month_year()
    await _show_multiselect_calendar(callback.message, year, month, [])


@router.callback_query(
    AdminScheduleEditStates.selecting_days,
    F.data.startswith("admin_ed_ms_nav:"),
)
async def handle_ed_ms_nav(callback: CallbackQuery, state: FSMContext):
    """Навигация по месяцам в режиме мультивыбора."""
    await callback.answer()
    _, year_str, month_str = callback.data.split(":")
    fsm = await state.get_data()
    selected = fsm.get("selected_dates", [])
    await _show_multiselect_calendar(callback.message, int(year_str), int(month_str), selected)


@router.callback_query(
    AdminScheduleEditStates.selecting_days,
    F.data.startswith("admin_ed_ms_sel:"),
)
async def handle_ed_ms_sel(callback: CallbackQuery, state: FSMContext):
    """Добавить день в мультивыбор."""
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]
    fsm = await state.get_data()
    selected = list(fsm.get("selected_dates", []))
    if date_str not in selected:
        selected.append(date_str)
    await state.update_data(selected_dates=selected)
    year, month = int(date_str[:4]), int(date_str[5:7])
    await _show_multiselect_calendar(callback.message, year, month, selected)


@router.callback_query(
    AdminScheduleEditStates.selecting_days,
    F.data.startswith("admin_ed_ms_desel:"),
)
async def handle_ed_ms_desel(callback: CallbackQuery, state: FSMContext):
    """Убрать день из мультивыбора."""
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]
    fsm = await state.get_data()
    selected = [d for d in fsm.get("selected_dates", []) if d != date_str]
    await state.update_data(selected_dates=selected)
    year, month = int(date_str[:4]), int(date_str[5:7])
    await _show_multiselect_calendar(callback.message, year, month, selected)


@router.callback_query(
    AdminScheduleEditStates.selecting_days,
    F.data == "admin_ed_ms_apply",
)
async def handle_ed_ms_apply(callback: CallbackQuery, state: FSMContext):
    """Показывает меню действий для выбранных дней."""
    await callback.answer()
    fsm = await state.get_data()
    selected = fsm.get("selected_dates", [])
    if not selected:
        await callback.answer("Выберите хотя бы один день.", show_alert=True)
        return

    await state.set_state(AdminScheduleEditStates.multi_action)
    await state.update_data(edit_dates=selected)

    n = len(selected)
    sorted_dates = sorted(selected)
    dates_preview = ", ".join(format_date_ru(d) for d in sorted_dates[:5])
    if n > 5:
        dates_preview += f" и ещё {n - 5}"

    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить слоты", callback_data="admin_ed_multi_add")
    builder.button(text="⏱ Изменить интервал", callback_data="admin_ed_multi_chg_int")
    builder.button(text="🗑 Удалить свободные слоты", callback_data="admin_ed_multi_del")
    builder.button(text="← Изменить выбор", callback_data="admin_ed_ms_back")
    builder.button(text="❌ Отмена", callback_data="admin:schedule_edit")
    builder.adjust(1, 1, 1, 2)

    await callback.message.edit_text(
        text=(
            f"🔲 <b>Выбрано {n} {_plural_days(n)}</b>\n\n"
            f"{dates_preview}\n\n"
            "Выберите действие для всех выбранных дней:"
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(
    AdminScheduleEditStates.multi_action,
    F.data == "admin_ed_ms_back",
)
async def handle_ed_ms_back(callback: CallbackQuery, state: FSMContext):
    """Возврат к мультивыбору."""
    await callback.answer()
    fsm = await state.get_data()
    selected = fsm.get("edit_dates", [])
    await state.set_state(AdminScheduleEditStates.selecting_days)
    await state.update_data(selected_dates=selected)
    year, month = get_current_month_year()
    await _show_multiselect_calendar(callback.message, year, month, selected)


@router.callback_query(
    AdminScheduleEditStates.multi_action,
    F.data == "admin_ed_multi_add",
)
async def handle_ed_multi_add(callback: CallbackQuery, state: FSMContext):
    """Мультивыбор → добавить слоты (запускает мини-генератор для всех дат)."""
    await callback.answer()
    fsm = await state.get_data()
    dates = fsm.get("edit_dates", [])
    n = len(dates)
    # Берём первую дату как "якорную" для отображения в подсказке
    first = sorted(dates)[0] if dates else ""
    await state.set_state(AdminScheduleEditStates.day_waiting_start)
    # edit_dates уже есть в FSM; edit_date ставим первую дату для отображения
    await state.update_data(edit_date=first)

    await callback.message.edit_text(
        text=(
            f"➕ <b>Добавить слоты в {n} {_plural_days(n)}</b>\n\n"
            "Шаг 1 из 3 — Выберите <b>время начала</b>:"
        ),
        reply_markup=get_hour_keyboard(list(range(0, 24)), "ed_day_start", "admin:schedule_edit"),
        parse_mode="HTML",
    )


@router.callback_query(
    AdminScheduleEditStates.multi_action,
    F.data == "admin_ed_multi_chg_int",
)
async def handle_ed_multi_chg_int(callback: CallbackQuery, state: FSMContext):
    """Мультивыбор → изменить интервал."""
    await callback.answer()
    fsm = await state.get_data()
    dates = fsm.get("edit_dates", [])
    n = len(dates)
    await state.set_state(AdminScheduleEditStates.changing_interval)

    builder = InlineKeyboardBuilder()
    builder.button(text="⏱ 15 минут", callback_data="ed_chg_int:15")
    builder.button(text="⏱ 30 минут", callback_data="ed_chg_int:30")
    builder.button(text="⏱ 1 час", callback_data="ed_chg_int:60")
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="← Назад", callback_data="admin_ed_ms_apply"))

    await callback.message.edit_text(
        text=(
            f"⏱ <b>Изменить интервал в {n} {_plural_days(n)}</b>\n\n"
            "Для каждого дня: свободные слоты удаляются и пересоздаются "
            "с тем же диапазоном времени, но новым интервалом.\n\n"
            "Выберите новый интервал:"
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(
    AdminScheduleEditStates.multi_action,
    F.data == "admin_ed_multi_del",
)
async def handle_ed_multi_del(callback: CallbackQuery, state: FSMContext):
    """Мультивыбор → удалить свободные слоты."""
    await callback.answer()
    fsm = await state.get_data()
    dates = fsm.get("edit_dates", [])
    n = len(dates)

    builder = InlineKeyboardBuilder()
    builder.button(text=f"✅ Да, удалить слоты в {n} {_plural_days(n)}", callback_data="ed_multi_del_confirm")
    builder.button(text="← Нет, назад", callback_data="admin_ed_ms_apply")
    builder.adjust(1)

    await callback.message.edit_text(
        text=(
            f"⚠️ <b>Удалить свободные слоты в {n} {_plural_days(n)}?</b>\n\n"
            "Занятые бронированиями слоты не будут затронуты.\n"
            "Это действие нельзя отменить."
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(
    AdminScheduleEditStates.multi_action,
    F.data == "ed_multi_del_confirm",
)
async def handle_ed_multi_del_confirm(callback: CallbackQuery, state: FSMContext):
    """Подтверждение удаления слотов для всех выбранных дней."""
    await callback.answer()
    fsm = await state.get_data()
    dates = fsm.get("edit_dates", [])

    total = 0
    for date_str in dates:
        deleted = await db.delete_slots_for_date(date_str)
        await db.add_custom_day(date_str)
        total += deleted

    await state.set_state(AdminScheduleEditStates.waiting_date)
    await callback.answer(
        f"✅ Удалено {total} слотов в {len(dates)} {_plural_days(len(dates))}.",
        show_alert=True,
    )
    year, month = get_current_month_year()
    await _show_schedule_edit_calendar(callback.message, year, month)


# ===================================================
# 12. МИНИ-ГЕНЕРАТОР ДЛЯ ПУСТОГО ДНЯ В РЕДАКТОРЕ
# ===================================================

@router.callback_query(
    StateFilter(AdminScheduleEditStates.day_waiting_start),
    F.data.startswith("ed_day_default:"),
)
async def handle_ed_day_apply_default(callback: CallbackQuery, state: FSMContext):
    """Применить стандартное расписание к пустому дню."""
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]
    rule = await db.get_default_schedule()
    if not rule:
        await callback.answer("Стандартное расписание не задано.", show_alert=True)
        return

    result = await db.bulk_create_slots(
        [date_str],
        f"{rule['start_hour']:02d}:00",
        f"{rule['end_hour']:02d}:00",
        rule["interval_min"],
    )
    await db.add_custom_day(date_str)
    await state.set_state(AdminScheduleEditStates.waiting_date)
    await callback.answer(
        f"✅ Создано {result['created']} слотов по стандарту.",
        show_alert=True,
    )
    year, month = int(date_str[:4]), int(date_str[5:7])
    await _show_schedule_edit_calendar(callback.message, year, month)


@router.callback_query(
    StateFilter(AdminScheduleEditStates.day_waiting_start),
    F.data == "ed_day_manual",
)
async def handle_ed_day_manual(callback: CallbackQuery, state: FSMContext):
    """Начать ручную настройку: шаг 1 — время начала."""
    await callback.answer()
    fsm = await state.get_data()
    date_str = fsm["edit_date"]

    await callback.message.edit_text(
        text=(
            f"📅 <b>{format_date_ru(date_str)}</b>\n\n"
            "Шаг 1 из 3 — Выберите <b>время начала</b> рабочего дня:"
        ),
        reply_markup=get_hour_keyboard(list(range(0, 24)), "ed_day_start", "admin:schedule_edit"),
        parse_mode="HTML",
    )


@router.callback_query(
    StateFilter(AdminScheduleEditStates.day_waiting_start),
    F.data.startswith("ed_day_start:"),
)
async def handle_ed_day_start(callback: CallbackQuery, state: FSMContext):
    """Записать начало, шаг 2 — время окончания."""
    await callback.answer()
    hour = int(callback.data.split(":")[1])
    await state.update_data(day_start_hour=hour)
    await state.set_state(AdminScheduleEditStates.day_waiting_end)

    await callback.message.edit_text(
        text=(
            f"Начало: <b>{hour:02d}:00</b>\n\n"
            "Шаг 2 из 3 — Выберите <b>время окончания</b>:"
        ),
        reply_markup=get_hour_keyboard(
            list(range(hour + 1, 24)) + ([0] if hour > 0 else []),
            "ed_day_end", "admin:schedule_edit",
            special_labels={0: "00 (полночь)"},
        ),
        parse_mode="HTML",
    )


@router.callback_query(
    StateFilter(AdminScheduleEditStates.day_waiting_end),
    F.data.startswith("ed_day_end:"),
)
async def handle_ed_day_end(callback: CallbackQuery, state: FSMContext):
    """Записать конец, шаг 3 — интервал."""
    await callback.answer()
    hour = int(callback.data.split(":")[1])
    await state.update_data(day_end_hour=hour)
    await state.set_state(AdminScheduleEditStates.day_waiting_interval)

    fsm = await state.get_data()
    start_hour = fsm["day_start_hour"]

    builder = InlineKeyboardBuilder()
    builder.button(text="⏱ 15 минут", callback_data="ed_day_interval:15")
    builder.button(text="⏱ 30 минут", callback_data="ed_day_interval:30")
    builder.button(text="⏱ 1 час", callback_data="ed_day_interval:60")
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="← Назад", callback_data="admin:schedule_edit"))

    await callback.message.edit_text(
        text=(
            f"Начало: <b>{start_hour:02d}:00</b> — Конец: <b>{hour:02d}:00</b>\n\n"
            "Шаг 3 из 3 — Выберите <b>интервал</b>:"
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(
    StateFilter(AdminScheduleEditStates.day_waiting_interval),
    F.data.startswith("ed_day_interval:"),
)
async def handle_ed_day_interval(callback: CallbackQuery, state: FSMContext):
    """Генерирует слоты для одной или нескольких дат и помечает их кастомными."""
    await callback.answer()
    interval_min = int(callback.data.split(":")[1])
    fsm = await state.get_data()
    start_hour = fsm["day_start_hour"]
    end_hour = fsm["day_end_hour"]

    # Поддержка мультивыбора: edit_dates — список дат
    dates = fsm.get("edit_dates") or [fsm.get("edit_date")]
    dates = [d for d in dates if d]

    total_created = 0
    for date_str in dates:
        result = await db.bulk_create_slots(
            [date_str],
            f"{start_hour:02d}:00",
            f"{end_hour:02d}:00",
            interval_min,
        )
        await db.add_custom_day(date_str)
        total_created += result.get("created", 0)

    await state.set_state(AdminScheduleEditStates.waiting_date)
    await callback.answer(
        f"✅ Создано {total_created} слотов в {len(dates)} {_plural_days(len(dates))}.",
        show_alert=True,
    )
    first = dates[0] if dates else None
    year = int(first[:4]) if first else get_current_month_year()[0]
    month = int(first[5:7]) if first else get_current_month_year()[1]
    await _show_schedule_edit_calendar(callback.message, year, month)


# ===================================================
# 13. СТАНДАРТНОЕ РАСПИСАНИЕ
# ===================================================

def _format_default_schedule_text(rule: dict) -> str:
    """Форматирует информацию о стандартном расписании для отображения."""
    wd_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    wd_list = " ".join(n for i, n in enumerate(wd_names) if rule["weekdays_mask"] & (1 << i))
    return (
        f"📅 <b>Дни:</b> {wd_list}\n"
        f"🕐 <b>Время:</b> {_fmt_schedule_range(rule['start_hour'], rule['end_hour'])}\n"
        f"⏱ <b>Интервал:</b> {rule['interval_min']} мин\n\n"
        "Слоты генерируются автоматически при открытии редактора расписания."
    )


@router.callback_query(F.data == "admin:default_schedule")
async def handle_admin_default_schedule(callback: CallbackQuery, state: FSMContext):
    """Показывает текущее стандартное расписание или приглашение его задать."""
    await callback.answer()
    await state.clear()
    rule = await db.get_default_schedule()

    if not rule:
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Задать стандартное расписание", callback_data="default_sched:setup")
        builder.button(text="← К расписанию", callback_data="admin:schedule")
        builder.button(text="◀ Главное меню", callback_data="admin:main")
        builder.adjust(1)
        await callback.message.edit_text(
            text=(
                "⚙️ <b>Стандартное расписание</b>\n\n"
                "Расписание не задано. Слоты создаются вручную.\n\n"
                "Задав стандарт, бот будет автоматически генерировать слоты "
                "при открытии редактора расписания."
            ),
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
    else:
        custom_days = await db.get_custom_days()
        builder = InlineKeyboardBuilder()
        builder.button(text="✏️ Изменить стандарт", callback_data="default_sched:setup")
        builder.button(text="← К расписанию", callback_data="admin:schedule")
        builder.button(text="◀ Главное меню", callback_data="admin:main")
        builder.adjust(1)
        await callback.message.edit_text(
            text=(
                "⚙️ <b>Стандартное расписание</b>\n\n"
                + _format_default_schedule_text(rule)
                + f"\n\n<i>Дней с ручными правками: {len(custom_days)}</i>"
            ),
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "default_sched:setup")
async def handle_default_sched_setup(callback: CallbackQuery, state: FSMContext):
    """Шаг 1 — выбор дней недели для стандартного расписания."""
    await callback.answer()
    await state.set_state(AdminDefaultScheduleStates.waiting_weekdays)
    await state.update_data(default_weekdays=set())
    await callback.message.edit_text(
        text=(
            "⚙️ <b>Стандартное расписание</b>\n\n"
            "Шаг 1 из 4 — Выберите <b>рабочие дни</b>:"
        ),
        reply_markup=get_weekday_keyboard(set(), cancel_cb="admin:default_schedule"),
        parse_mode="HTML",
    )


@router.callback_query(AdminDefaultScheduleStates.waiting_weekdays, F.data.startswith("rule_wd:"))
async def handle_default_wd_toggle(callback: CallbackQuery, state: FSMContext):
    """Переключает день недели в стандартном расписании."""
    await callback.answer()
    day_idx = int(callback.data.split(":")[1])
    fsm = await state.get_data()
    weekdays = set(fsm.get("default_weekdays", []))
    if day_idx in weekdays:
        weekdays.discard(day_idx)
    else:
        weekdays.add(day_idx)
    await state.update_data(default_weekdays=list(weekdays))
    await callback.message.edit_reply_markup(
        reply_markup=get_weekday_keyboard(weekdays, cancel_cb="admin:default_schedule")
    )


@router.callback_query(AdminDefaultScheduleStates.waiting_weekdays, F.data == "rule_wd_done")
async def handle_default_wd_done(callback: CallbackQuery, state: FSMContext):
    """Подтверждает дни, переходит к шагу 2 — начало рабочего дня."""
    await callback.answer()
    fsm = await state.get_data()
    weekdays = set(fsm.get("default_weekdays", []))
    if not weekdays:
        await callback.answer("Выберите хотя бы один день.", show_alert=True)
        return
    await state.set_state(AdminDefaultScheduleStates.waiting_start_time)

    wd_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    wd_str = " ".join(wd_names[i] for i in sorted(weekdays))
    await callback.message.edit_text(
        text=(
            "⚙️ <b>Стандартное расписание</b>\n\n"
            f"Дни: <b>{wd_str}</b>\n\n"
            "Шаг 2 из 4 — Выберите <b>время начала</b> рабочего дня:"
        ),
        reply_markup=get_hour_keyboard(list(range(0, 24)), "default_start", "admin:default_schedule"),
        parse_mode="HTML",
    )


@router.callback_query(AdminDefaultScheduleStates.waiting_start_time, F.data.startswith("default_start:"))
async def handle_default_start_time(callback: CallbackQuery, state: FSMContext):
    """Записывает начало, шаг 3 — конец рабочего дня."""
    await callback.answer()
    hour = int(callback.data.split(":")[1])
    await state.update_data(default_start_hour=hour)
    await state.set_state(AdminDefaultScheduleStates.waiting_end_time)

    await callback.message.edit_text(
        text=(
            "⚙️ <b>Стандартное расписание</b>\n\n"
            f"Начало: <b>{hour:02d}:00</b>\n\n"
            "Шаг 3 из 4 — Выберите <b>время окончания</b>:"
        ),
        reply_markup=get_hour_keyboard(
            list(range(hour + 1, 24)) + ([0] if hour > 0 else []),
            "default_end", "admin:default_schedule",
            special_labels={0: "00 (полночь)"},
        ),
        parse_mode="HTML",
    )


@router.callback_query(AdminDefaultScheduleStates.waiting_end_time, F.data.startswith("default_end:"))
async def handle_default_end_time(callback: CallbackQuery, state: FSMContext):
    """Записывает конец, шаг 4 — интервал."""
    await callback.answer()
    hour = int(callback.data.split(":")[1])
    await state.update_data(default_end_hour=hour)
    await state.set_state(AdminDefaultScheduleStates.waiting_interval)

    fsm = await state.get_data()
    start_hour = fsm["default_start_hour"]

    builder = InlineKeyboardBuilder()
    builder.button(text="⏱ 15 минут", callback_data="default_interval:15")
    builder.button(text="⏱ 30 минут", callback_data="default_interval:30")
    builder.button(text="⏱ 1 час", callback_data="default_interval:60")
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="← Назад", callback_data="admin:default_schedule"))

    await callback.message.edit_text(
        text=(
            "⚙️ <b>Стандартное расписание</b>\n\n"
            f"Начало: <b>{start_hour:02d}:00</b> — Конец: <b>{hour:02d}:00</b>\n\n"
            "Шаг 4 из 4 — Выберите <b>интервал</b> между записями:"
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(AdminDefaultScheduleStates.waiting_interval, F.data.startswith("default_interval:"))
async def handle_default_interval(callback: CallbackQuery, state: FSMContext):
    """Сохраняет стандартное расписание и пересоздаёт слоты на 24 мес вперёд."""
    await callback.answer()
    interval_min = int(callback.data.split(":")[1])
    fsm = await state.get_data()

    weekdays_mask = sum(1 << w for w in fsm.get("default_weekdays", []))
    start_hour = fsm["default_start_hour"]
    end_hour = fsm["default_end_hour"]

    # Пробуем сохранить — если таблица не создана, покажем ошибку
    saved = await db.save_default_schedule(weekdays_mask, start_hour, end_hour, interval_min)
    if saved is not True:
        back_builder = InlineKeyboardBuilder()
        back_builder.button(text="◀ Назад", callback_data="admin:default_schedule")
        error_detail = f"\n\n<code>{saved}</code>" if isinstance(saved, str) else ""
        await callback.message.edit_text(
            text=f"❌ <b>Ошибка сохранения</b>{error_detail}",
            reply_markup=back_builder.as_markup(),
            parse_mode="HTML",
        )
        return

    # Сообщаем что идёт генерация
    await callback.message.edit_text(
        "⏳ Сохраняю расписание и генерирую слоты на 24 месяца вперёд...",
        parse_mode="HTML",
    )

    result = await db.reset_default_schedule_slots()
    await state.clear()

    wd_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    wd_str = " ".join(n for i, n in enumerate(wd_names) if weekdays_mask & (1 << i))

    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Редактировать расписание", callback_data="admin:schedule_edit")
    builder.button(text="← К расписанию", callback_data="admin:schedule")
    builder.button(text="◀ Главное меню", callback_data="admin:main")
    builder.adjust(1)

    await callback.message.edit_text(
        text=(
            "✅ <b>Стандартное расписание сохранено</b>\n\n"
            f"📅 Дни: <b>{wd_str}</b>\n"
            f"🕐 Время: <b>{_fmt_schedule_range(start_hour, end_hour)}</b>\n"
            f"⏱ Интервал: <b>{interval_min} мин</b>\n\n"
            f"Добавлено слотов: <b>{result.get('created', 0)}</b>\n"
            f"Уже существовало: <b>{result.get('skipped', 0)}</b>"
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "default_sched:delete_prompt")
async def handle_default_sched_delete_prompt(callback: CallbackQuery):
    """Запрашивает подтверждение удаления стандартного расписания."""
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, удалить", callback_data="default_sched:delete_confirm")
    builder.button(text="← Отмена", callback_data="admin:default_schedule")
    builder.button(text="◀ Главное меню", callback_data="admin:main")
    builder.adjust(1)
    await callback.message.edit_text(
        text=(
            "⚠️ <b>Удалить стандартное расписание?</b>\n\n"
            "Уже созданные слоты останутся. "
            "Новые слоты перестанут генерироваться автоматически."
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "default_sched:delete_confirm")
async def handle_default_sched_delete(callback: CallbackQuery, state: FSMContext):
    """Удаляет стандартное расписание."""
    await callback.answer()
    await db.delete_default_schedule()
    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.button(text="◀ К расписанию", callback_data="admin:schedule")
    await callback.message.edit_text(
        text="🗑 Стандартное расписание удалено.\nСлоты создаются вручную.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


