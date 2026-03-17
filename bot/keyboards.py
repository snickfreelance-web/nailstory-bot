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
        📋 Все бронирования  — список записей с фильтрами
        💅 Управление услугами — добавить/удалить/скрыть
        📅 Расписание        — управление слотами
        📊 Статистика        — сводка по записям
    """
    builder = InlineKeyboardBuilder()

    builder.button(text="📋 Бронирования", callback_data="admin:bookings")
    builder.button(text="💅 Услуги", callback_data="admin:services")
    builder.button(text="📅 Расписание", callback_data="admin:schedule")
    builder.button(text="📊 Статистика", callback_data="admin:stats")

    # Две кнопки в ряд
    builder.adjust(2)

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
    page: int = 0
) -> InlineKeyboardMarkup:
    """
    Клавиатура действий с конкретным бронированием.

    Args:
        booking_id: UUID бронирования
        current_status: Текущий статус для показа доступных действий
        page: Текущая страница списка (для возврата назад)

    Returns:
        Клавиатура с действиями

    Доступные действия зависят от статуса:
        pending:   [Подтвердить] [Перенести] [Отменить] [Удалить]
        confirmed: [Перенести] [Отменить] [Удалить]
        cancelled: [Удалить] [Восстановить]
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

    if current_status == "cancelled":
        builder.button(
            text="🔄 Восстановить",
            callback_data=f"admin_bk_restore:{booking_id}"
        )

    builder.button(
        text="🗑 Удалить",
        callback_data=f"admin_bk_delete:{booking_id}"
    )

    # Кнопка возврата к списку с сохранением страницы пагинации
    builder.button(
        text="◀ К списку",
        callback_data=f"admin_bk_list:{page}"
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


def get_admin_schedule_keyboard() -> InlineKeyboardMarkup:
    """
    Меню управления расписанием (временными слотами).

    Кнопки:
        ➕ Добавить рабочий день — создать слоты для новой даты
        📅 Просмотр дня          — посмотреть слоты конкретного дня
        🗑 Удалить слот          — убрать конкретное время
        ◀ Главное меню
    """
    builder = InlineKeyboardBuilder()

    builder.button(text="➕ Добавить рабочий день", callback_data="admin_sched:add_day")
    builder.button(text="📅 Просмотр дня", callback_data="admin_sched:view_day")
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


def get_schedule_mode_choice_keyboard() -> InlineKeyboardMarkup:
    """
    Главное меню раздела «Расписание».

    Кнопки:
        📅 Создать расписание — генератор по правилу (дни+часы+интервал)
        ✏️ Редактировать расписание — просмотр календаря и правка дней
        ➕ Добавить день вручную — старый ручной режим (кнопки-слоты)
        ◀ Главное меню
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Создать расписание на месяц", callback_data="admin_sched:create_rule")
    builder.button(text="✏️ Редактировать расписание", callback_data="admin_sched:edit_month")
    builder.button(text="➕ Добавить день вручную", callback_data="admin_sched:add_day")
    builder.button(text="◀ Главное меню", callback_data="admin:main")
    builder.adjust(1)
    return builder.as_markup()


def get_weekday_keyboard(selected: set) -> InlineKeyboardMarkup:
    """
    Мультивыбор дней недели с тогглами.

    Args:
        selected: Множество выбранных дней (0=Пн, 1=Вт, ..., 6=Вс)

    Кнопки:
        [✅ Пн] [⬜ Вт] ... — нажать, чтобы переключить
        [✅ Готово] — подтвердить выбор
    """
    builder = InlineKeyboardBuilder()
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    for i, name in enumerate(days):
        mark = "✅" if i in selected else "⬜"
        builder.button(text=f"{mark} {name}", callback_data=f"sched_wd:{i}")
    builder.button(text="✅ Готово →", callback_data="sched_wd:done")
    builder.adjust(4, 3, 1)
    return builder.as_markup()


def get_hour_keyboard(
    start_h: int,
    end_h: int,
    cb_prefix: str,
    cancel_cb: str,
) -> InlineKeyboardMarkup:
    """
    Универсальная клавиатура выбора часа.

    Args:
        start_h: Первый час (включительно)
        end_h: Последний час (включительно)
        cb_prefix: Префикс callback_data, итоговый формат: "prefix:HH:00"
        cancel_cb: callback_data для кнопки «Отмена»
    """
    builder = InlineKeyboardBuilder()
    for h in range(start_h, end_h + 1):
        builder.button(text=f"{h:02d}:00", callback_data=f"{cb_prefix}:{h:02d}:00")
    builder.button(text="❌ Отмена", callback_data=cancel_cb)
    # По 4 часа в ряд, отмена отдельно
    count = end_h - start_h + 1
    rows = [4] * (count // 4)
    if count % 4:
        rows.append(count % 4)
    rows.append(1)
    builder.adjust(*rows)
    return builder.as_markup()


def get_interval_keyboard(cb_prefix: str) -> InlineKeyboardMarkup:
    """
    Выбор интервала между слотами: 15/30/60 мин + произвольный.
    Используется одинаково при создании расписания и при редактировании дня.

    Args:
        cb_prefix: Префикс callback, итоговый формат: "prefix:15" / "prefix:custom"
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="⏱ 15 минут", callback_data=f"{cb_prefix}:15")
    builder.button(text="⏱ 30 минут", callback_data=f"{cb_prefix}:30")
    builder.button(text="⏱ 60 минут", callback_data=f"{cb_prefix}:60")
    builder.button(text="✏️ Свой интервал…", callback_data=f"{cb_prefix}:custom")
    builder.adjust(3, 1)
    return builder.as_markup()


def build_admin_month_calendar(
    year: int,
    month: int,
    schedule_info: List[Dict],
) -> InlineKeyboardMarkup:
    """
    Месячный календарь для просмотра/редактирования расписания.

    Дни со слотами — кликабельные кнопки.
    Кастомные дни (is_custom=True) — помечены иконкой ✏️.
    Дни без слотов — пустые (неактивные).
    Навигация: ◀ Пред / ▶ След.

    Args:
        year: Год
        month: Месяц (1-12)
        schedule_info: Результат get_month_schedule_info()
    """
    import calendar as cal_mod
    from datetime import date

    builder = InlineKeyboardBuilder()

    # Заголовок месяца
    months_ru = [
        "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
        "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
    ]
    builder.button(
        text=f"── {months_ru[month]} {year} ──",
        callback_data="sched_cal_ignore"
    )
    builder.adjust(1)

    # Заголовки дней недели
    for day_name in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]:
        builder.button(text=day_name, callback_data="sched_cal_ignore")

    # Индекс данных расписания по дате
    info_by_date = {item["date"]: item for item in schedule_info}

    # Первый день месяца (weekday: 0=пн, 6=вс)
    first_weekday = cal_mod.monthrange(year, month)[0]
    days_in_month = cal_mod.monthrange(year, month)[1]

    # Пустые ячейки до первого дня
    for _ in range(first_weekday):
        builder.button(text=" ", callback_data="sched_cal_ignore")

    today = date.today()

    for day in range(1, days_in_month + 1):
        date_str = f"{year}-{month:02d}-{day:02d}"
        info = info_by_date.get(date_str)

        if info:
            # День со слотами
            label = str(day)
            if info["is_custom"]:
                label = f"✏️{day}"
            builder.button(text=label, callback_data=f"edit_day:{date_str}")
        else:
            # День без слотов — неактивный
            builder.button(text=f"· {day}", callback_data="sched_cal_ignore")

    # Добираем пустые ячейки до конца последней строки
    total_cells = first_weekday + days_in_month
    remainder = total_cells % 7
    if remainder:
        for _ in range(7 - remainder):
            builder.button(text=" ", callback_data="sched_cal_ignore")

    # Навигация
    prev_year, prev_month = (year, month - 1) if month > 1 else (year - 1, 12)
    next_year, next_month = (year, month + 1) if month < 12 else (year + 1, 1)

    today = date.today()
    if (prev_year, prev_month) >= (today.year, today.month):
        builder.button(text="◀", callback_data=f"sched_cal_nav:{prev_year}:{prev_month}")
    else:
        builder.button(text=" ", callback_data="sched_cal_ignore")

    builder.button(text=" ", callback_data="sched_cal_ignore")

    builder.button(text="▶", callback_data=f"sched_cal_nav:{next_year}:{next_month}")

    builder.button(text="◀ К расписанию", callback_data="admin:schedule")

    # Заголовок + 7 дней нед + все дни + навигация (3) + назад (1)
    total_day_cells = first_weekday + days_in_month
    if total_day_cells % 7:
        total_day_cells += 7 - (total_day_cells % 7)

    # Строим adjust: 1 (заголовок), 7 (дни нед), строки по 7, 3 (навигация), 1 (назад)
    rows = [1, 7] + [7] * (total_day_cells // 7) + [3, 1]
    builder.adjust(*rows)

    return builder.as_markup()


def get_day_actions_keyboard(date_str: str, has_free_slots: bool = True) -> InlineKeyboardMarkup:
    """
    Действия для конкретного дня расписания.

    Кнопки:
        ✏️ Редактировать — изменить время начала/конца/интервал
        🗑 Удалить день — удалить все свободные слоты за день
        ◀ Назад — вернуться к календарю
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Редактировать", callback_data=f"edit_day_action:edit:{date_str}")
    if has_free_slots:
        builder.button(text="🗑 Удалить день", callback_data=f"edit_day_action:delete:{date_str}")
    builder.button(text="◀ Назад", callback_data="admin_sched:edit_month")
    builder.adjust(1)
    return builder.as_markup()


def get_custom_days_confirm_keyboard(
    custom_dates: List[str],
    keep_set: set,
) -> InlineKeyboardMarkup:
    """
    Список кастомных дней с тогглами.
    ✅ = оставить кастомным (в keep_set)
    ⬜ = применить общее правило (не в keep_set)

    Args:
        custom_dates: Список дат ["YYYY-MM-DD", ...]
        keep_set: Множество дат, которые нужно оставить кастомными

    Кнопки:
        [✅ 15 мар] / [⬜ 15 мар] — тоглы
        [✅ Подтвердить]
    """
    from bot.utils.validators import format_date_ru

    builder = InlineKeyboardBuilder()
    for date_str in custom_dates:
        mark = "✅" if date_str in keep_set else "⬜"
        label = format_date_ru(date_str)  # "15 марта"
        builder.button(
            text=f"{mark} {label}",
            callback_data=f"sched_custom_toggle:{date_str}"
        )
    builder.button(text="✅ Подтвердить", callback_data="sched_custom_confirm")
    builder.adjust(1)
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
