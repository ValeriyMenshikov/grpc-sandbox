# Промт: фронтенд для gRPC-стенда

Готовый промт для агента/разработчика. Факты в нём сверены с кодом на коммите `2e8acdc`.

---

## Задача

В репозитории `grpc-sandbox` (учебный gRPC-стенд маркетплейса) нужен веб-фронтенд покупателя.
Он поднимается тем же `docker compose` — после `make up` стенд работает целиком, включая UI в
браузере. Бэкенд менять не нужно: весь API уже есть в HTTP-фасаде `gateway`.

Стек — на твой выбор (React/Vue/Svelte/SolidJS, TS или JS, SSR не нужен). Критерий выбора один:
образ собирается в одну стадию сборки + статика, поднимается в compose и проходит healthcheck.

## Что уже есть (прочитай перед началом)

- `docs/stand/grpc-stand-TZ.md` — ТЗ стенда, `docs/api.md` — gRPC-контракты и коды ошибок,
  `docs/decisions.md` — принятые решения (§16 — про gateway), `README.md` — запуск и раскладка
- `services/gateway/src/gateway/` — HTTP-фасад: `routers/<группа>.py` (эндпоинты), `schemas.py`
  (точные JSON-модели ответов), `errors.py` (gRPC-код → HTTP-код и формат тела ошибки)
- `docker-compose.yml` — стенд: postgres, redis, users, catalog, orders, support, gateway
- OpenAPI живого стенда: `http://localhost:8080/docs` и `/openapi.json` после `make up`

**Единственный источник данных для фронта — REST gateway.** Напрямую в gRPC-сервисы, Postgres или
Redis из браузера не ходим.

## API gateway (порт 8080 внутри сети, `${GATEWAY_PORT:-8080}` на хосте)

Все ответы — JSON. Авторизация — `Authorization: Bearer <access_token>`.

| Метод | Путь | Тело/параметры | Ответ |
|---|---|---|---|
| GET | `/healthz` | — | `{"status":"ok"}` |
| POST | `/auth/sign-up` | `{email, password, display_name?, role?}`, `role` — `BUYER`\|`SELLER` | 201, `User` |
| POST | `/auth/confirm` | `{email, code}` | `User` |
| POST | `/auth/sign-in` | `{email, password}` | `{access_token, expires_at, user}` |
| GET | `/me` | — (нужен токен) | `User` |
| GET | `/products` | `query`, `category`, `min_price_kopecks`, `max_price_kopecks`, `sort`, `page_size`, `page_token` | `{products[], next_page_token}` |
| GET | `/products/{product_id}` | — | `Product` |
| GET | `/cart` | — (токен) | `{items[], total}` |
| POST | `/cart/items` | `{product_id, quantity}` | `Cart` |
| DELETE | `/cart/items/{product_id}` | — | `Cart` |
| POST | `/checkout` | заголовок `Idempotency-Key` | `Order` |
| GET | `/orders` | `status`, `page_size`, `page_token` | `{orders[], next_page_token}` |
| GET | `/orders/{order_id}` | — | `Order` |

Детали, которые легко упустить:

- `sort` — `name` \| `price_asc` \| `price_desc` \| `newest`; `page_size=0` = размер по умолчанию
  сервиса; пагинация — курсорная: `next_page_token` пустой → страниц больше нет
- `status` заказа — `CREATED` \| `PAID` \| `ASSEMBLING` \| `HANDED_TO_COURIER` \| `DELIVERED` \| `CANCELLED`
- деньги — объект `{currency_code, units, nanos}` (`units` — рубли, `nanos` — доли рубля);
  цена товара тоже приходит как `Money`, а фильтры в запросе — в копейках (`*_kopecks`)
- даты — ISO 8601 UTC, незаданные приходят как `null` (`phone`, `expires_at`, `created_at`, …)
- `Idempotency-Key` у `/checkout` обязателен по смыслу: без него order-service ответит 400.
  Генерируй uuid на попытку оформления и **переиспользуй его при ретрае того же заказа**
- ошибка стенда: `{"error":{"code":"NOT_FOUND","message":"...","details":[...]}}`, где `code` — имя
  gRPC-статуса, а `details` — google.rpc rich details (`BadRequest.field_violations`,
  `PreconditionFailure`, `ErrorInfo`, `QuotaFailure`) — их стоит показывать пользователю
  поштучно, это учебная ценность стенда
- ошибка валидации самого HTTP-запроса — обычные 422 FastAPI (`{"detail":[...]}`), другой формат
- 401 приходит с `WWW-Authenticate: Bearer` — повод разлогинить и отправить на вход
- 503 = сосед gateway недоступен, 504 = не успел в deadline: показывай как «сервис недоступен,
  попробуйте снова», без разлогина

## Ограничения стенда, с которыми надо считаться

1. **CORS в gateway нет.** Поэтому фронт отдаётся тем же origin, что и API: контейнер фронта —
   nginx (или любой статик-сервер), который раздаёт сборку и проксирует `/api/*` на
   `http://gateway:8080/*` внутри сети compose. Браузер ходит только на origin фронта. Правки
   бэкенда не нужны — так и сделай.
2. **Код подтверждения email никуда не отправляется** — он живёт только в Redis
   (`confirm:{email}`, TTL `CONFIRM_CODE_TTL_S=900`), ни в ответе, ни в логах его нет. Значит
   сценарий регистрации в UI доводится до экрана «введите код», а сам код взять негде. Что делать:
   - основной демо-вход — сид-продавец `seller@stand.local` / `seller-password` и любой
     пользователь, зарегистрированный заранее;
   - на экране подтверждения честно напиши, где взять код
     (`docker compose exec redis redis-cli get confirm:<email>`);
   - если хочется автоматического сценария — предложи отдельной задачей dev-эндпоинт в gateway,
     сам бэкенд в рамках этой задачи не меняй.
3. **Стримов в REST нет.** `TrackOrder` (статус доставки) и `Chat` с поддержкой — только gRPC,
   gateway их не публикует. Статус заказа в UI — поллинг `GET /orders/{id}`; доставка идёт шагами
   по `FULFILLMENT_STEP_MS` (по умолчанию 2 с, 4 шага до `DELIVERED`), так что интервал 1–2 с
   выглядит живым. Чат из UI не делаем.
4. **Кабинета продавца в REST тоже нет** (импорт/экспорт товаров — только gRPC). Фронт —
   покупательский.
5. `GET /products` возвращает `stock`, но корзина проверяет остаток на бэкенде: добавление
   большего количества вернёт 400/409 с rich details — это нужно показать, а не прятать.

## Жёсткие требования к интеграции в репозиторий

- Фронтенд живёт в **`frontend/` в корне репозитория**, не в `services/`: корневой
  `pyproject.toml` объявляет `members = ["pb", "packages/*", "services/*"]`, и каталог без
  `pyproject.toml` внутри `services/` ломает `uv sync` («Workspace member … is missing a
  `pyproject.toml`»), то есть `make install` и сборку образа. (Альтернатива — `services/frontend`
  плюс `exclude` в `tool.uv.workspace`, но проще не трогать workspace.)
- Новый сервис в `docker-compose.yml` рядом с `gateway`, по конвенциям файла:
  - `<<: *restart`, свой `build.context: ./frontend`, `mem_limit` (бюджет стенда — см. README,
    держись в пределах 128m)
  - порт внутри контейнера — литералом в compose; на хост — через `${FRONTEND_PORT:-3000}`
  - `depends_on: gateway: condition: service_healthy`
  - `healthcheck` обязателен: `make up` = `docker compose up -d --build --wait`, без healthcheck
    «поднялся» ничего не значит. Проверка не должна требовать доустановки пакетов в образ
    (в `nginx:alpine` есть busybox `wget`, `curl` нет)
  - адрес API — переменной окружения (`GATEWAY_URL` / `API_BASE`), а не хардкодом
- `FRONTEND_PORT` и прочие новые переменные — в `.env.example` с комментарием, как у остальных
- Многостадийная сборка: `node:…-alpine` для сборки → лёгкий runtime без node_modules.
  `frontend/.dockerignore` с `node_modules`, `dist` обязателен (корневой `.dockerignore` на
  контекст `frontend/` не действует)
- Лок-файл зависимостей (`package-lock.json`/`pnpm-lock.yaml`) коммитится, сборка — `npm ci`
- `make check` и `make test` — Python-only и должны остаться зелёными. Проверки фронта — своими
  командами (`npm run lint`, `npm test`) и, если удобно, отдельными make-целями
  (`front-lint`, `front-test`); в существующие цели их не вшивай
- `make up`, `make down`, `make reset` продолжают работать как есть, без новых шагов

## Объём UI (минимум)

1. **Вход/регистрация** — `/auth/sign-in`, `/auth/sign-up`, экран подтверждения кода с подсказкой
   из п.2 ограничений; токен в памяти + `localStorage`, подстановка `Authorization` во все
   запросы, автологаут на 401, `/me` в шапке
2. **Каталог** — поиск по `query`, фильтры по категории и цене (в UI рубли, в запросе копейки),
   сортировка, пагинация по `next_page_token`, пустой результат и состояние загрузки
3. **Карточка товара** — цена, категория, остаток, кнопка «в корзину» с количеством
4. **Корзина** — позиции, цена за единицу, итог, удаление позиции, доступный остаток
5. **Оформление** — `POST /checkout` с `Idempotency-Key`, обработка повторного клика (тот же ключ),
   переход на страницу заказа
6. **Заказы** — список с фильтром по статусу и пагинацией; страница заказа с поллингом статуса и
   видимым прогрессом `CREATED → PAID → ASSEMBLING → HANDED_TO_COURIER → DELIVERED`
7. **Ошибки** — единый разбор тела `{"error":{code,message,details}}`: сообщение + расшифровка
   rich details; отдельно 422, 401, 503/504

Дизайн — минимальный и аккуратный; UI-библиотека по желанию. Локализация не нужна, но текст —
на русском, как остальная документация стенда.

## Что нужно обновить в документации

- `README.md` — раздел про фронтенд: порт, как открыть, как устроено проксирование `/api`
- `.env.example` — `FRONTEND_PORT` (и всё новое)
- `docs/decisions.md` — новый пункт: почему `frontend/` в корне, почему nginx-прокси вместо CORS,
  почему поллинг вместо стрима
- `CLAUDE.md` — строка про раскладку фронтенда, если появляются неочевидные конвенции
- `docs/stand/grpc-stand-TZ.md` — дерево каталогов

Язык комментариев и документации — русский, сообщения в UI — русский (как в стенде).

## Критерии готовности

1. `cp .env.example .env && make up` — все контейнеры, включая фронтенд, `healthy`;
   `http://localhost:${FRONTEND_PORT:-3000}` открывается
2. Сквозной сценарий в браузере: вход сид-продавцом → поиск товара → карточка → корзина →
   `/checkout` → заказ доходит до `DELIVERED` без перезагрузки страницы
3. Повторный клик «оформить» не создаёт второй заказ (один `Idempotency-Key`)
4. Погашенный сосед (`docker compose stop catalog`) даёт понятное сообщение, а не белый экран
5. `make check && make test` и `make smoke` — зелёные, как до изменений
6. `make down && make up` воспроизводит всё с нуля, без ручных шагов

## Как работать

Сначала прочитай `README.md`, `docs/decisions.md` §16 и `services/gateway/src/gateway/schemas.py`,
подними стенд (`make up`) и посмотри `http://localhost:8080/docs`. Если по ходу решаешь что-то
неочевидное — добавляй пункт в `docs/decisions.md`. Коммиты — `feat: …` / `fix: …` / `docs: …`.
Если упираешься в ограничение бэкенда — не правь бэкенд молча: опиши, какой эндпоинт нужен и
почему, и доведи остальное до конца.
