-- Схема support-service. Идемпотентна: применяется при каждом старте сервиса.

CREATE SCHEMA IF NOT EXISTS support;

CREATE TABLE IF NOT EXISTS support.chats (
    chat_id    text        PRIMARY KEY,
    -- Один чат на заказ; владелец заказа проверен через order-service при первом join
    order_id   text        NOT NULL UNIQUE,
    user_id    text        NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS support.messages (
    message_id        text        PRIMARY KEY,
    -- Порядок сообщений в чате: created_at двух быстрых сообщений может совпасть
    seq               bigint      GENERATED ALWAYS AS IDENTITY,
    chat_id           text        NOT NULL REFERENCES support.chats (chat_id) ON DELETE CASCADE,
    author            text        NOT NULL CHECK (author IN ('CUSTOMER', 'AGENT', 'BOT')),
    text              text        NOT NULL,
    -- Идентификатор, выданный клиентом (только у сообщений CUSTOMER)
    client_message_id text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    -- Когда покупатель прочитал сообщение (read{message_id})
    read_at           timestamptz
);

-- История и последние сообщения чата в порядке отправки
CREATE INDEX IF NOT EXISTS messages_chat_created_idx
    ON support.messages (chat_id, seq);

-- Проекция смен статуса заказа из событий order.status_changed (read model, не источник истины:
-- история — в orders.order_status_history). Заказ проходит каждый статус один раз, поэтому
-- (order_id, status) — естественный ключ: повторная доставка события ничего не добавляет
CREATE TABLE IF NOT EXISTS support.order_events (
    order_id   text        NOT NULL,
    status     text        NOT NULL,
    changed_at timestamptz NOT NULL,
    PRIMARY KEY (order_id, status)
);
