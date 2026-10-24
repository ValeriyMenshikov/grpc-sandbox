-- Схема catalog-service. Идемпотентна: применяется при каждом старте сервиса.

CREATE SCHEMA IF NOT EXISTS catalog;

CREATE TABLE IF NOT EXISTS catalog.products (
    product_id    text        PRIMARY KEY DEFAULT gen_random_uuid()::text,
    seller_id     text        NOT NULL,
    -- Артикул продавца, уникален в рамках продавца
    offer_id      text        NOT NULL,
    name          text        NOT NULL,
    category      text        NOT NULL,
    price_kopecks bigint      NOT NULL CHECK (price_kopecks BETWEEN 1 AND 1000000000000),
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (seller_id, offer_id)
);

CREATE INDEX IF NOT EXISTS products_category_idx ON catalog.products (category);
CREATE INDEX IF NOT EXISTS products_seller_updated_idx
    ON catalog.products (seller_id, updated_at, product_id);

-- Остаток на складе; доступно = quantity - резервы
CREATE TABLE IF NOT EXISTS catalog.stocks (
    product_id text   PRIMARY KEY REFERENCES catalog.products (product_id) ON DELETE CASCADE,
    quantity   bigint NOT NULL CHECK (quantity >= 0)
);

-- Резервы под заказы (StockService.ReserveStock / ReleaseStock)
CREATE TABLE IF NOT EXISTS catalog.reservations (
    order_id   text        NOT NULL,
    product_id text        NOT NULL REFERENCES catalog.products (product_id) ON DELETE CASCADE,
    quantity   bigint      NOT NULL CHECK (quantity > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (order_id, product_id)
);

CREATE INDEX IF NOT EXISTS reservations_product_idx ON catalog.reservations (product_id);

-- Сиды: товары продавца-сида seller@stand.local. Его id фиксирован (docs/decisions.md),
-- user-service создаёт этого продавца с тем же id.
INSERT INTO catalog.products (seller_id, offer_id, name, category, price_kopecks)
VALUES
    ('00000000-0000-4000-8000-000000000001', 'EL-001', 'Смартфон Nova 12', 'electronics', 2499000),
    ('00000000-0000-4000-8000-000000000001', 'EL-002', 'Наушники Pulse ANC', 'electronics', 899000),
    ('00000000-0000-4000-8000-000000000001', 'EL-003', 'Ноутбук Air 14', 'electronics', 6999000),
    ('00000000-0000-4000-8000-000000000001', 'EL-004', 'Умные часы Fit 3', 'electronics', 1299000),
    ('00000000-0000-4000-8000-000000000001', 'EL-005', 'Power bank 20000 мАч', 'electronics', 249000),
    ('00000000-0000-4000-8000-000000000001', 'EL-006', 'Кабель USB-C 2 м', 'electronics', 49000),
    ('00000000-0000-4000-8000-000000000001', 'BK-001', 'Книга «Чистый код»', 'books', 159000),
    ('00000000-0000-4000-8000-000000000001', 'BK-002', 'Книга «Python. К вершинам мастерства»', 'books', 299000),
    ('00000000-0000-4000-8000-000000000001', 'BK-003', 'Книга «Высоконагруженные приложения»', 'books', 249000),
    ('00000000-0000-4000-8000-000000000001', 'BK-004', 'Книга «Тестирование dot com»', 'books', 129000),
    ('00000000-0000-4000-8000-000000000001', 'BK-005', 'Книга «gRPC: запуск и эксплуатация»', 'books', 189000),
    ('00000000-0000-4000-8000-000000000001', 'BK-006', 'Блокнот в клетку A5', 'books', 19900),
    ('00000000-0000-4000-8000-000000000001', 'HM-001', 'Чайник электрический 1,7 л', 'home', 349000),
    ('00000000-0000-4000-8000-000000000001', 'HM-002', 'Кофемолка ручная', 'home', 219000),
    ('00000000-0000-4000-8000-000000000001', 'HM-003', 'Набор кружек, 4 шт.', 'home', 129900),
    ('00000000-0000-4000-8000-000000000001', 'HM-004', 'Плед флисовый 150×200', 'home', 159000),
    ('00000000-0000-4000-8000-000000000001', 'HM-005', 'Лампа настольная LED', 'home', 189000),
    ('00000000-0000-4000-8000-000000000001', 'HM-006', 'Сковорода 28 см', 'home', 279000),
    ('00000000-0000-4000-8000-000000000001', 'SP-001', 'Коврик для йоги', 'sport', 149000),
    ('00000000-0000-4000-8000-000000000001', 'SP-002', 'Гантели 2×5 кг', 'sport', 399000),
    ('00000000-0000-4000-8000-000000000001', 'SP-003', 'Скакалка скоростная', 'sport', 59000),
    ('00000000-0000-4000-8000-000000000001', 'SP-004', 'Бутылка для воды 0,7 л', 'sport', 79000),
    ('00000000-0000-4000-8000-000000000001', 'SP-005', 'Мяч футбольный, размер 5', 'sport', 249000),
    ('00000000-0000-4000-8000-000000000001', 'SP-006', 'Велосипедный шлем', 'sport', 459000)
ON CONFLICT (seller_id, offer_id) DO NOTHING;

-- Остатки сидов: от 5 до 100 штук, кроме одного товара, которого нет в наличии (SP-006)
INSERT INTO catalog.stocks (product_id, quantity)
SELECT product_id,
       CASE offer_id
           WHEN 'SP-006' THEN 0
           ELSE 5 + (abs(hashtext(offer_id)) % 96)
       END
FROM catalog.products
WHERE seller_id = '00000000-0000-4000-8000-000000000001'
ON CONFLICT (product_id) DO NOTHING;
