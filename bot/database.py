# ===================================================
# database.py — Все взаимодействия с базой данных Supabase
# ===================================================
# Этот модуль — единственное место в проекте, которое
# знает о Supabase. Все остальные модули вызывают функции
# из этого файла и не работают с БД напрямую.
#
# Паттерн: Repository (Репозиторий) — изолируем логику
# работы с данными от бизнес-логики бота.
# ===================================================

from supabase import create_client, Client
from bot.config import settings
from typing import Optional, List, Dict, Any
from datetime import date, time
import logging

logger = logging.getLogger(__name__)

# ===================================================
# ИНИЦИАЛИЗАЦИЯ КЛИЕНТА SUPABASE
# ===================================================

def get_supabase_client() -> Client:
    """
    Создаёт и возвращает клиент Supabase.
    Вызывается один раз при старте приложения.

    create_client() принимает URL и ключ из настроек.
    Клиент автоматически добавляет Authorization-заголовок
    ко всем запросам.
    """
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)


# Создаём глобальный клиент — он потокобезопасен и переиспользуется
supabase: Client = get_supabase_client()


# ===================================================
# УСЛУГИ (SERVICES)
# ===================================================

async def get_all_services(active_only: bool = True) -> List[Dict]:
    """
    Получает список услуг из таблицы services.

    Args:
        active_only: если True — возвращает только активные услуги
                     (is_active = true). Для клиентов передаём True,
                     для админа — False (видит все).

    Returns:
        Список словарей с полями: id, name, duration_min, price, is_active

    Пример запроса в Supabase:
        SELECT * FROM services WHERE is_active = true ORDER BY name
    """
    try:
        query = supabase.table("services").select("*").order("name")

        if active_only:
            query = query.eq("is_active", True)

        response = query.execute()
        return response.data or []

    except Exception as e:
        logger.error(f"Ошибка получения услуг: {e}")
        return []


async def get_service_by_id(service_id: str) -> Optional[Dict]:
    """
    Получает одну услугу по её UUID.

    Args:
        service_id: UUID услуги из таблицы services

    Returns:
        Словарь с данными услуги или None, если не найдена
    """
    try:
        response = (
            supabase.table("services")
            .select("*")
            .eq("id", service_id)
            .single()  # Ожидаем ровно одну запись
            .execute()
        )
        return response.data

    except Exception as e:
        logger.error(f"Ошибка получения услуги {service_id}: {e}")
        return None


async def add_service(name: str, duration_min: int, price: int) -> Optional[Dict]:
    """
    Добавляет новую услугу в таблицу services.

    Args:
        name: Название услуги (например "Маникюр классический")
        duration_min: Длительность в минутах (например 60)
        price: Цена в рублях (например 1500)

    Returns:
        Созданная запись или None при ошибке

    Supabase автоматически генерирует UUID и created_at.
    is_active по умолчанию = true (задаётся в схеме БД).
    """
    try:
        response = (
            supabase.table("services")
            .insert({
                "name": name,
                "duration_min": duration_min,
                "price": price,
                "is_active": True,
            })
            .execute()
        )
        return response.data[0] if response.data else None

    except Exception as e:
        logger.error(f"Ошибка добавления услуги: {e}")
        return None


async def toggle_service_status(service_id: str, is_active: bool) -> bool:
    """
    Включает или отключает услугу (не удаляет, а скрывает от клиентов).
    Это "мягкое удаление" — данные сохраняются для истории бронирований.

    Args:
        service_id: UUID услуги
        is_active: True = показывать клиентам, False = скрыть

    Returns:
        True если обновление прошло успешно
    """
    try:
        supabase.table("services").update({"is_active": is_active}).eq("id", service_id).execute()
        return True

    except Exception as e:
        logger.error(f"Ошибка изменения статуса услуги: {e}")
        return False


async def delete_service(service_id: str) -> bool:
    """
    Полностью удаляет услугу из БД.
    ⚠️ Используйте только если у услуги нет бронирований.
    Иначе используйте toggle_service_status(False).

    Args:
        service_id: UUID услуги

    Returns:
        True если удаление прошло успешно
    """
    try:
        supabase.table("services").delete().eq("id", service_id).execute()
        return True

    except Exception as e:
        logger.error(f"Ошибка удаления услуги: {e}")
        return False


async def service_has_bookings(service_id: str) -> bool:
    """
    Проверяет, есть ли бронирования для данной услуги.
    Используется перед удалением — нельзя удалять услугу
    с историей бронирований (нарушит ссылочную целостность).

    Returns:
        True если существует хотя бы одно бронирование
    """
    try:
        response = (
            supabase.table("bookings")
            .select("id", count="exact")
            .eq("service_id", service_id)
            .execute()
        )
        return (response.count or 0) > 0

    except Exception as e:
        logger.error(f"Ошибка проверки бронирований услуги: {e}")
        return True  # При ошибке считаем что бронирования есть (безопасно)


# ===================================================
# СЛОТЫ ВРЕМЕНИ (TIME_SLOTS)
# ===================================================

async def get_available_dates(year: int, month: int) -> List[str]:
    """
    Возвращает список дат в указанном месяце,
    в которых есть хотя бы один свободный слот.
    Используется для подсветки дат в календаре.

    Args:
        year: Год (например 2024)
        month: Месяц 1-12

    Returns:
        Список строк в формате "YYYY-MM-DD"
        Например: ["2024-03-05", "2024-03-07", "2024-03-12"]
    """
    try:
        # Формируем границы месяца для фильтрации
        # Supabase принимает даты в формате ISO: "2024-03-01"
        month_str = f"{year:04d}-{month:02d}"
        start_date = f"{month_str}-01"

        # Последний день месяца: берём первый день следующего и вычитаем 1
        if month == 12:
            end_date = f"{year + 1:04d}-01-01"
        else:
            end_date = f"{year:04d}-{month + 1:02d}-01"

        response = (
            supabase.table("time_slots")
            .select("slot_date")
            .eq("is_available", True)
            .gte("slot_date", start_date)   # >= начало месяца
            .lt("slot_date", end_date)       # < начало следующего месяца
            .execute()
        )

        if not response.data:
            return []

        # Убираем дубликаты (у одной даты может быть много слотов)
        dates = list(set(row["slot_date"] for row in response.data))
        return sorted(dates)

    except Exception as e:
        logger.error(f"Ошибка получения доступных дат: {e}")
        return []


async def get_available_slots(slot_date: str) -> List[Dict]:
    """
    Возвращает все свободные временные слоты для конкретной даты.
    Сортируем по времени чтобы отображались в хронологическом порядке.

    Args:
        slot_date: Дата в формате "YYYY-MM-DD"

    Returns:
        Список словарей с полями: id, slot_date, slot_time, is_available
        Например: [{"id": "uuid", "slot_date": "2024-03-05", "slot_time": "10:00:00"}]
    """
    try:
        response = (
            supabase.table("time_slots")
            .select("*")
            .eq("slot_date", slot_date)
            .eq("is_available", True)
            .order("slot_time")  # Сортируем по времени
            .execute()
        )
        return response.data or []

    except Exception as e:
        logger.error(f"Ошибка получения слотов для {slot_date}: {e}")
        return []


async def add_time_slot(slot_date: str, slot_time: str) -> Optional[Dict]:
    """
    Добавляет один временной слот (рабочее время) для заданной даты.
    Вызывается администратором при настройке расписания.

    Args:
        slot_date: Дата в формате "YYYY-MM-DD"
        slot_time: Время в формате "HH:MM" или "HH:MM:SS"

    Returns:
        Созданная запись или None при ошибке
    """
    try:
        response = (
            supabase.table("time_slots")
            .insert({
                "slot_date": slot_date,
                "slot_time": slot_time,
                "is_available": True,
            })
            .execute()
        )
        return response.data[0] if response.data else None

    except Exception as e:
        logger.error(f"Ошибка добавления слота: {e}")
        return None


async def mark_slot_unavailable(slot_id: str) -> bool:
    """
    Помечает слот как занятый (is_available = False).
    Вызывается при создании бронирования, чтобы слот
    не был доступен другим клиентам.

    Args:
        slot_id: UUID слота из таблицы time_slots

    Returns:
        True если обновление успешно
    """
    try:
        supabase.table("time_slots").update({"is_available": False}).eq("id", slot_id).execute()
        return True

    except Exception as e:
        logger.error(f"Ошибка блокировки слота {slot_id}: {e}")
        return False


async def mark_slot_available(slot_id: str) -> bool:
    """
    Возвращает слот в пул доступных.
    Вызывается при отмене или переносе бронирования.

    Args:
        slot_id: UUID слота

    Returns:
        True если обновление успешно
    """
    try:
        supabase.table("time_slots").update({"is_available": True}).eq("id", slot_id).execute()
        return True

    except Exception as e:
        logger.error(f"Ошибка разблокировки слота {slot_id}: {e}")
        return False


async def get_slot_by_date_time(slot_date: str, slot_time: str) -> Optional[Dict]:
    """
    Ищет слот по дате и времени.
    Используется при переносе бронирования на новое время.

    Args:
        slot_date: Дата "YYYY-MM-DD"
        slot_time: Время "HH:MM" или "HH:MM:SS"

    Returns:
        Словарь с данными слота или None
    """
    try:
        response = (
            supabase.table("time_slots")
            .select("*")
            .eq("slot_date", slot_date)
            .eq("slot_time", slot_time)
            .single()
            .execute()
        )
        return response.data

    except Exception as e:
        logger.error(f"Ошибка поиска слота {slot_date} {slot_time}: {e}")
        return None


async def delete_time_slot(slot_id: str) -> bool:
    """
    Полностью удаляет временной слот из расписания.
    Используется администратором для закрытия времени.

    Args:
        slot_id: UUID слота

    Returns:
        True если удаление успешно
    """
    try:
        supabase.table("time_slots").delete().eq("id", slot_id).execute()
        return True

    except Exception as e:
        logger.error(f"Ошибка удаления слота {slot_id}: {e}")
        return False


async def get_all_slots_for_date(slot_date: str) -> List[Dict]:
    """
    Получает ВСЕ слоты для даты (включая занятые).
    Используется в admin-панели для полного обзора расписания.

    Args:
        slot_date: Дата "YYYY-MM-DD"

    Returns:
        Список всех слотов (свободных и занятых)
    """
    try:
        response = (
            supabase.table("time_slots")
            .select("*")
            .eq("slot_date", slot_date)
            .order("slot_time")
            .execute()
        )
        return response.data or []

    except Exception as e:
        logger.error(f"Ошибка получения всех слотов для {slot_date}: {e}")
        return []


# ===================================================
# БРОНИРОВАНИЯ (BOOKINGS)
# ===================================================

async def create_booking(
    user_id: int,
    username: Optional[str],
    full_name: str,
    phone: str,
    service_id: str,
    slot_id: str,
    booking_date: str,
    booking_time: str,
) -> Optional[Dict]:
    """
    Создаёт новое бронирование в БД и одновременно помечает
    выбранный слот как занятый.

    Это главная функция клиентского флоу — вызывается после
    того, как пользователь отправил номер телефона.

    Args:
        user_id: Telegram ID пользователя (bigint)
        username: @username в Telegram (может быть None)
        full_name: Имя и фамилия из Telegram профиля
        phone: Номер телефона в любом формате
        service_id: UUID выбранной услуги
        slot_id: UUID выбранного слота (для блокировки)
        booking_date: Дата визита "YYYY-MM-DD"
        booking_time: Время визита "HH:MM:SS"

    Returns:
        Созданное бронирование или None при ошибке
    """
    try:
        # Шаг 1: Создаём бронирование со статусом "pending"
        # Статусы: pending (ожидает подтверждения), confirmed, cancelled
        response = (
            supabase.table("bookings")
            .insert({
                "user_id": user_id,
                "username": username,
                "full_name": full_name,
                "phone": phone,
                "service_id": service_id,
                "booking_date": booking_date,
                "booking_time": booking_time,
                "status": "pending",
            })
            .execute()
        )

        booking = response.data[0] if response.data else None

        if booking:
            # Шаг 2: Блокируем слот чтобы он не был виден другим клиентам
            await mark_slot_unavailable(slot_id)
            logger.info(f"Создано бронирование {booking['id']} для пользователя {user_id}")

        return booking

    except Exception as e:
        logger.error(f"Ошибка создания бронирования: {e}")
        return None


async def get_all_bookings(
    status_filter: Optional[str] = None,
    date_filter: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
) -> List[Dict]:
    """
    Получает список бронирований для админ-панели.
    Поддерживает фильтрацию по статусу и дате, а также пагинацию.

    Args:
        status_filter: "pending", "confirmed", "cancelled" или None (все)
        date_filter: Дата в формате "YYYY-MM-DD" или None (все даты)
        limit: Количество записей на страницу (для пагинации)
        offset: Смещение (страница * limit)

    Returns:
        Список бронирований с данными об услуге (JOIN через select)
    """
    try:
        # Запрашиваем бронирование вместе с данными услуги (LEFT JOIN)
        # Синтаксис Supabase: "bookings(*, services(name, price))"
        query = (
            supabase.table("bookings")
            .select("*, services(name, price)")
            .order("booking_date", desc=False)
            .order("booking_time", desc=False)
            .range(offset, offset + limit - 1)  # Пагинация
        )

        if status_filter:
            query = query.eq("status", status_filter)

        if date_filter:
            query = query.eq("booking_date", date_filter)

        response = query.execute()
        return response.data or []

    except Exception as e:
        logger.error(f"Ошибка получения бронирований: {e}")
        return []


async def get_booking_by_id(booking_id: str) -> Optional[Dict]:
    """
    Получает одно бронирование по UUID.
    Используется при редактировании/удалении конкретной записи.

    Args:
        booking_id: UUID бронирования

    Returns:
        Словарь с данными бронирования и услуги
    """
    try:
        response = (
            supabase.table("bookings")
            .select("*, services(name, price)")
            .eq("id", booking_id)
            .single()
            .execute()
        )
        return response.data

    except Exception as e:
        logger.error(f"Ошибка получения бронирования {booking_id}: {e}")
        return None


async def update_booking_status(booking_id: str, new_status: str) -> bool:
    """
    Обновляет статус бронирования.
    Администратор может подтвердить или отменить запись.

    Args:
        booking_id: UUID бронирования
        new_status: "pending", "confirmed" или "cancelled"

    Returns:
        True если обновление успешно
    """
    try:
        supabase.table("bookings").update({"status": new_status}).eq("id", booking_id).execute()
        return True

    except Exception as e:
        logger.error(f"Ошибка обновления статуса бронирования: {e}")
        return False


async def reschedule_booking(
    booking_id: str,
    old_slot_id: str,
    new_slot_id: str,
    new_date: str,
    new_time: str,
) -> bool:
    """
    Переносит бронирование на другое время.
    Атомарно: освобождает старый слот и занимает новый.

    Args:
        booking_id: UUID бронирования
        old_slot_id: UUID старого слота (будет освобождён)
        new_slot_id: UUID нового слота (будет заблокирован)
        new_date: Новая дата "YYYY-MM-DD"
        new_time: Новое время "HH:MM:SS"

    Returns:
        True если перенос прошёл успешно
    """
    try:
        # Шаг 1: Освобождаем старый слот
        await mark_slot_available(old_slot_id)

        # Шаг 2: Занимаем новый слот
        await mark_slot_unavailable(new_slot_id)

        # Шаг 3: Обновляем данные бронирования
        supabase.table("bookings").update({
            "booking_date": new_date,
            "booking_time": new_time,
            "status": "confirmed",  # После переноса автоматически подтверждаем
        }).eq("id", booking_id).execute()

        logger.info(f"Бронирование {booking_id} перенесено на {new_date} {new_time}")
        return True

    except Exception as e:
        logger.error(f"Ошибка переноса бронирования: {e}")
        return False


async def delete_booking(booking_id: str, slot_id: Optional[str] = None) -> bool:
    """
    Удаляет бронирование и освобождает связанный слот.

    Args:
        booking_id: UUID бронирования
        slot_id: UUID слота для освобождения (если известен)

    Returns:
        True если удаление успешно
    """
    try:
        # Если ID слота не передан — ищем его по дате и времени бронирования
        if not slot_id:
            booking = await get_booking_by_id(booking_id)
            if booking:
                slot = await get_slot_by_date_time(
                    booking["booking_date"],
                    booking["booking_time"]
                )
                if slot:
                    slot_id = slot["id"]

        # Освобождаем слот перед удалением бронирования
        if slot_id:
            await mark_slot_available(slot_id)

        # Удаляем само бронирование
        supabase.table("bookings").delete().eq("id", booking_id).execute()
        logger.info(f"Бронирование {booking_id} удалено")
        return True

    except Exception as e:
        logger.error(f"Ошибка удаления бронирования {booking_id}: {e}")
        return False


async def get_bookings_count(status_filter: Optional[str] = None) -> int:
    """
    Возвращает общее количество бронирований (для пагинации).

    Args:
        status_filter: Фильтр по статусу или None для всех

    Returns:
        Количество записей
    """
    try:
        query = supabase.table("bookings").select("id", count="exact")

        if status_filter:
            query = query.eq("status", status_filter)

        response = query.execute()
        return response.count or 0

    except Exception as e:
        logger.error(f"Ошибка подсчёта бронирований: {e}")
        return 0


async def get_upcoming_bookings_for_date(target_date: str) -> List[Dict]:
    """
    Получает все бронирования на конкретную дату.
    Используется в admin для просмотра расписания дня.

    Args:
        target_date: Дата "YYYY-MM-DD"

    Returns:
        Список бронирований на эту дату, отсортированных по времени
    """
    try:
        response = (
            supabase.table("bookings")
            .select("*, services(name)")
            .eq("booking_date", target_date)
            .neq("status", "cancelled")  # Исключаем отменённые
            .order("booking_time")
            .execute()
        )
        return response.data or []

    except Exception as e:
        logger.error(f"Ошибка получения записей за {target_date}: {e}")
        return []
