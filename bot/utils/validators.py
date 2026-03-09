# ===================================================
# utils/validators.py — Валидация пользовательского ввода
# ===================================================
# Функции для проверки корректности данных,
# которые вводят пользователи и администраторы.
# ===================================================

import re
from datetime import datetime, date


def normalize_phone(phone: str) -> str:
    """
    Нормализует номер телефона к единому формату +7XXXXXXXXXX.
    Принимает телефоны в любом формате.

    Примеры входных данных:
        "8 (916) 123-45-67" → "+79161234567"
        "+7 916 123 45 67"  → "+79161234567"
        "89161234567"       → "+79161234567"
        "79161234567"       → "+79161234567"

    Args:
        phone: Строка с номером телефона

    Returns:
        Нормализованный номер или исходную строку если не удалось обработать
    """
    # Оставляем только цифры и знак +
    digits_only = re.sub(r'[^\d+]', '', phone)

    # Убираем знак + для подсчёта цифр
    digits = re.sub(r'[^\d]', '', digits_only)

    # Российский номер: 11 цифр, начинается с 7 или 8
    if len(digits) == 11:
        if digits.startswith('8'):
            return '+7' + digits[1:]
        elif digits.startswith('7'):
            return '+' + digits

    # Если 10 цифр — добавляем +7 (только код без 8/7)
    if len(digits) == 10:
        return '+7' + digits

    # Если уже есть + — возвращаем как есть
    return phone


def is_valid_phone(phone: str) -> bool:
    """
    Проверяет, является ли строка корректным российским номером.
    Используется при ручном вводе телефона (не через кнопку контакта).

    Args:
        phone: Строка с номером телефона

    Returns:
        True если номер валидный

    Валидные форматы:
        +79161234567, 89161234567, 79161234567,
        8 916 123-45-67, +7 (916) 123 45 67
    """
    digits = re.sub(r'[^\d]', '', phone)

    # Российский номер должен содержать 10 или 11 цифр
    if len(digits) not in (10, 11):
        return False

    # Если 11 цифр — должен начинаться с 7 или 8
    if len(digits) == 11 and digits[0] not in ('7', '8'):
        return False

    return True


def is_valid_price(price_str: str) -> bool:
    """
    Проверяет, является ли строка корректной ценой.
    Цена должна быть положительным целым числом.

    Args:
        price_str: Строка для проверки

    Returns:
        True если строка — допустимая цена

    Валидные значения: "1500", "500", "3000"
    Невалидные: "-100", "abc", "15.5", "0"
    """
    try:
        price = int(price_str.strip())
        return price > 0
    except ValueError:
        return False


def parse_date(date_str: str) -> tuple:
    """
    Разбирает строку даты в формате DD.MM.YYYY.
    Используется когда администратор вводит дату текстом.

    Args:
        date_str: Строка с датой, например "15.03.2024"

    Returns:
        Tuple (year: int, month: int, day: int, date_obj: date)
        или None если дата невалидна

    Обрабатывает форматы:
        "15.03.2024", "15/03/2024", "15-03-2024"
    """
    # Нормализуем разделители
    normalized = date_str.strip().replace('/', '.').replace('-', '.')

    try:
        dt = datetime.strptime(normalized, "%d.%m.%Y")
        d = dt.date()

        # Проверяем что дата не в прошлом
        if d <= date.today():
            return None

        return (d.year, d.month, d.day, d)

    except ValueError:
        return None


def format_date_ru(date_str: str) -> str:
    """
    Форматирует дату из "YYYY-MM-DD" в читаемый русский формат.
    Используется в сообщениях пользователю.

    Args:
        date_str: Дата в формате "2024-03-15"

    Returns:
        "15 марта 2024" или исходную строку при ошибке
    """
    months = {
        1: "января", 2: "февраля", 3: "марта", 4: "апреля",
        5: "мая", 6: "июня", 7: "июля", 8: "августа",
        9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
    }

    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{d.day} {months[d.month]} {d.year}"
    except Exception:
        return date_str


def format_time_ru(time_str: str) -> str:
    """
    Форматирует время из "HH:MM:SS" или "HH:MM" в "HH:MM".
    Убирает секунды если они есть.

    Args:
        time_str: Время "10:00:00" или "10:00"

    Returns:
        "10:00"
    """
    return time_str[:5]


def format_status_ru(status: str) -> str:
    """
    Переводит статус бронирования на русский.

    Args:
        status: "pending", "confirmed", "cancelled"

    Returns:
        Читаемый русский статус с эмодзи
    """
    statuses = {
        "pending": "⏳ Ожидает подтверждения",
        "confirmed": "✅ Подтверждена",
        "cancelled": "❌ Отменена",
    }
    return statuses.get(status, status)
