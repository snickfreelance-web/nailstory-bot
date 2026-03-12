# ===================================================
# keyboards.py — Все клавиатуры бота
# ===================================================
# Централизованное место для всех кнопок и клавиатур.
# Разделяем на две категории:
#   1. InlineKeyboardMarkup — кнопки внутри сообщения
#   2. ReplyKeyboardMarkup — кнопки под полем ввода
#
# Inline используем везде где нужен выбор из вариантов.
# Reply используем только для запроса контакта (телефона).
# ===================================================

from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from typing import List, Dict, Optional


# ===================================================
# КЛАВИАТУРЫ ПРИВЕТСТВИЯ И ГЛАВНОГО МЕНЮ
# ===================================================

def get_start_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура стартового сообщения.
    Показывается сразу после /start.

    Кнопки:
        💅 Записаться на маникюр — начинает процесс записи
        📞 Связаться с нами    — показывает контакты
    """
    builder = InlineKeyboardBuilder()

    builder.button(
        text="💅 Записаться на маникюр",
        callback_data="start_booking"
    )
    builder.button(
        text="📞 Связаться с нами",
        callback_data="show_contacts"
    )

    # Кнопки по одной в ряд (столбец)
    builder.adjust(1)

    return builder.as_markup()


# ===================================================
# КЛАВИАТУРЫ ВЫБОРА УСЛУГИ
# ===================================================

def get_services_keyboard(services: List[Dict]) -> InlineKeyboardMarkup:
    """
    Динамически строит клавиатуру со списком услуг из БД.
    Количество кнопок = количество активных услуг.

    Args:
        services: Список словарей из database.get_all_services()
                  Каждый содержит: id, name, price, duration_min

    Returns:
        InlineKeyboardMarkup с кнопками для каждой услуги

    Пример отображения:
        [💅 Маникюр классический — 1000 ₽]
        [✨ Гель-покрытие — 1500 ₽]
        [🌸 Маникюр + гель — 2000 ₽]
        [◀ Назад]
    """
    builder = InlineKeyboardBuilder()

    for service in services:
        # Форматируем текст кнопки: "Название — ЦЕНА ₽"
        btn_text = f"💅 {service['name']} — {service['price']} ₽"

        # callback_data содержит ID услуги для однозначной идентификации
        builder.button(
            text=btn_text,
            callback_data=f"service:{service['id']}"
        )

    # Кнопка "Назад" для возврата в главное меню
    builder.button(
        text="◀ Назад",
        callback_data="back_to_main"
    )

    # По одной кнопке в ряд — удобнее читать длинные названия
    builder.adjust(1)

    return builder.as_markup()


# ===================================================
# КЛАВИАТУРА ЗАПРОСА ТЕЛЕФОНА
# ===================================================

def get_phone_keyboard() -> ReplyKeyboardMarkup:
    """
    Reply-клавиатура для запроса номера телефона.

    Используем ReplyKeyboard (а не Inline) потому что
    только Reply-кнопки поддерживают request_contact=True.
    Эта специальная кнопка отправляет верифицированный
    номер из Telegram-профиля без ручного ввода.

    Returns:
        ReplyKeyboardMarkup с кнопкой "Отправить телефон"
        и кнопкой "Ввести вручную" (для пользователей без телефона в TG)

    После получения телефона клавиатуру нужно убрать
    с помощью ReplyKeyboardRemove().
    """
    builder = ReplyKeyboardBuilder()

    # Главная кнопка — запрашивает контакт из профиля Telegram
    builder.button(
        text="📱 Отправить мой номер",
        request_contact=True,  # Ключевой параметр!
    )

    # Кнопка для ручного ввода (на случай если контакт скрыт)
    builder.button(
        text="✏️ Ввести номер вручную",
    )

    # Кнопки по одной в ряд
    builder.adjust(1)

    return builder.as_markup(
        resize_keyboard=True,  # Уменьшаем клавиатуру под контент
        one_time_keyboard=True,  # Скрывается после нажатия
    )


def get_remove_keyboard() -> ReplyKeyboardRemove:
    """
    Убирает Reply-клавиатуру после использования.
    Отправляется вместе с сообщением подтверждения.
    """
    return ReplyKeyboardRemove()


# ===================================================
# КЛАВИАТУРЫ ПОДТВЕРЖДЕНИЯ
# ===================================================

def get_confirm_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура финального подтверждения записи.
    Показывается перед созданием бронирования.

    Кнопки:
        ✅ Подтвердить  — создаёт бронирование в БД
        ✏️ Изменить    — возвращает к выбору услуги
        ❌ Отменить    — отменяет и возвращает в начало
    """
    builder = InlineKeyboardBuilder()

    builder.button(text="✅ Подтвердить запись", callback_data="confirm_booking")
    builder.button(text="✏️ Изменить", callback_data="back_to_service")
    builder.button(text="❌ Отменить", callback_data="cancel_booking")

    builder.adjust(1)
    return builder.as_markup()


# ===================================================
# КЛАВИАТУРЫ АДМИНИСТРАТИВНОЙ ПАНЕЛИ
# ===================================================

def get_admin_main_keyboard() -> InlineKeyboardMarkup:
    """
    Главное меню администратора.
    Доступно по команде /admin.

    Кнопки:
        📋 Бронирования       — список записей с фильтрами
        💅 Услуги             — добавить/удалить/скрыть
        📅 Расписание         — управление слотами
        📊 Статистика         — сводка по записям
        ➕ Создать запись     — ручное создание бронирования
        👥 Администраторы     — добавить/удалить администраторов
    """
    builder = InlineKeyboardBuilder()

    builder.button(text="📋 Бронирования", callback_data="admin:bookings")
    builder.button(text="💅 Услуги", callback_data="admin:services")
    builder.button(text="📅 Расписание", callback_data="admin:schedule")
    builder.button(text="📊 Статистика", callback_data="admin:stats")
    builder.button(text="➕ Создать запись", callback_data="admin:create_booking")
    builder.button(text="👥 Администраторы", callback_data="admin:admins")

    # 2 + 2 + 1 + 1
    builder.adjust(2, 2, 1, 1)

    return builder.as_markup()


def get_admin_admins_keyboard(
    db_admins: List[Dict],
    owner_id: Optional[int],
    viewer_id: Optional[int],
) -> InlineKeyboardMarkup:
    """
    Клавиатура управления администраторами.

    Args:
        db_admins:  Список записей из таблицы admins (уже содержит role)
        owner_id:   Telegram ID текущего владельца (или None)
        viewer_id:  Telegram ID пользователя, просматривающего страницу

    Логика отображения кнопок:
        - Владелец (owner_id == viewer_id):
            • Обычные администраторы: кнопка [🗑 @username] — удалить
            • Если есть хотя бы один обычный администратор: кнопка [🔄 Передать владение]
            • Кнопка [➕ Добавить администратора]
        - Обычный администратор:
            • Кнопки управления не показываются (только просмотр)
        - Всегда: [◀ Главное меню]
    """
    builder = InlineKeyboardBuilder()
    viewer_is_owner = (owner_id is not None and viewer_id == owner_id)

    if viewer_is_owner:
        # Кнопки удаления для каждого обычного администратора
        regular_admins = [a for a in db_admins if a["telegram_id"] != owner_id]
        for admin in regular_admins:
            t_id = admin["telegram_id"]
            label = f"@{admin['username']}" if admin.get("username") else str(t_id)
            builder.button(
                text=f"🗑 {label}",
                callback_data=f"admin_mgmt:remove:{t_id}",
            )

        # Передача владения — только если есть кому передавать
        if regular_admins:
            builder.button(
                text="🔄 Передать владение",
                callback_data="admin_mgmt:transfer",
            )

        builder.button(text="➕ Добавить администратора", callback_data="admin_mgmt:add")

    builder.button(text="◀ Главное меню", callback_data="admin:main")
    builder.adjust(1)
    return builder.as_markup()


def get_admin_transfer_keyboard(
    db_admins: List[Dict],
    owner_id: Optional[int],
) -> InlineKeyboardMarkup:
    """
    Клавиатура выбора нового владельца при передаче владения.
    Показывает всех обычных администраторов из БД (кроме текущего владельца).

    Args:
        db_admins: Список записей из таблицы admins
        owner_id:  Текущий владелец (его исключаем из списка)
    """
    builder = InlineKeyboardBuilder()

    candidates = [a for a in db_admins if a["telegram_id"] != owner_id]
    for admin in candidates:
        t_id = admin["telegram_id"]
        label = f"@{admin['username']}" if admin.get("username") else str(t_id)
        builder.button(
            text=f"👤 {label}",
            callback_data=f"admin_mgmt:transfer_to:{t_id}",
        )

    builder.button(text="❌ Отмена", callback_data="admin:admins")
    builder.adjust(1)
    return builder.as_markup()


def get_admin_services_keyboard(services: List[Dict]) -> InlineKeyboardMarkup:
    """
    Список услуг в панели администратора.
    Отличается от клиентского: показывает ВСЕ услуги (включая скрытые)
    и добавляет кнопки управления для каждой.

    Args:
        services: Список ВСЕХ услуг (active_only=False)

    Returns:
        Клавиатура с услугами и кнопками управления

    Пример:
        [💅 Маникюр — 1000₽ | ✅ Вкл]
        [✨ Гель — 1500₽     | 🔴 Выкл]
        [+ Добавить услугу]
        [◀ Назад]
    """
    builder = InlineKeyboardBuilder()

    for service in services:
        # Статус услуги визуально
        status_icon = "✅" if service["is_active"] else "🔴"

        # Название услуги — нажатие открывает детали
        builder.button(
            text=f"{status_icon} {service['name']} — {service['price']} ₽",
            callback_data=f"admin_svc:{service['id']}"
        )

    # Кнопка добавления новой услуги
    builder.button(text="➕ Добавить услугу", callback_data="admin_svc:add")

    # Кнопка возврата в главное меню
    builder.button(text="◀ Главное меню", callback_data="admin:main")

    # Каждая услуга — своя строка, добавить и назад — отдельные строки
    builder.adjust(1)

    return builder.as_markup()


def get_admin_service_detail_keyboard(service_id: str, is_active: bool) -> InlineKeyboardMarkup:
    """
    Детальная страница конкретной услуги в админке.
    Показывает кнопки управления выбранной услугой.

    Args:
        service_id: UUID услуги
        is_active: Текущий статус (для кнопки переключения)

    Returns:
        Клавиатура с действиями над услугой

    Кнопки:
        🔴 Скрыть / ✅ Показать  — переключить видимость
        🗑 Удалить              — полное удаление (если нет бронирований)
        ◀ Назад                — к списку услуг
    """
    builder = InlineKeyboardBuilder()

    # Текст кнопки зависит от текущего статуса
    if is_active:
        toggle_text = "🔴 Скрыть от клиентов"
        toggle_data = f"admin_svc_hide:{service_id}"
    else:
        toggle_text = "✅ Показать клиентам"
        toggle_data = f"admin_svc_show:{service_id}"

    builder.button(text="✏️ Редактировать", callback_data=f"admin_svc_edit:{service_id}")
    builder.button(text=toggle_text, callback_data=toggle_data)
    builder.button(text="🗑 Удалить услугу", callback_data=f"admin_svc_del:{service_id}")
    builder.button(text="◀ К списку услуг", callback_data="admin:services")

    builder.adjust(1)
    return builder.as_markup()


def get_admin_duration_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура выбора длительности услуги.
    Администратор выбирает из готовых вариантов вместо ввода числа.

    Returns:
        Клавиатура с вариантами длительности в минутах

    Преимущество: администратор не может ввести некорректное значение.
    """
    builder = InlineKeyboardBuilder()

    # Стандартные длительности для маникюрных услуг
    durations = [30, 45, 60, 75, 90, 120]

    for dur in durations:
        if dur >= 60:
            hours = dur // 60
            mins = dur % 60
            if mins == 0:
                label = f"⏱ {hours} ч"
            else:
                label = f"⏱ {hours} ч {mins} мин"
        else:
            label = f"⏱ {dur} мин"

        builder.button(text=label, callback_data=f"duration:{dur}")

    builder.button(text="❌ Отмена", callback_data="admin:services")

    # По 2 кнопки в ряд, кнопка отмены отдельно
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def get_admin_edit_skip_keyboard(skip_cb: str, cancel_cb: str) -> InlineKeyboardMarkup:
    """
    Универсальная клавиатура для шагов редактирования.
    Используется на шагах ввода имени и цены (текстовый ввод).

    Args:
        skip_cb: callback_data для кнопки «Пропустить»
        cancel_cb: callback_data для кнопки «Отмена»
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭ Пропустить", callback_data=skip_cb)
    builder.button(text="❌ Отмена", callback_data=cancel_cb)
    builder.adjust(2)
    return builder.as_markup()


def get_admin_edit_duration_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура выбора длительности при редактировании услуги.
    Аналог get_admin_duration_keyboard(), но добавлена кнопка «Пропустить».
    """
    builder = InlineKeyboardBuilder()

    durations = [30, 45, 60, 75, 90, 120]

    for dur in durations:
        if dur >= 60:
            hours = dur // 60
            mins = dur % 60
            if mins == 0:
                label = f"⏱ {hours} ч"
            else:
                label = f"⏱ {hours} ч {mins} мин"
        else:
            label = f"⏱ {dur} мин"
        builder.button(text=label, callback_data=f"duration:{dur}")

    builder.button(text="⏭ Пропустить", callback_data="edit_skip_duration")
    builder.button(text="❌ Отмена", callback_data="edit_cancel")

    # 6 кнопок по 2 в ряд, затем 2 служебных отдельно
    builder.adjust(2, 2, 2, 2)
    return builder.as_markup()



def get_admin_bookings_filter_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура фильтрации бронирований по статусу.
    Позволяет быстро просмотреть нужную категорию записей.

    Кнопки:
        📋 Все       — все бронирования
        ⏳ Ожидающие — статус pending
        ✅ Подтверждённые — статус confirmed
        ❌ Отменённые  — статус cancelled
        📅 По дате   — ввод конкретной даты
        ◀ Меню       — в главное меню
    """
    builder = InlineKeyboardBuilder()

    builder.button(text="📋 Все", callback_data="admin_bk_filter:all")
    builder.button(text="⏳ Ожидающие", callback_data="admin_bk_filter:pending")
    builder.button(text="✅ Подтверждённые", callback_data="admin_bk_filter:confirmed")
    builder.button(text="❌ Отменённые", callback_data="admin_bk_filter:cancelled")
    builder.button(text="📅 По дате", callback_data="admin_bk_filter:date")
    builder.button(text="◀ Главное меню", callback_data="admin:main")

    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def get_admin_booking_actions_keyboard(
    booking_id: str,
    current_status: str,
    page: int = 0,
    back_cb: str = None,
) -> InlineKeyboardMarkup:
    """
    Клавиатура действий с конкретным бронированием.

    Args:
        booking_id: UUID бронирования
        current_status: Текущий статус для показа доступных действий
        page: Текущая страница списка (для возврата назад, если back_cb не задан)
        back_cb: Переопределяет callback кнопки «Назад».
                 Например, "admin_bk_cal_date:2024-03-15" для возврата
                 к списку бронирований за конкретный день.

    Returns:
        Клавиатура с действиями

    Доступные действия зависят от статуса:
        pending:   [Подтвердить] [Перенести] [Отменить] [Назад]
        confirmed: [Перенести] [Отменить] [Назад]
        cancelled: [Назад]
    """
    builder = InlineKeyboardBuilder()

    if current_status == "pending":
        builder.button(
            text="✅ Подтвердить",
            callback_data=f"admin_bk_confirm:{booking_id}"
        )

    if current_status != "cancelled":
        builder.button(
            text="📅 Перенести",
            callback_data=f"admin_bk_reschedule:{booking_id}"
        )
        builder.button(
            text="❌ Отменить",
            callback_data=f"admin_bk_cancel:{booking_id}"
        )

    # Кнопка возврата: либо к списку по дате, либо к пагинированному списку
    builder.button(
        text="◀ Назад",
        callback_data=back_cb if back_cb else f"admin_bk_list:{page}"
    )

    builder.adjust(1)
    return builder.as_markup()


def get_admin_pagination_keyboard(
    current_page: int,
    total_pages: int,
    filter_type: str = "all"
) -> InlineKeyboardMarkup:
    """
    Клавиатура пагинации для списка бронирований.
    Показывает кнопки перехода между страницами.

    Args:
        current_page: Текущая страница (начиная с 0)
        total_pages: Всего страниц
        filter_type: Активный фильтр (для сохранения при навигации)

    Returns:
        Строка с кнопками ◀ [1/5] ▶ + кнопки фильтров

    Пример: ◀ Пред | 2 / 5 | След ▶
    """
    builder = InlineKeyboardBuilder()

    # Кнопка "Предыдущая страница"
    if current_page > 0:
        builder.button(
            text="◀ Пред",
            callback_data=f"admin_bk_page:{current_page - 1}:{filter_type}"
        )
    else:
        # Заглушка — кнопка есть, но не работает (для красивой вёрстки)
        builder.button(text=" ", callback_data="ignore")

    # Индикатор текущей страницы
    builder.button(
        text=f"{current_page + 1} / {total_pages}",
        callback_data="ignore"
    )

    # Кнопка "Следующая страница"
    if current_page < total_pages - 1:
        builder.button(
            text="След ▶",
            callback_data=f"admin_bk_page:{current_page + 1}:{filter_type}"
        )
    else:
        builder.button(text=" ", callback_data="ignore")

    # Кнопки управления (фильтр и меню)
    builder.button(text="🔍 Фильтр", callback_data="admin:bookings")
    builder.button(text="◀ Меню", callback_data="admin:main")

    # Строка пагинации — 3 кнопки, потом кнопки управления — 2
    builder.adjust(3, 2)
    return builder.as_markup()


def get_schedule_mode_choice_keyboard() -> InlineKeyboardMarkup:
    """Первичный выбор режима расписания."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Стандартное — задаётся один раз", callback_data="sched_mode:standard")
    builder.button(text="🗓 По месяцам — вручную каждый месяц", callback_data="sched_mode:monthly")
    builder.button(text="◀ Главное меню", callback_data="admin:main")
    builder.adjust(1)
    return builder.as_markup()


def get_admin_schedule_keyboard() -> InlineKeyboardMarkup:
    """
    Меню управления расписанием (временными слотами).
    Кнопки отображаются ПОД календарём текущего месяца.
    Используется только в старом флоу — заменяется режимными клавиатурами.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="⚙️ Стандартное расписание", callback_data="admin:default_schedule")
    builder.button(text="📅 Создать расписание на месяц", callback_data="admin:schedule_rule")
    builder.button(text="✏️ Редактировать расписание", callback_data="admin:schedule_edit")
    builder.button(text="◀ Главное меню", callback_data="admin:main")
    builder.adjust(1)
    return builder.as_markup()


def get_admin_time_slots_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура выбора времени для добавления в расписание.
    Администратор добавляет рабочие часы нажатием кнопок.

    Показывает стандартные рабочие часы с шагом 30 минут (9:00–20:00).

    Returns:
        Клавиатура с временными слотами для добавления
    """
    builder = InlineKeyboardBuilder()

    # Генерируем временные слоты с 9:00 до 20:00 каждые 30 минут
    times = []
    for hour in range(9, 21):
        times.append(f"{hour:02d}:00")
        if hour < 20:  # Не добавляем 20:30
            times.append(f"{hour:02d}:30")

    for t in times:
        builder.button(
            text=f"🕐 {t}",
            callback_data=f"admin_add_slot:{t}"
        )

    builder.button(text="✅ Готово", callback_data="admin_sched:done")
    builder.button(text="❌ Отмена", callback_data="admin:schedule")

    # По 4 кнопки времени в ряд, потом 2 кнопки управления
    builder.adjust(4, 4, 4, 4, 4, 4, 2)
    return builder.as_markup()


def get_admin_slots_list_keyboard(slots: List[Dict]) -> InlineKeyboardMarkup:
    """
    Список слотов конкретного дня с возможностью удаления каждого.
    Используется в просмотре расписания дня.

    Args:
        slots: Список всех слотов дня (свободных и занятых)

    Returns:
        Клавиатура со слотами и кнопками удаления
    """
    builder = InlineKeyboardBuilder()

    for slot in slots:
        time_str = slot["slot_time"][:5]
        status = "🟢" if slot["is_available"] else "🔴"

        # Информационная кнопка (не нажимается)
        builder.button(
            text=f"{status} {time_str}",
            callback_data="ignore"
        )

        # Кнопка удаления слота
        if slot["is_available"]:
            builder.button(
                text="🗑",
                callback_data=f"admin_del_slot:{slot['id']}"
            )
        else:
            # Занятый слот нельзя удалить
            builder.button(text="📌", callback_data="ignore")

    builder.button(text="◀ К расписанию", callback_data="admin:schedule")

    # По 2 кнопки в ряд (время + удалить), последняя отдельно
    row_widths = [2] * len(slots) + [1]
    builder.adjust(*row_widths)
    return builder.as_markup()


COMFORT_OPTIONS = {
    "coffee":  "☕ Кофе",
    "tea":     "🍵 Чай",
    "sweets":  "🍬 Сладости",
    "blanket": "🧣 Плед",
}


def get_survey_comfort_keyboard(selected: list = None) -> InlineKeyboardMarkup:
    """
    Мультивыбор: что подготовить к визиту клиента.
    Уже выбранные пункты отмечены ✅.
    Кнопка «Готово» сохраняет выбор и завершает опрос.
    """
    selected = selected or []
    builder = InlineKeyboardBuilder()

    for key, label in COMFORT_OPTIONS.items():
        prefix = "✅ " if key in selected else ""
        builder.button(text=f"{prefix}{label}", callback_data=f"survey_comfort:{key}")

    builder.button(text="➡️ Готово", callback_data="survey_comfort:done")

    # 4 опции по 2 в ряд, кнопка готово отдельно
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def get_delete_confirm_keyboard(booking_id: str) -> InlineKeyboardMarkup:
    """
    Клавиатура подтверждения удаления бронирования.
    Двойное подтверждение предотвращает случайное удаление.

    Args:
        booking_id: UUID бронирования для удаления

    Returns:
        Клавиатура с кнопками подтверждения и отмены
    """
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🗑 Да, удалить",
        callback_data=f"admin_bk_delete_confirm:{booking_id}"
    )
    builder.button(
        text="◀ Отмена",
        callback_data=f"admin_bk_view:{booking_id}"
    )

    builder.adjust(1)
    return builder.as_markup()


# ===================================================
# КЛАВИАТУРЫ ГЕНЕРАТОРА И РЕДАКТОРА РАСПИСАНИЯ
# ===================================================

WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def get_weekday_keyboard(
    selected: set,
    cancel_cb: str = "admin:schedule",
) -> InlineKeyboardMarkup:
    """
    Клавиатура выбора дней недели (мультивыбор).
    ✅ — выбран, ⬜ — не выбран.

    Args:
        selected: Множество индексов выбранных дней (0=Пн, 6=Вс)
        cancel_cb: callback_data для кнопки «Отмена»
    """
    builder = InlineKeyboardBuilder()
    for i, name in enumerate(WEEKDAYS_RU):
        mark = "✅" if i in selected else "⬜"
        builder.button(text=f"{mark} {name}", callback_data=f"rule_wd:{i}")
    builder.adjust(4, 3)
    builder.row(
        InlineKeyboardButton(text="✅ Готово →", callback_data="rule_wd_done"),
        InlineKeyboardButton(text="❌ Отмена", callback_data=cancel_cb),
    )
    return builder.as_markup()


def get_hour_keyboard(
    hours: list,
    cb_prefix: str,
    cancel_cb: str = "admin:schedule",
) -> InlineKeyboardMarkup:
    """
    Универсальная клавиатура выбора часа.

    Args:
        hours: Список доступных часов [8, 9, 10, ...]
        cb_prefix: Префикс callback_data (rule_start / rule_end)
        cancel_cb: callback_data для кнопки «← Назад»
    """
    builder = InlineKeyboardBuilder()
    for h in hours:
        builder.button(text=f"{h:02d}:00", callback_data=f"{cb_prefix}:{h}")
    builder.adjust(4)
    builder.row(InlineKeyboardButton(text="← Назад", callback_data=cancel_cb))
    return builder.as_markup()


def get_slot_edit_keyboard(
    slots: list,
    removed_ids: set,
    date_str: str,
) -> InlineKeyboardMarkup:
    """
    Клавиатура редактирования слотов дня.
    ✅ — слот активен, ❌ — помечен для удаления, 🔒 — занят бронированием.
    """
    builder = InlineKeyboardBuilder()
    for slot in slots:
        slot_id = slot["id"]
        time_str = slot["slot_time"][:5]
        is_booked = not slot["is_available"]
        if is_booked:
            builder.button(text=f"🔒 {time_str}", callback_data="edit_slot_ignore")
        elif slot_id in removed_ids:
            builder.button(text=f"❌ {time_str}", callback_data=f"edit_slot_toggle:{slot_id}")
        else:
            builder.button(text=f"✅ {time_str}", callback_data=f"edit_slot_toggle:{slot_id}")
    builder.adjust(4)
    builder.row(InlineKeyboardButton(
        text="💾 Сохранить изменения", callback_data="edit_slot_save"
    ))
    builder.row(
        InlineKeyboardButton(text="🗑 Удалить весь день", callback_data=f"edit_day_delete:{date_str}"),
        InlineKeyboardButton(text="← Отмена", callback_data=f"admin_ed_day_action:{date_str}"),
    )
    builder.row(InlineKeyboardButton(text="◀ Главное меню", callback_data="admin:main"))
    return builder.as_markup()
