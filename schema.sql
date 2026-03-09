-- ===================================================
-- schema.sql — Схема базы данных Supabase
-- ===================================================
-- Выполните этот SQL в Supabase Dashboard:
--   Database → SQL Editor → New Query → вставьте → Run
-- ===================================================


-- ===================================================
-- РАСШИРЕНИЯ
-- ===================================================

-- UUID генерация (обычно уже включено в Supabase)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";


-- ===================================================
-- ТАБЛИЦА УСЛУГ
-- ===================================================

CREATE TABLE IF NOT EXISTS services (
    -- Уникальный идентификатор (UUID генерируется автоматически)
    id          UUID DEFAULT uuid_generate_v4() PRIMARY KEY,

    -- Название услуги (обязательное, уникальное)
    name        TEXT NOT NULL UNIQUE,

    -- Длительность в минутах (например: 60)
    duration_min INTEGER NOT NULL CHECK (duration_min > 0),

    -- Цена в рублях (целое число, > 0)
    price       INTEGER NOT NULL CHECK (price > 0),

    -- Видна ли услуга клиентам (false = скрыта, не удалена)
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,

    -- Время создания (заполняется автоматически)
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Индекс для быстрого поиска активных услуг
CREATE INDEX IF NOT EXISTS idx_services_active ON services (is_active);


-- ===================================================
-- ТАБЛИЦА ВРЕМЕННЫХ СЛОТОВ
-- ===================================================

CREATE TABLE IF NOT EXISTS time_slots (
    id          UUID DEFAULT uuid_generate_v4() PRIMARY KEY,

    -- Дата рабочего дня (например: 2024-03-15)
    slot_date   DATE NOT NULL,

    -- Время начала слота (например: 10:00:00)
    slot_time   TIME NOT NULL,

    -- Доступен ли слот для записи
    is_available BOOLEAN NOT NULL DEFAULT TRUE,

    -- Уникальность: один слот = одна дата + одно время
    UNIQUE (slot_date, slot_time)
);

-- Индексы для быстрого поиска
CREATE INDEX IF NOT EXISTS idx_slots_date ON time_slots (slot_date);
CREATE INDEX IF NOT EXISTS idx_slots_available ON time_slots (slot_date, is_available);


-- ===================================================
-- ТАБЛИЦА БРОНИРОВАНИЙ
-- ===================================================

CREATE TABLE IF NOT EXISTS bookings (
    id           UUID DEFAULT uuid_generate_v4() PRIMARY KEY,

    -- Данные клиента (из Telegram)
    user_id      BIGINT NOT NULL,          -- Telegram User ID
    username     TEXT,                     -- @username (может быть NULL)
    full_name    TEXT NOT NULL,            -- Имя из профиля
    phone        TEXT NOT NULL,            -- Номер телефона

    -- Ссылка на услугу (внешний ключ)
    -- ON DELETE RESTRICT — нельзя удалить услугу с бронированиями
    service_id   UUID NOT NULL REFERENCES services(id) ON DELETE RESTRICT,

    -- Дата и время визита
    booking_date DATE NOT NULL,
    booking_time TIME NOT NULL,

    -- Статус записи
    -- pending   = создана, ожидает подтверждения администратором
    -- confirmed = подтверждена
    -- cancelled = отменена
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'confirmed', 'cancelled')),

    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Индексы для быстрых запросов в админке
CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings (status);
CREATE INDEX IF NOT EXISTS idx_bookings_date ON bookings (booking_date);
CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings (user_id);


-- ===================================================
-- ТЕСТОВЫЕ ДАННЫЕ (опционально, для проверки)
-- ===================================================
-- Раскомментируйте и выполните отдельно для заполнения тестовыми данными

-- INSERT INTO services (name, duration_min, price) VALUES
--     ('Маникюр классический', 60, 1000),
--     ('Маникюр + гель-лак', 90, 1500),
--     ('Педикюр классический', 75, 1200),
--     ('Педикюр + гель-лак', 105, 1800),
--     ('Наращивание ногтей (гель)', 180, 3000);

-- -- Добавим слоты на ближайшие дни (замените даты)
-- INSERT INTO time_slots (slot_date, slot_time) VALUES
--     ('2024-03-20', '10:00'),
--     ('2024-03-20', '11:00'),
--     ('2024-03-20', '12:00'),
--     ('2024-03-20', '14:00'),
--     ('2024-03-20', '15:00'),
--     ('2024-03-20', '16:00'),
--     ('2024-03-21', '10:00'),
--     ('2024-03-21', '11:30'),
--     ('2024-03-21', '14:00'),
--     ('2024-03-22', '10:00'),
--     ('2024-03-22', '13:00'),
--     ('2024-03-22', '15:30');
