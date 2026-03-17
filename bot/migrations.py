# ===================================================
# bot/migrations.py — Автоматические миграции БД
# ===================================================
# Создаёт нужные таблицы в Supabase при старте бота,
# если они ещё не существуют.
#
# Использует Supabase Management API:
#   POST https://api.supabase.com/v1/projects/{ref}/database/query
#   Authorization: Bearer SUPABASE_ACCESS_TOKEN
#
# project_ref извлекается из SUPABASE_URL автоматически:
#   https://abcdefg.supabase.co → ref = abcdefg
# ===================================================

import logging
import aiohttp
from bot.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------
# SQL-миграции (порядок важен — по зависимостям)
# ---------------------------------------------------
MIGRATIONS = [
    {
        "name": "create_admin_settings",
        "sql": """
            CREATE TABLE IF NOT EXISTS admin_settings (
                key   text  PRIMARY KEY,
                value jsonb NOT NULL
            )
        """,
    },
    {
        "name": "create_custom_schedule_days",
        "sql": """
            CREATE TABLE IF NOT EXISTS custom_schedule_days (
                slot_date date PRIMARY KEY
            )
        """,
    },
    # Права доступа: отключаем RLS и выдаём гранты всем нужным ролям.
    # Supabase использует anon/authenticated/service_role через PostgREST.
    {
        "name": "grant_admin_settings",
        "sql": """
            ALTER TABLE public.admin_settings DISABLE ROW LEVEL SECURITY;
            GRANT ALL ON TABLE public.admin_settings TO anon;
            GRANT ALL ON TABLE public.admin_settings TO authenticated;
            GRANT ALL ON TABLE public.admin_settings TO service_role
        """,
    },
    {
        "name": "grant_custom_schedule_days",
        "sql": """
            ALTER TABLE public.custom_schedule_days DISABLE ROW LEVEL SECURITY;
            GRANT ALL ON TABLE public.custom_schedule_days TO anon;
            GRANT ALL ON TABLE public.custom_schedule_days TO authenticated;
            GRANT ALL ON TABLE public.custom_schedule_days TO service_role
        """,
    },
    # Перезагружаем кеш схемы PostgREST чтобы новые таблицы стали доступны через REST API
    {
        "name": "reload_postgrest_schema",
        "sql": "SELECT pg_notify('pgrst', 'reload schema')",
    },
]


def _get_project_ref() -> str | None:
    """
    Извлекает project_ref из SUPABASE_URL.
    https://abcdefg.supabase.co  →  'abcdefg'
    """
    url = settings.SUPABASE_URL.strip()
    if not url:
        return None
    # Убираем протокол и берём первую часть домена
    host = url.replace("https://", "").replace("http://", "")
    ref = host.split(".")[0]
    return ref if ref else None


async def run_migrations() -> None:
    """
    Запускает все SQL-миграции при старте бота.
    Безопасно: каждый SQL использует CREATE TABLE IF NOT EXISTS.
    При отсутствии токена — выводит предупреждение и продолжает без миграций.
    """
    token = settings.SUPABASE_ACCESS_TOKEN.strip()
    if not token:
        logger.warning(
            "⚠️  SUPABASE_ACCESS_TOKEN не задан — автомиграции пропущены. "
            "Создайте таблицы вручную через Supabase Dashboard."
        )
        return

    project_ref = _get_project_ref()
    if not project_ref:
        logger.warning("⚠️  Не удалось определить project_ref из SUPABASE_URL — миграции пропущены.")
        return

    url = f"https://api.supabase.com/v1/projects/{project_ref}/database/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    logger.info("🔧 Запуск миграций БД...")

    async with aiohttp.ClientSession() as session:
        for migration in MIGRATIONS:
            name = migration["name"]
            sql = migration["sql"].strip()
            try:
                async with session.post(url, json={"query": sql}, headers=headers) as resp:
                    if resp.status in (200, 201):
                        logger.info(f"  ✅ {name}")
                    else:
                        body = await resp.text()
                        logger.error(f"  ❌ {name} — HTTP {resp.status}: {body}")
            except Exception as e:
                logger.error(f"  ❌ {name} — ошибка: {e}")

    logger.info("✅ Миграции применены")
