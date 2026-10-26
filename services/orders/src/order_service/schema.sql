-- Схема order-service. Идемпотентна: применяется при каждом старте сервиса.

CREATE SCHEMA IF NOT EXISTS orders;

CREATE TABLE IF NOT EXISTS orders.orders (
    -- uuid, который order-service выбирает сам: он же order_id резерва в catalog
    order_id   text        PRIMARY KEY,
    user_id    text        NOT NULL,
    status     text        NOT NULL CHECK (status IN (
        'CREATED', 'PAID', 'ASSEMBLING', 'HANDED_TO_COURIER', 'DELIVERED', 'CANCELLED'
    )),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- ListOrders: заказы пользователя, новые первыми
CREATE INDEX IF NOT EXISTS orders_user_created_idx
    ON orders.orders (user_id, created_at DESC, order_id DESC);

CREATE TABLE IF NOT EXISTS orders.order_items (
    order_id      text   NOT NULL REFERENCES orders.orders (order_id) ON DELETE CASCADE,
    -- Порядок позиций, как в корзине
    position      int    NOT NULL,
    product_id    text   NOT NULL,
    -- Название и цена — снимок на момент оформления
    name          text   NOT NULL,
    quantity      bigint NOT NULL CHECK (quantity > 0),
    price_kopecks bigint NOT NULL CHECK (price_kopecks >= 0),
    PRIMARY KEY (order_id, position)
);

-- Имитация доставки: заказы, которые ещё едут (финальные статусы в индекс не попадают)
CREATE INDEX IF NOT EXISTS orders_in_fulfillment_idx
    ON orders.orders (updated_at)
    WHERE status IN ('CREATED', 'PAID', 'ASSEMBLING', 'HANDED_TO_COURIER');

-- История смен статуса: источник истины для таймлайна покупателя. Строка пишется в той же
-- операции, что и смена статуса в orders.orders
CREATE TABLE IF NOT EXISTS orders.order_status_history (
    -- Порядок вставки: различает смены с одинаковым changed_at
    id         bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id   text        NOT NULL REFERENCES orders.orders (order_id) ON DELETE CASCADE,
    status     text        NOT NULL CHECK (status IN (
        'CREATED', 'PAID', 'ASSEMBLING', 'HANDED_TO_COURIER', 'DELIVERED', 'CANCELLED'
    )),
    changed_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS order_status_history_order_idx
    ON orders.order_status_history (order_id, changed_at);
