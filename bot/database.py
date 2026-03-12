# ===================================================
# database.py — Все взаимодействия с базой данных Supabase
# ===================================================

from supabase import create_client, Client
from bot.config import settings
from typing import Optional, List, Dict
from datetime import date, datetime, timedelta
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


async def update_service(
    service_id: str,
    name: str | None = None,
    duration_min: int | None = None,
    price: int | None = None,
) -> bool:
    """Обновляет только переданные поля услуги. Возвращает False при конфликте имени."""
    updates: dict = {}
    if name is not None:
        updates["name"] = name
    if duration_min is not None:
        updates["duration_min"] = duration_min
    if price is not None:
        updates["price"] = price

    if not updates:
        return True  # нечего менять — успех

    try:
        supabase.table("services").update(updates).eq("id", service_id).execute()
        return True
    except Exception as e:
        err = str(e)
        if "23505" in err or "unique" in err.lower() or "duplicate" in err.lower():
            logger.warning(f"Конфликт имени при обновлении услуги {service_id}: {e}")
        else:
            logger.error(f"Ошибка обновления услуги {service_id}: {e}")
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

        # Нижняя граница — максимум из 1-го числа месяца и сегодня
        # (не тянем прошедшие даты, build_calendar всё равно их скрывает)
        today_str = date.today().isoformat()
        effective_start = max(start_date, today_str)

        response = (
            supabase.table("time_slots")
            .select("slot_date")
            .eq("is_available", True)
            .gte("slot_date", effective_start)
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


async def get_dates_with_any_slots(year: int, month: int) -> List[str]:
    """Возвращает даты месяца, на которые уже созданы слоты (любые, не только свободные).
    Используется для визуального маркера в админском календаре (📅)."""
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
            .gte("slot_date", start_date)
            .lt("slot_date", end_date)
            .execute()
        )
        if not response.data:
            return []
        dates = list(set(row["slot_date"] for row in response.data))
        return sorted(dates)
    except Exception as e:
        logger.error(f"Ошибка получения дат со слотами: {e}")
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


async def bulk_create_slots(
    dates: List[str],
    start_time: str,
    end_time: str,
    interval_min: int,
) -> Dict:
    """
    Массово создаёт слоты для списка дат с заданным интервалом.

    Args:
        dates: Список дат ["YYYY-MM-DD", ...]
        start_time: Начало "HH:MM"
        end_time: Конец "HH:MM" (не включается)
        interval_min: Шаг в минутах (15, 30, 60)

    Returns:
        {"created": N, "skipped": N}
    """
    start_dt = datetime.strptime(start_time, "%H:%M")
    # end_time="00:00" означает «до полуночи» (конец суток)
    if end_time == "00:00":
        end_dt = start_dt.replace(hour=0, minute=0) + timedelta(days=1)
    else:
        end_dt = datetime.strptime(end_time, "%H:%M")
    delta = timedelta(minutes=interval_min)

    # Собираем все слоты для генерации
    slots_to_create = []
    current = start_dt
    while current < end_dt:
        time_str = current.strftime("%H:%M:%S")
        for date_str in dates:
            slots_to_create.append({
                "slot_date": date_str,
                "slot_time": time_str,
                "is_available": True,
            })
        current += delta

    if not slots_to_create:
        return {"created": 0, "skipped": 0}

    # Получаем уже существующие слоты одним запросом
    existing = set()
    try:
        response = (
            supabase.table("time_slots")
            .select("slot_date,slot_time")
            .in_("slot_date", dates)
            .execute()
        )
        for row in (response.data or []):
            existing.add((row["slot_date"], row["slot_time"]))
    except Exception as e:
        logger.error(f"Ошибка проверки существующих слотов: {e}")

    new_slots = [
        s for s in slots_to_create
        if (s["slot_date"], s["slot_time"]) not in existing
    ]
    skipped = len(slots_to_create) - len(new_slots)
    created = 0

    # Вставляем новые слоты батчами по 100
    if new_slots:
        try:
            batch_size = 100
            for i in range(0, len(new_slots), batch_size):
                supabase.table("time_slots").insert(new_slots[i:i + batch_size]).execute()
            created = len(new_slots)
        except Exception as e:
            logger.error(f"Ошибка bulk insert слотов: {e}")

    return {"created": created, "skipped": skipped}


async def delete_slots_for_date(date_str: str) -> int:
    """
    Удаляет все СВОБОДНЫЕ слоты за дату.
    Занятые (is_available=False) слоты не трогает.

    Returns:
        Количество удалённых слотов
    """
    try:
        response = (
            supabase.table("time_slots")
            .delete()
            .eq("slot_date", date_str)
            .eq("is_available", True)
            .execute()
        )
        return len(response.data or [])
    except Exception as e:
        logger.error(f"Ошибка удаления слотов за {date_str}: {e}")
        return 0


async def delete_slot_by_id(slot_id: str) -> bool:
    """Удаляет конкретный свободный слот по ID."""
    try:
        supabase.table("time_slots").delete().eq("id", slot_id).eq("is_available", True).execute()
        return True
    except Exception as e:
        logger.error(f"Ошибка удаления слота {slot_id}: {e}")
        return False


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


async def get_dates_with_available_slots(year: int, month: int) -> List[str]:
    """Возвращает даты в месяце, на которые есть хотя бы один свободный слот."""
    try:
        start_date = f"{year:04d}-{month:02d}-01"
        end_date = f"{year:04d}-{month + 1:02d}-01" if month < 12 else f"{year + 1:04d}-01-01"

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
        logger.error(f"Ошибка получения дат со свободными слотами: {e}")
        return []


async def get_dates_with_bookings(year: int, month: int) -> List[str]:
    """Возвращает список дат в формате YYYY-MM-DD, на которые есть хотя бы одно бронирование."""
    try:
        start_date = f"{year:04d}-{month:02d}-01"
        if month == 12:
            end_date = f"{year + 1:04d}-01-01"
        else:
            end_date = f"{year:04d}-{month + 1:02d}-01"

        response = (
            supabase.table("bookings")
            .select("booking_date")
            .gte("booking_date", start_date)
            .lt("booking_date", end_date)
            .execute()
        )
        if not response.data:
            return []
        dates = list(set(row["booking_date"] for row in response.data))
        return sorted(dates)
    except Exception as e:
        logger.error(f"Ошибка получения дат с бронированиями: {e}")
        return []


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


async def add_admin(
    telegram_id: int,
    username: Optional[str] = None,
    role: str = "admin",
) -> bool:
    """
    Добавляет администратора в БД.
    Если уже есть — обновляет username (роль не трогает, чтобы не перезаписать 'owner').
    Для явной установки роли используйте set_admin_role().
    """
    try:
        # Проверяем, есть ли уже запись
        existing = (
            supabase.table("admins")
            .select("role")
            .eq("telegram_id", telegram_id)
            .execute()
        )
        if existing.data:
            # Обновляем только username, роль оставляем
            supabase.table("admins").update(
                {"username": username}
            ).eq("telegram_id", telegram_id).execute()
        else:
            supabase.table("admins").insert(
                {"telegram_id": telegram_id, "username": username, "role": role}
            ).execute()
        logger.info(f"Администратор {telegram_id} добавлен/обновлён в БД (role={role})")
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


async def get_db_owner_id() -> Optional[int]:
    """
    Возвращает Telegram ID владельца (role='owner') из таблицы admins.
    Если в БД нет владельца — возвращает None.
    """
    try:
        response = (
            supabase.table("admins")
            .select("telegram_id")
            .eq("role", "owner")
            .limit(1)
            .execute()
        )
        if response.data:
            return response.data[0]["telegram_id"]
        return None
    except Exception as e:
        logger.error(f"Ошибка получения владельца из БД: {e}")
        return None


async def set_admin_role(telegram_id: int, role: str) -> bool:
    """
    Устанавливает роль администратора ('owner' или 'admin').
    Администратор должен уже существовать в таблице admins.
    """
    try:
        supabase.table("admins").update({"role": role}).eq("telegram_id", telegram_id).execute()
        logger.info(f"Роль администратора {telegram_id} изменена на {role}")
        return True
    except Exception as e:
        logger.error(f"Ошибка изменения роли {telegram_id}: {e}")
        return False


async def transfer_ownership(old_owner_id: int, new_owner_id: int) -> bool:
    """
    Передаёт владение: старый владелец становится обычным администратором,
    новый — владельцем. Оба должны существовать в таблице admins.
    Возвращает True при успехе обоих запросов.
    """
    try:
        supabase.table("admins").update({"role": "admin"}).eq("telegram_id", old_owner_id).execute()
        supabase.table("admins").update({"role": "owner"}).eq("telegram_id", new_owner_id).execute()
        logger.info(f"Владение передано: {old_owner_id} → {new_owner_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка передачи владения {old_owner_id}→{new_owner_id}: {e}")
        return False


async def ensure_owner_in_db(owner_id: int, username: Optional[str] = None) -> bool:
    """
    Гарантирует, что владелец существует в таблице admins с role='owner'.
    Вызывается при первом открытии раздела администраторов, если в БД нет owner.
    Если запись уже есть — обновляет роль до 'owner'.
    """
    try:
        existing = (
            supabase.table("admins")
            .select("telegram_id, role")
            .eq("telegram_id", owner_id)
            .execute()
        )
        if existing.data:
            if existing.data[0]["role"] != "owner":
                supabase.table("admins").update({"role": "owner"}).eq("telegram_id", owner_id).execute()
        else:
            supabase.table("admins").insert(
                {"telegram_id": owner_id, "username": username, "role": "owner"}
            ).execute()
        logger.info(f"Владелец {owner_id} зарегистрирован в БД")
        return True
    except Exception as e:
        logger.error(f"Ошибка регистрации владельца {owner_id}: {e}")
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


# ===================================================
# СТАНДАРТНОЕ РАСПИСАНИЕ
# ===================================================

async def get_default_schedule() -> Optional[Dict]:
    """
    Возвращает стандартное расписание или None если не задано.
    Поля: weekdays_mask, start_hour, end_hour, interval_min, updated_at
    """
    try:
        response = (
            supabase.table("default_schedule")
            .select("*")
            .eq("id", 1)
            .execute()
        )
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Ошибка получения стандартного расписания: {e}")
        return None


async def save_default_schedule(
    weekdays_mask: int,
    start_hour: int,
    end_hour: int,
    interval_min: int,
) -> bool:
    """
    Сохраняет (upsert) стандартное расписание.
    Одна строка с id=1.
    """
    try:
        supabase.table("default_schedule").upsert({
            "id": 1,
            "weekdays_mask": weekdays_mask,
            "start_hour": start_hour,
            "end_hour": end_hour,
            "interval_min": interval_min,
            "updated_at": datetime.utcnow().isoformat(),
        }).execute()
        return True
    except Exception as e:
        logger.error(f"Ошибка сохранения стандартного расписания: {e}")
        return str(e)  # возвращаем текст ошибки для отображения


async def delete_default_schedule() -> bool:
    """Удаляет стандартное расписание."""
    try:
        supabase.table("default_schedule").delete().eq("id", 1).execute()
        return True
    except Exception as e:
        logger.error(f"Ошибка удаления стандартного расписания: {e}")
        return False


async def get_custom_days() -> set:
    """
    Возвращает множество дат, отредактированных вручную (защищены от стандарта).
    Формат: {"2024-03-05", "2024-03-12", ...}
    """
    try:
        response = supabase.table("custom_days").select("date").execute()
        return {row["date"] for row in (response.data or [])}
    except Exception as e:
        logger.error(f"Ошибка получения кастомных дней: {e}")
        return set()


async def add_custom_day(date_str: str) -> None:
    """Помечает день как кастомный (защита от перезаписи стандартом)."""
    try:
        supabase.table("custom_days").upsert({"date": date_str}).execute()
    except Exception as e:
        logger.error(f"Ошибка добавления кастомного дня {date_str}: {e}")


async def add_custom_days(dates: list) -> None:
    """Пакетно помечает список дат как кастомные (для месячного генератора)."""
    if not dates:
        return
    try:
        rows = [{"date": d} for d in dates]
        for i in range(0, len(rows), 100):
            supabase.table("custom_days").upsert(rows[i:i + 100]).execute()
    except Exception as e:
        logger.error(f"Ошибка пакетного добавления кастомных дней: {e}")


async def remove_custom_day(date_str: str) -> None:
    """Снимает пометку кастомного дня."""
    try:
        supabase.table("custom_days").delete().eq("date", date_str).execute()
    except Exception as e:
        logger.error(f"Ошибка удаления кастомного дня {date_str}: {e}")


def _get_dates_for_rule(
    weekdays_mask: int,
    start_date: date,
    end_date: date,
    custom_days: set,
) -> List[str]:
    """
    Вспомогательная: возвращает список дат в диапазоне [start_date, end_date),
    которые совпадают с weekdays_mask и не являются кастомными.
    weekdays_mask: бит 0 = Пн, бит 6 = Вс (0b0000001 = только Пн)
    """
    result = []
    current = start_date
    while current < end_date:
        weekday_bit = 1 << current.weekday()  # weekday(): 0=Mon, 6=Sun
        if (weekdays_mask & weekday_bit) and current.isoformat() not in custom_days:
            result.append(current.isoformat())
        current += timedelta(days=1)
    return result


async def apply_default_schedule_for_months(months_ahead: int = 24) -> Dict:
    """
    Применяет стандартное расписание на N месяцев вперёд.
    Пропускает кастомные дни и уже существующие слоты.
    Возвращает {"created": N, "skipped": N} или {"error": "..."}.
    """
    rule = await get_default_schedule()
    if not rule:
        return {"error": "no_rule"}

    today = date.today()
    end_date = date(
        today.year + (today.month + months_ahead - 1) // 12,
        (today.month + months_ahead - 1) % 12 + 1,
        1,
    )

    custom = await get_custom_days()
    dates = _get_dates_for_rule(
        rule["weekdays_mask"], today, end_date, custom
    )
    if not dates:
        return {"created": 0, "skipped": 0}

    return await bulk_create_slots(
        dates,
        f"{rule['start_hour']:02d}:00",
        f"{rule['end_hour']:02d}:00",
        rule["interval_min"],
    )


async def get_day_schedule_info(date_str: str) -> Optional[Dict]:
    """
    Возвращает информацию о расписании на конкретный день:
    start, end (последний слот), end_exclusive, interval_min, total, free.
    Используется для продления дня и смены интервала.
    """
    try:
        response = (
            supabase.table("time_slots")
            .select("slot_time,is_available")
            .eq("slot_date", date_str)
            .order("slot_time")
            .execute()
        )
        slots = response.data or []
        if not slots:
            return None

        all_times = sorted(s["slot_time"][:5] for s in slots)
        free_times = [s["slot_time"][:5] for s in slots if s["is_available"]]

        start = all_times[0]
        end = all_times[-1]

        interval_min = 30  # умолчание
        if len(all_times) >= 2:
            t1 = datetime.strptime(all_times[0], "%H:%M")
            t2 = datetime.strptime(all_times[1], "%H:%M")
            diff = int((t2 - t1).total_seconds() / 60)
            if diff > 0:
                interval_min = diff

        last_dt = datetime.strptime(end, "%H:%M")
        end_exclusive_dt = last_dt + timedelta(minutes=interval_min)
        if end_exclusive_dt.day != last_dt.day:
            end_exclusive = "24:00"
        else:
            end_exclusive = end_exclusive_dt.strftime("%H:%M")

        return {
            "start": start,
            "end": end,
            "end_exclusive": end_exclusive,
            "interval_min": interval_min,
            "total": len(all_times),
            "free": len(free_times),
        }
    except Exception as e:
        logger.error(f"Ошибка получения инфо о дне {date_str}: {e}")
        return None


async def clear_non_custom_future_slots() -> Dict:
    """
    Удаляет все будущие свободные слоты, кроме custom-дней (ручных правок).
    Используется при смене режима расписания.
    """
    today = date.today()
    custom = await get_custom_days()
    try:
        response = (
            supabase.table("time_slots")
            .select("id,slot_date")
            .eq("is_available", True)
            .gte("slot_date", today.isoformat())
            .execute()
        )
        ids_to_delete = [
            row["id"] for row in (response.data or [])
            if row["slot_date"] not in custom
        ]
        if ids_to_delete:
            batch_size = 100
            for i in range(0, len(ids_to_delete), batch_size):
                supabase.table("time_slots").delete().in_(
                    "id", ids_to_delete[i:i + batch_size]
                ).execute()
        return {"deleted": len(ids_to_delete)}
    except Exception as e:
        logger.error(f"Ошибка очистки слотов при смене режима: {e}")
        return {"error": str(e)}


async def get_active_hours_for_date(date_str: str) -> set:
    """Возвращает множество часов (int 0-23), в которых есть хотя бы один слот."""
    try:
        response = (
            supabase.table("time_slots")
            .select("slot_time")
            .eq("slot_date", date_str)
            .execute()
        )
        return {int(row["slot_time"][:2]) for row in (response.data or [])}
    except Exception as e:
        logger.error(f"Ошибка получения активных часов для {date_str}: {e}")
        return set()


async def delete_slots_in_hours(date_str: str, hours: set) -> int:
    """Удаляет все слоты в указанных часах для даты. Возвращает число удалённых."""
    if not hours:
        return 0
    try:
        response = (
            supabase.table("time_slots")
            .select("id,slot_time")
            .eq("slot_date", date_str)
            .execute()
        )
        ids_to_delete = [
            row["id"] for row in (response.data or [])
            if int(row["slot_time"][:2]) in hours
        ]
        if ids_to_delete:
            batch_size = 100
            for i in range(0, len(ids_to_delete), batch_size):
                supabase.table("time_slots").delete().in_(
                    "id", ids_to_delete[i:i + batch_size]
                ).execute()
        return len(ids_to_delete)
    except Exception as e:
        logger.error(f"Ошибка удаления слотов по часам для {date_str}: {e}")
        return 0


async def reset_default_schedule_slots() -> Dict:
    """
    При задании/смене стандартного расписания:
    1. Удаляет ВСЕ некастомные (не day-level) свободные слоты в будущем
       — это очищает и старый стандарт, и месячные прогоны
    2. Сохраняет кастомные (отредактированные на уровне дня) слоты
    3. Добавляет новые слоты по текущему правилу на 24 мес вперёд
    Вызывается ПОСЛЕ save_default_schedule().
    """
    today = date.today()
    custom = await get_custom_days()  # только day-level overrides

    try:
        response = (
            supabase.table("time_slots")
            .select("id,slot_date")
            .eq("is_available", True)
            .gte("slot_date", today.isoformat())
            .execute()
        )
        ids_to_delete = [
            row["id"] for row in (response.data or [])
            if row["slot_date"] not in custom
        ]
        if ids_to_delete:
            batch_size = 100
            for i in range(0, len(ids_to_delete), batch_size):
                supabase.table("time_slots").delete().in_(
                    "id", ids_to_delete[i:i + batch_size]
                ).execute()
    except Exception as e:
        logger.error(f"Ошибка очистки слотов при смене стандарта: {e}")

    return await apply_default_schedule_for_months(24)


# ===================================================
# НАСТРОЙКИ БОТА (bot_settings)
# ===================================================

async def get_setting(key: str) -> Optional[str]:
    """Возвращает значение настройки по ключу или None."""
    try:
        response = (
            supabase.table("bot_settings")
            .select("value")
            .eq("key", key)
            .execute()
        )
        return response.data[0]["value"] if response.data else None
    except Exception as e:
        logger.error(f"Ошибка чтения настройки {key}: {e}")
        return None


async def set_setting(key: str, value: str) -> bool:
    """Сохраняет (upsert) значение настройки."""
    try:
        supabase.table("bot_settings").upsert({"key": key, "value": value}).execute()
        return True
    except Exception as e:
        logger.error(f"Ошибка сохранения настройки {key}: {e}")
        return False
