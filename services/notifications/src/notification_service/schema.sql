-- Схема notification-service. Идемпотентна: применяется при каждом старте сервиса.

CREATE SCHEMA IF NOT EXISTS notifications;

-- Журнал попыток отправки: одна строка на обработанное сообщение очереди
CREATE TABLE IF NOT EXISTS notifications.sent_emails (
    notification_id uuid        PRIMARY KEY,
    -- Пусто, если событие не удалось разобрать и адресат неизвестен
    to_email        text        NOT NULL,
    subject         text        NOT NULL,
    status          text        NOT NULL,
    -- Текст ошибки для FAILED, причина для SKIPPED, иначе пусто
    error           text        NOT NULL DEFAULT '',
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- CHECK отдельно от CREATE TABLE: в базе, созданной до статуса SKIPPED, ограничение пересоздаётся
ALTER TABLE notifications.sent_emails DROP CONSTRAINT IF EXISTS sent_emails_status_check;
ALTER TABLE notifications.sent_emails
    ADD CONSTRAINT sent_emails_status_check CHECK (status IN ('SENT', 'FAILED', 'SKIPPED'));

-- ListNotifications: письма адресату (без учёта регистра), новые первыми
CREATE INDEX IF NOT EXISTS sent_emails_to_created_idx
    ON notifications.sent_emails (lower(to_email), created_at DESC, notification_id DESC);
