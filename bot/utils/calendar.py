# ===================================================
# utils/calendar.py — Генератор инлайн-календаря
# ===================================================
# Этот модуль создаёт интерактивный инлайн-календарь
# прямо в Telegram-сообщении.
#
# Внешний вид:
#   ◀  Март 2024  ▶
#   Пн  Вт  Ср  Чт  Пт  Сб  Вс
#   ·   ·   ·   ✅  ·   ✅  ·
#   ✅  ·   ✅  ✅  ·   ·   ·
#
# ✅ — есть свободные слоты, можно нажать
# ·  — нет слотов или прошедшая дата, нажать нельзя
#
# Данные о свободных датах приходят из database.py
# ===================================================

import calendar
from datetime import date, datetime
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List


# Короткие названия дней недели для шапки календаря
WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

# Названия месяцев на русском
MONTHS_RU = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
}


def build_calendar(
    year: int,
    month: int,
    available_dates: List[str],
) -> InlineKeyboardMarkup:
    """
    Строит инлайн-клавиатуру в виде календаря на указанный месяц.

    Алгоритм:
    1. Рисуем заголовок (название месяца + кнопки ◀▶)
    2. Рисуем строку с днями недели (Пн Вт Ср...)
    3. Для каждой недели рисуем строку кнопок:
       - Если день доступен → кнопка с callback_data
       - Если нет → кнопка с текстом "·" и callback "ignore"

    Особенности:
    - Кнопка ◀ скрыта для текущего и прошлых месяцев
    - Если available_dates пуст — показывается заглушка «нет дат»

    Args:
        year: Год для отображения
        month: Месяц 1-12 для отображения
        available_dates: Список дат со свободными слотами
                         Формат: ["2024-03-05", "2024-03-12"]

    Returns:
        InlineKeyboardMarkup — готовая клавиатура для отправки
    """

    builder = InlineKeyboardBuilder()
    today = date.today()

    # ---------------------------------------------------
    # Строка 1: Навигация по месяцам
    # ---------------------------------------------------
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    # Кнопка ◀: скрываем, если просматриваем текущий или прошлый месяц
    is_current_or_past_month = (year, month) <= (today.year, today.month)
    if is_current_or_past_month:
        builder.button(text=" ", callback_data="cal_ignore")
    else:
        builder.button(text="◀", callback_data=f"cal_nav:{prev_year}:{prev_month}")

    # Заголовок с названием месяца
    builder.button(
        text=f"{MONTHS_RU[month]} {year}",
        callback_data="cal_ignore"
    )

    # Кнопка ▶
    builder.button(
        text="▶",
        callback_data=f"cal_nav:{next_year}:{next_month}"
    )

    builder.adjust(3)

    # ---------------------------------------------------
    # Если нет доступных дат — показываем заглушку
    # ---------------------------------------------------
    if not available_dates:
        builder.button(
            text="😔 Нет свободного времени в этом месяце",
            callback_data="cal_ignore"
        )
        builder.button(
            text="▶ Следующий месяц",
            callback_data=f"cal_nav:{next_year}:{next_month}"
        )
        builder.adjust(3, 1, 1)
        return builder.as_markup()

    # ---------------------------------------------------
    # Строка 2: Заголовки дней недели
    # ---------------------------------------------------
    for day_name in WEEKDAYS:
        builder.button(text=day_name, callback_data="cal_ignore")

    # ---------------------------------------------------
    # Строки 3+: Числа месяца
    # ---------------------------------------------------
    month_calendar = calendar.monthcalendar(year, month)

    for week in month_calendar:
        for day_num in week:
            if day_num == 0:
                builder.button(text=" ", callback_data="cal_ignore")
            else:
                day_str = f"{year:04d}-{month:02d}-{day_num:02d}"
                day_date = date(year, month, day_num)

                is_past = day_date <= today
                is_available = day_str in available_dates

                if is_available and not is_past:
                    builder.button(
                        text=f"🟢{day_num}",
                        callback_data=f"cal_date:{day_str}"
                    )
                else:
                    builder.button(
                        text=str(day_num),
                        callback_data="cal_ignore"
                    )

    row_widths = [3, 7] + [7] * len(month_calendar)
    builder.adjust(*row_widths)

    return builder.as_markup()


def build_time_slots_keyboard(slots: list) -> InlineKeyboardMarkup:
    """
    Строит клавиатуру выбора времени из списка доступных слотов.
    Кнопки расставляются по 3 в ряд.

    Args:
        slots: Список словарей слотов из database.get_available_slots()
               Каждый словарь содержит: id, slot_time

    Returns:
        InlineKeyboardMarkup с кнопками времени + кнопка отмены

    Пример отображения:
        [10:00] [11:00] [12:00]
        [14:00] [15:30] [16:00]
        [  ❌ Отмена  ]
    """
    builder = InlineKeyboardBuilder()

    for slot in slots:
        # Форматируем время: "10:00:00" → "10:00"
        time_str = slot["slot_time"][:5]  # Берём первые 5 символов "HH:MM"

        # callback_data содержит ID слота и время для FSM
        # Формат: "slot:uuid:HH:MM"
        builder.button(
            text=f"🕐 {time_str}",
            callback_data=f"slot:{slot['id']}:{time_str}"
        )

    # Кнопки по 3 в ряд
    builder.adjust(3)

    # Добавляем кнопку "Назад" отдельной строкой
    builder.row(
        InlineKeyboardButton(text="◀ Назад к дате", callback_data="back_to_date")
    )

    return builder.as_markup()


def build_admin_calendar(
    year: int,
    month: int,
    dates_with_slots: List[str],
) -> InlineKeyboardMarkup:
    """
    Строит инлайн-клавиатуру выбора даты для админского флоу «Добавить рабочий день».

    Отличия от клиентского build_calendar():
    - ВСЕ будущие даты кликабельны (администратор может добавить слоты на любой день)
    - Даты с уже созданными слотами помечаются 📅
    - Навигация: admin_cal_nav:YYYY:M  (не cal_nav:)
    - Выбор даты: admin_cal_date:YYYY-MM-DD  (не cal_date:)
    - Нет заглушки «нет дат» — в отличие от клиентского календаря

    Args:
        year: Год для отображения
        month: Месяц 1-12
        dates_with_slots: Даты, на которые уже созданы слоты (маркер 📅)

    Returns:
        InlineKeyboardMarkup — готовая клавиатура
    """
    builder = InlineKeyboardBuilder()
    today = date.today()

    # Строка 1: навигация
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    is_current_or_past_month = (year, month) <= (today.year, today.month)
    if is_current_or_past_month:
        builder.button(text=" ", callback_data="cal_ignore")
    else:
        builder.button(text="◀", callback_data=f"admin_cal_nav:{prev_year}:{prev_month}")

    builder.button(text=f"{MONTHS_RU[month]} {year}", callback_data="cal_ignore")
    builder.button(text="▶", callback_data=f"admin_cal_nav:{next_year}:{next_month}")
    builder.adjust(3)

    # Строка 2: заголовки дней недели
    for day_name in WEEKDAYS:
        builder.button(text=day_name, callback_data="cal_ignore")

    # Строки 3+: числа месяца
    month_calendar = calendar.monthcalendar(year, month)
    for week in month_calendar:
        for day_num in week:
            if day_num == 0:
                builder.button(text=" ", callback_data="cal_ignore")
            else:
                day_str = f"{year:04d}-{month:02d}-{day_num:02d}"
                day_date = date(year, month, day_num)
                is_past = day_date <= today

                if is_past:
                    builder.button(text=str(day_num), callback_data="cal_ignore")
                elif day_str in dates_with_slots:
                    builder.button(text=f"📅{day_num}", callback_data=f"admin_cal_date:{day_str}")
                else:
                    builder.button(text=str(day_num), callback_data=f"admin_cal_date:{day_str}")

    row_widths = [3, 7] + [7] * len(month_calendar)
    builder.adjust(*row_widths)

    return builder.as_markup()


def get_current_month_year():
    """
    Возвращает текущий год и месяц.
    Вспомогательная функция — используется при первом
    открытии календаря (показываем текущий месяц).

    Returns:
        Tuple (year: int, month: int)
    """
    today = date.today()
    return today.year, today.month
