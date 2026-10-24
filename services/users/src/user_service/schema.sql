-- Схема user-service. Идемпотентна: применяется при каждом старте сервиса.

CREATE SCHEMA IF NOT EXISTS users;

CREATE TABLE IF NOT EXISTS users.users (
    user_id       text        PRIMARY KEY DEFAULT gen_random_uuid()::text,
    -- Нормализованный email (обрезанные пробелы, нижний регистр)
    email         text        NOT NULL UNIQUE,
    -- scrypt$n$r$p$salt$hash, см. passwords.py
    password_hash text        NOT NULL,
    display_name  text        NOT NULL,
    phone         text,
    role          text        NOT NULL CHECK (role IN ('BUYER', 'SELLER')),
    status        text        NOT NULL CHECK (status IN ('PENDING', 'ACTIVE')),
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

-- Сид продавца seller@stand.local (id фиксирован, см. docs/decisions.md) пишет
-- UserRepository.connect(): хэш пароля из env SEED_SELLER_PASSWORD в SQL не посчитать.
