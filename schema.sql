-- ===================================================
-- schema.sql — Схема базы данных NailStory
-- ===================================================
-- Выполните ВЕСЬ этот SQL в Supabase Dashboard:
--   Database → SQL Editor → New Query → вставьте → Run
--
-- ВНИМАНИЕ: скрипт удаляет существующие таблицы (DROP).
-- Все данные будут удалены. Запускать только при первом
-- развёртывании или полном сбросе.
-- ===================================================


-- ===================================================
-- 1. УДАЛЯЕМ СТАРЫЕ ТАБЛИЦЫ (если есть)
-- ===================================================

DROP TABLE IF EXISTS bookings  CASCADE;
DROP TABLE IF EXISTS time_slots CASCADE;
DROP TABLE IF EXISTS services   CASCADE;


-- ===================================================
-- 2. РАСШИРЕНИЯ
-- ===================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";


-- ===================================================
-- 3. СОЗДАЁМ ТАБЛИЦЫ
-- ===================================================

CREATE TABLE services (
    id           UUID        DEFAULT uuid_generate_v4() PRIMARY KEY,
    name         TEXT        NOT NULL UNIQUE,
    duration_min INTEGER     NOT NULL CHECK (duration_min > 0),
    price        INTEGER     NOT NULL CHECK (price > 0),
    is_active    BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE time_slots (
    id           UUID    DEFAULT uuid_generate_v4() PRIMARY KEY,
    slot_date    DATE    NOT NULL,
    slot_time    TIME    NOT NULL,
    is_available BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (slot_date, slot_time)
);

CREATE TABLE bookings (
    id           UUID        DEFAULT uuid_generate_v4() PRIMARY KEY,
    user_id      BIGINT      NOT NULL,
    username     TEXT,
    full_name    TEXT        NOT NULL,
    phone        TEXT        NOT NULL,
    service_id   UUID        NOT NULL REFERENCES services(id) ON DELETE RESTRICT,
    booking_date DATE        NOT NULL,
    booking_time TIME        NOT NULL,
    status       TEXT        NOT NULL DEFAULT 'pending'
                             CHECK (status IN ('pending', 'confirmed', 'cancelled')),
    created_at   TIMESTAMPTZ DEFAULT NOW()
);


-- ===================================================
-- 4. ИНДЕКСЫ
-- ===================================================

CREATE INDEX idx_services_active    ON services  (is_active);
CREATE INDEX idx_slots_date         ON time_slots (slot_date);
CREATE INDEX idx_slots_available    ON time_slots (slot_date, is_available);
CREATE INDEX idx_bookings_status    ON bookings  (status);
CREATE INDEX idx_bookings_date      ON bookings  (booking_date);
CREATE INDEX idx_bookings_user      ON bookings  (user_id);


-- ===================================================
-- 5. ПРАВА ДОСТУПА
-- ===================================================
-- Бот работает на сервере с service_role ключом.
-- Отключаем RLS и выдаём явные права — без этого
-- INSERT/UPDATE/DELETE могут быть заблокированы.

ALTER TABLE services   DISABLE ROW LEVEL SECURITY;
ALTER TABLE time_slots DISABLE ROW LEVEL SECURITY;
ALTER TABLE bookings   DISABLE ROW LEVEL SECURITY;

GRANT ALL ON services   TO anon, authenticated, service_role;
GRANT ALL ON time_slots TO anon, authenticated, service_role;
GRANT ALL ON bookings   TO anon, authenticated, service_role;


-- ===================================================
-- 6. АНКЕТА НОВОГО КЛИЕНТА
-- ===================================================
-- Заполняется один раз после первого бронирования.
-- user_id UNIQUE — один опрос на клиента.

DROP TABLE IF EXISTS client_surveys CASCADE;

CREATE TABLE client_surveys (
    id           UUID        DEFAULT uuid_generate_v4() PRIMARY KEY,
    user_id      BIGINT      NOT NULL UNIQUE,
    booking_id   UUID        REFERENCES bookings(id) ON DELETE SET NULL,
    allergies    TEXT,
    nail_shape   TEXT,
    design_style TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE client_surveys DISABLE ROW LEVEL SECURITY;
GRANT ALL ON client_surveys TO anon, authenticated, service_role;
