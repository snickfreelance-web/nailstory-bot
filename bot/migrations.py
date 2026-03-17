# ===================================================
# migrations.py — Автоматические миграции БД
# ===================================================
# При запуске бота проверяет наличие нужных таблиц
# и создаёт их через Supabase Management API если они отсутствуют.
#
# Используется Supabase Management API:
#   POST https://api.supabase.com/v1/projects/{ref}/database/query
#   Authorization: Bearer SUPABASE_ACCESS_TOKEN
#
# Project ref берётся из SUPABASE_URL:
#   https://{ref}.supabase.co → ref
# ===================================================

import logging
import httpx
from bot.config import settings

logger = logging.getLogger(__name__)

# SQL для создания новых таблиц (идемпотентно — IF NOT EXISTS)
MIGRATIONS = [
    {
        "name": "create_admin_settings",
        "sql": """
            CREATE TABLE IF NOT EXISTS admin_settings (
                key text PRIMARY KEY,
                value jsonb NOT NULL
            );
        """,
    },
    {
        "name": "create_custom_schedule_days",
        "sql": """
            CREATE TABLE IF NOT EXISTS custom_schedule_days (
                slot_date date PRIMARY KEY
            );
        """,
    },
]


def _get_project_ref() -> str:
    """Извлекает project ref из SUPABASE_URL."""
    url = settings.SUPABASE_URL
    # https://{ref}.supabase.co
    host = url.replace("https://", "").replace("http://", "")
    ref = host.split(".")[0]
    return ref


async def run_migrations() -> None:
    """
    Запускает все миграции при старте бота.
    Пропускает если SUPABASE_ACCESS_TOKEN не задан.
    """
    if not settings.SUPABASE_ACCESS_TOKEN:
        logger.warning(
            "⚠️  SUPABASE_ACCESS_TOKEN не задан — миграции пропущены. "
            "Добавьте токен в .env для автоматического создания таблиц."
        )
        return

    project_ref = _get_project_ref()
    api_url = f"https://api.supabase.com/v1/projects/{project_ref}/database/query"
    headers = {
        "Authorization": f"Bearer {settings.SUPABASE_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    logger.info(f"🔧 Запуск миграций для проекта {project_ref}...")

    async with httpx.AsyncClient(timeout=30.0) as client:
        for migration in MIGRATIONS:
            name = migration["name"]
            sql = migration["sql"].strip()
            try:
                response = await client.post(
                    api_url,
                    headers=headers,
                    json={"query": sql},
                )
                if response.status_code in (200, 201):
                    logger.info(f"  ✅ {name}")
                else:
                    logger.error(
                        f"  ❌ {name}: HTTP {response.status_code} — {response.text}"
                    )
            except Exception as e:
                logger.error(f"  ❌ {name}: {e}")

    logger.info("🔧 Миграции завершены")
