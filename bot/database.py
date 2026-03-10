# ===================================================
# database.py — Все взаимодействия с базой данных Supabase
# ===================================================

from supabase import create_client, Client
from bot.config import settings
from typing import Optional, List, Dict
import logging

logger = logging.getLogger(__name__)

# Глобальный sync-клиент — инициализируется один раз при запуске
supabase: Client = None


def init_supabase():
    """
    Инициализирует синхронный клиент Supabase.
    Вызывается один раз в main.py перед запуском polling.
    Функции БД объявлены как async def для совместимости с aiogram,
    но внутри используют sync-клиент — brief blocking допустим
    при низком трафике (nail salon).
    """
    global supabase
    supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    logger.info("✅ Supabase клиент инициализирован")


# ===================================================
# УСЛУГИ (SERVICES)
# ===================================================

async def get_all_services(active_only: bool = True) -> List[Dict]:
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
    try:
        response = (
            supabase.table("services")
            .select("*")
            .eq("id", service_id)
            .single()
            .execute()
        )
        return response.data
    except Exception as e:
        logger.error(f"Ошибка получения услуги {service_id}: {e}")
        return None


async def add_service(name: str, duration_min: int, price: int) -> Optional[Dict]:
    # Блок 1: INSERT
    try:
        supabase.table("services").insert({
            "name": name,
            "duration_min": duration_min,
            "price": price,
            "is_active": True,
        }).execute()
    except Exception as e:
        err = str(e)
        if "23505" in err or "unique" in err.lower() or "duplicate" in err.lower():
            logger.warning(f"Услуга '{name}' уже существует, возвращаем существующую")
        else:
            logger.error(f"INSERT services failed: {e}", exc_info=True)
            return None

    # Блок 2: SELECT — выполняется всегда
    try:
        response = (
            supabase.table("services")
            .select("*")
            .eq("name", name)
            .single()
            .execute()
        )
        return response.data
    except Exception as e:
        logger.error(f"SELECT services after insert: {e}", exc_info=True)
        return None


async def toggle_service_status(service_id: str, is_active: bool) -> bool:
    try:
        supabase.table("services").update({"is_active": is_active}).eq("id", service_id).execute()
        return True
    except Exception as e:
        logger.error(f"Ошибка изменения статуса услуги: {e}")
        return False


async def delete_service(service_id: str) -> bool:
    try:
        supabase.table("services").delete().eq("id", service_id).execute()
        return True
    except Exception as e:
        logger.error(f"Ошибка удаления услуги: {e}")
        return False


async def service_has_bookings(service_id: str) -> bool:
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
        return True


# ===================================================
# СЛОТЫ ВРЕМЕНИ (TIME_SLOTS)
# ===================================================

async def get_available_dates(year: int, month: int) -> List[str]:
    try:
        month_str = f"{year:04d}-{month:02d}"
        start_date = f"{month_str}-01"
        if month == 12:
            end_date = f"{year + 1:04d}-01-01"
        else:
            end_date = f"{year:04d}-{month + 1:02d}-01"

        response = (
            supabase.table("time_slots")
            .select("slot_date")
            .eq("is_available", True)
            .gte("slot_date", start_date)
            .lt("slot_date", end_date)
            .execute()
        )

        if not response.data:
            return []

        dates = list(set(row["slot_date"] for row in response.data))
        return sorted(dates)
    except Exception as e:
        logger.error(f"Ошибка получения доступных дат: {e}")
        return []


async def get_available_slots(slot_date: str) -> List[Dict]:
    try:
        response = (
            supabase.table("time_slots")
            .select("*")
            .eq("slot_date", slot_date)
            .eq("is_available", True)
            .order("slot_time")
            .execute()
        )
        return response.data or []
    except Exception as e:
        logger.error(f"Ошибка получения слотов для {slot_date}: {e}")
        return []


async def add_time_slot(slot_date: str, slot_time: str) -> Optional[Dict]:
    # Блок 1: INSERT
    try:
        supabase.table("time_slots").insert({
            "slot_date": slot_date,
            "slot_time": slot_time,
            "is_available": True,
        }).execute()
    except Exception as e:
        err = str(e)
        if "23505" in err or "unique" in err.lower() or "duplicate" in err.lower():
            logger.warning(f"Слот {slot_date} {slot_time} уже существует")
        else:
            logger.error(f"INSERT time_slots failed: {e}", exc_info=True)
            return None

    # Блок 2: SELECT — выполняется всегда
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
        logger.error(f"SELECT time_slots after insert: {e}", exc_info=True)
        return None


async def mark_slot_unavailable(slot_id: str) -> bool:
    try:
        supabase.table("time_slots").update({"is_available": False}).eq("id", slot_id).execute()
        return True
    except Exception as e:
        logger.error(f"Ошибка блокировки слота {slot_id}: {e}")
        return False


async def mark_slot_available(slot_id: str) -> bool:
    try:
        supabase.table("time_slots").update({"is_available": True}).eq("id", slot_id).execute()
        return True
    except Exception as e:
        logger.error(f"Ошибка разблокировки слота {slot_id}: {e}")
        return False


async def get_slot_by_date_time(slot_date: str, slot_time: str) -> Optional[Dict]:
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
    try:
        supabase.table("time_slots").delete().eq("id", slot_id).execute()
        return True
    except Exception as e:
        logger.error(f"Ошибка удаления слота {slot_id}: {e}")
        return False


async def get_all_slots_for_date(slot_date: str) -> List[Dict]:
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
    try:
        # Блок 1: INSERT
        try:
            supabase.table("bookings").insert({
                "user_id": user_id,
                "username": username,
                "full_name": full_name,
                "phone": phone,
                "service_id": service_id,
                "booking_date": booking_date,
                "booking_time": booking_time,
                "status": "pending",
            }).execute()
        except Exception as e:
            logger.error(f"INSERT bookings failed: {e}", exc_info=True)
            return None

        # Блок 2: SELECT с полными данными
        fetch = (
            supabase.table("bookings")
            .select("*, services(name, price)")
            .eq("user_id", user_id)
            .eq("booking_date", booking_date)
            .eq("booking_time", booking_time)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        booking = fetch.data[0] if fetch.data else None

        if booking:
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
    try:
        query = (
            supabase.table("bookings")
            .select("*, services(name, price)")
            .order("booking_date", desc=False)
            .order("booking_time", desc=False)
            .range(offset, offset + limit - 1)
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
    try:
        await mark_slot_available(old_slot_id)
        await mark_slot_unavailable(new_slot_id)

        supabase.table("bookings").update({
            "booking_date": new_date,
            "booking_time": new_time,
            "status": "confirmed",
        }).eq("id", booking_id).execute()

        logger.info(f"Бронирование {booking_id} перенесено на {new_date} {new_time}")
        return True
    except Exception as e:
        logger.error(f"Ошибка переноса бронирования: {e}")
        return False


async def delete_booking(booking_id: str, slot_id: Optional[str] = None) -> bool:
    try:
        if not slot_id:
            booking = await get_booking_by_id(booking_id)
            if booking:
                slot = await get_slot_by_date_time(
                    booking["booking_date"],
                    booking["booking_time"]
                )
                if slot:
                    slot_id = slot["id"]

        if slot_id:
            await mark_slot_available(slot_id)

        supabase.table("bookings").delete().eq("id", booking_id).execute()
        logger.info(f"Бронирование {booking_id} удалено")
        return True
    except Exception as e:
        logger.error(f"Ошибка удаления бронирования {booking_id}: {e}")
        return False


async def get_bookings_count(status_filter: Optional[str] = None) -> int:
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
    try:
        response = (
            supabase.table("bookings")
            .select("*, services(name)")
            .eq("booking_date", target_date)
            .neq("status", "cancelled")
            .order("booking_time")
            .execute()
        )
        return response.data or []
    except Exception as e:
        logger.error(f"Ошибка получения записей за {target_date}: {e}")
        return []


# ===================================================
# АНКЕТА НОВОГО КЛИЕНТА (CLIENT SURVEYS)
# ===================================================


async def save_survey(
    user_id: int,
    booking_id: str,
    comfort_prefs: Optional[str],
) -> bool:
    """
    Сохраняет (или обновляет) пожелания клиента к конкретному визиту.
    Upsert по booking_id — каждое бронирование хранит свои пожелания.
    comfort_prefs — строка через запятую («☕ Кофе, 🧣 Плед») или None.
    """
    try:
        supabase.table("client_surveys").upsert({
            "user_id": user_id,
            "booking_id": booking_id,
            "comfort_prefs": comfort_prefs,
        }, on_conflict="booking_id").execute()
        logger.info(f"Пожелания сохранены: booking_id={booking_id}, prefs={comfort_prefs}")
        return True
    except Exception as e:
        logger.error(f"Ошибка сохранения пожеланий booking_id={booking_id}: {e}")
        return False


# ===================================================
# АДМИНИСТРАТОРЫ (ADMINS)
# ===================================================

async def get_admin_telegram_ids() -> List[int]:
    """
    Возвращает список Telegram ID всех администраторов из БД.
    Используется для кэширования прав доступа в middleware.
    """
    try:
        response = (
            supabase.table("admins")
            .select("telegram_id")
            .execute()
        )
        return [row["telegram_id"] for row in (response.data or [])]
    except Exception as e:
        logger.error(f"Ошибка получения ID администраторов: {e}")
        return []


async def get_all_admins() -> List[Dict]:
    """Возвращает всех администраторов из БД с полными данными."""
    try:
        response = (
            supabase.table("admins")
            .select("*")
            .order("added_at")
            .execute()
        )
        return response.data or []
    except Exception as e:
        logger.error(f"Ошибка получения администраторов: {e}")
        return []


async def add_admin(telegram_id: int, username: Optional[str] = None) -> bool:
    """Добавляет администратора в БД. Если уже есть — обновляет username."""
    try:
        supabase.table("admins").upsert(
            {"telegram_id": telegram_id, "username": username},
            on_conflict="telegram_id",
        ).execute()
        logger.info(f"Администратор {telegram_id} добавлен в БД")
        return True
    except Exception as e:
        logger.error(f"Ошибка добавления администратора {telegram_id}: {e}")
        return False


async def remove_admin(telegram_id: int) -> bool:
    """Удаляет администратора из БД по Telegram ID."""
    try:
        supabase.table("admins").delete().eq("telegram_id", telegram_id).execute()
        logger.info(f"Администратор {telegram_id} удалён из БД")
        return True
    except Exception as e:
        logger.error(f"Ошибка удаления администратора {telegram_id}: {e}")
        return False


async def find_user_id_by_username(username: str) -> Optional[int]:
    """
    Ищет Telegram ID пользователя по его username в таблице bookings.
    username передаётся без символа @, поиск без учёта регистра.
    Возвращает user_id последней записи клиента, или None если не найден.
    """
    try:
        clean = username.lstrip("@").lower()
        response = (
            supabase.table("bookings")
            .select("user_id")
            .ilike("username", clean)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if response.data:
            return response.data[0]["user_id"]
        return None
    except Exception as e:
        logger.error(f"Ошибка поиска user_id по username @{username}: {e}")
        return None


async def get_username_by_user_id(user_id: int) -> Optional[str]:
    """
    Ищет username пользователя по его Telegram ID в таблице bookings.
    Возвращает username из последней записи, или None если не найден
    или если у пользователя нет username.
    """
    try:
        response = (
            supabase.table("bookings")
            .select("username")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if response.data and response.data[0].get("username"):
            return response.data[0]["username"]
        return None
    except Exception as e:
        logger.error(f"Ошибка поиска username по user_id {user_id}: {e}")
        return None


async def get_user_display_info(user_id: int) -> tuple:
    """
    Возвращает (full_name, username) из последнего бронирования пользователя.
    Используется для красивого отображения в списке администраторов.
    Оба значения могут быть None если пользователь не делал записей через бот.
    """
    try:
        response = (
            supabase.table("bookings")
            .select("full_name, username")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if response.data:
            row = response.data[0]
            return row.get("full_name"), row.get("username")
        return None, None
    except Exception as e:
        logger.error(f"Ошибка получения данных пользователя {user_id}: {e}")
        return None, None


async def get_survey_by_booking_id(booking_id: str) -> Optional[Dict]:
    """
    Возвращает пожелания клиента по ID конкретного бронирования.
    Используется в админке для отображения в карточке бронирования.
    """
    try:
        response = (
            supabase.table("client_surveys")
            .select("comfort_prefs")
            .eq("booking_id", booking_id)
            .single()
            .execute()
        )
        return response.data
    except Exception as e:
        # single() бросает исключение если строк нет — это нормально
        return None
