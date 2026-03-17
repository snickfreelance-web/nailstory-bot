import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

class Settings:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")
    ADMIN_IDS: str = os.getenv("ADMIN_IDS", "")
    OWNER_ID: str = os.getenv("OWNER_ID", "")
    SUPABASE_ACCESS_TOKEN: str = os.getenv("SUPABASE_ACCESS_TOKEN", "")

    def get_admin_ids(self) -> list[int]:
        return [int(x.strip()) for x in self.ADMIN_IDS.split(",") if x.strip()]

    def get_owner_id(self) -> Optional[int]:
        """
        Возвращает Telegram ID владельца из .env.
        Если OWNER_ID не задан — берёт первый ID из ADMIN_IDS.
        Используется только как начальное значение; после передачи
        владения через бот источником правды становится БД.
        """
        if self.OWNER_ID.strip():
            return int(self.OWNER_ID.strip())
        ids = self.get_admin_ids()
        return ids[0] if ids else None

settings = Settings()
