-- Схема notification-service. Идемпотентна: применяется при каждом старте сервиса.

CREATE SCHEMA IF NOT EXISTS notifications;

-- Журнал попыток отправки: одна строка на обработанное сообщение очереди
CREATE TABLE IF NOT EXISTS notifications.sent_emails (
    notification_id uuid        PRIMARY KEY,
    -- Пусто, если событие не удалось разобрать и адресат неизвестен
    to_email        text        NOT NULL,
    subject         text        NOT NULL,
    status          text        NOT NULL CHECK (status IN ('SENT', 'FAILED')),
    -- Текст ошибки для FAILED, иначе пусто
    error           text        NOT NULL DEFAULT '',
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- ListNotifications: письма адресату (без учёта регистра), новые первыми
CREATE INDEX IF NOT EXISTS sent_emails_to_created_idx
    ON notifications.sent_emails (lower(to_email), created_at DESC, notification_id DESC);
