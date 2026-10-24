# Учебный gRPC-стенд маркетплейса (реализация ТЗ docs/stand/grpc-stand-TZ.md)

## Overview

Пишем с нуля учебный стенд: упрощённый бэкенд маркетплейса из gRPC-сервисов (user, catalog, order, support) и REST-шлюза (gateway). Всё поднимается одной командой в docker compose вместе с Postgres и Redis. Общая библиотека stand_core содержит декоратор rpc в стиле Nuke, сервер grpc.aio со сверкой с proto, reflection, health и graceful stop, интерцепторы, rich error model, nuke-di клиенты к Postgres, Redis и соседним сервисам. Все сервисы покрыты собственными тестами, есть smoke-сценарий против поднятого стенда. Документация: README, docs/api.md, docs/decisions.md.

## Context

- Источник требований: docs/stand/grpc-stand-TZ.md (разделы 2–12; DoD — раздел 10)
- Репозиторий пустой (README.md, .gitignore, ТЗ). Корень стенда = корень репозитория (в ТЗ он назван grpc-stand/), это решение пишем в docs/decisions.md
- Файлы: Makefile, pyproject.toml, uv.lock, .env.example, docker-compose.yml, docker/Dockerfile, protos/**, gen/**, packages/stand_core/**, services/{users,catalog,orders,support,gateway}/**, docs/api.md, docs/decisions.md, README.md
- Образцы: API декоратора rpc и сервера Nuke (раздел 5 ТЗ); гайды nuke-di (clients, servers-in-workers/grpc.aio, testing, fastapi)
- Зависимости: Python 3.12+, uv workspace, nuke-di 2.x, grpcio, grpcio-tools, grpcio-status, grpcio-reflection, grpcio-health-checking, googleapis-common-protos, mypy-protobuf, protobuf, asyncpg, redis, pydantic-settings, structlog, fastapi, uvicorn, httpx (тесты gateway), pytest, pytest-asyncio, ruff, mypy

## Development Approach

- Testing approach: Regular (сначала код, потом тесты)
- Каждую задачу доводим до конца, прежде чем браться за следующую. Порядок — как в разделе 12 ТЗ
- После каждой задачи: make check && make test, коммит с понятным сообщением
- Неоднозначности решаем самым простым способом и записываем в docs/decisions.md по ходу работы
- mypy strict без type: ignore вне gen/ (исключения обосновываем в decisions.md)
- Один хэндлер — один файл с суффиксом типа вызова (_u_u, _s_u, _u_s, _s_s)
- Тесты, которым нужны Postgres/Redis, используют контейнеры из compose (make up). Unit-тесты хэндлеров обходятся без инфраструктуры: клиенты подменяются через DI.override / mock
- CRITICAL: every task MUST include new/updated tests
- CRITICAL: all tests must pass before starting next task

## Implementation Steps

### Task 1: Каркас workspace, Makefile, инструменты, Docker и compose с инфраструктурой

**Files:**

- Create: `pyproject.toml` (uv workspace, ruff target py312, mypy strict python_version 3.12 + плагин nuke-di, исключение gen/, настройки pytest с маркером stand)
- Create: `Makefile` (install, gen, format, lint, typecheck, check, test, up, down, logs, ps, stats, reset)
- Create: `.env.example` (все переменные из раздела 7 с дефолтами)
- Create: `docker/Dockerfile` (многостадийный, python:${PYTHON_VERSION}-slim + uv, без dev-зависимостей в рантайме)
- Create: `docker-compose.yml` (пока postgres-alpine и redis-alpine с healthcheck, mem_limit, restart)
- Create: `packages/stand_core/pyproject.toml`, `packages/stand_core/src/stand_core/__init__.py`
- Create: `docs/decisions.md`
- Modify: `.gitignore` (.env, .idea, .ralphex)
- [x] настроить uv workspace (members: packages/*, services/*), зависимости и dev-группу
- [x] Makefile со всеми целями раздела 8; make test запускает pytest без маркера stand, отдельная цель или переменная — для smoke
- [x] Dockerfile и compose: Postgres и Redis с healthcheck, mem_limit, restart: unless-stopped
- [x] заготовка docs/decisions.md (первая запись — корень стенда = корень репо)
- [x] smoke-тест импорта stand_core, чтобы pytest имел что запускать
- [x] make install && make check && make test — зелёные

### Task 2: Proto-контракты и кодогенерация

**Files:**

- Create: `protos/common/v1/money.proto`, `protos/users/v1/users.proto`, `protos/catalog/v1/catalog.proto`, `protos/catalog/v2/catalog.proto`, `protos/orders/v1/orders.proto`, `protos/support/v1/support.proto`
- Create: `gen/**` (сгенерированный код в git), `gen` как пакет workspace или путь в sys.path
- Modify: `Makefile` (цель gen: grpc_tools.protoc --python_out --pyi_out --grpc_python_out + mypy-protobuf)
- [x] common.v1: Money (units, nanos, currency_code), Pagination
- [x] users.v1 UserService: SignUp, ConfirmEmail, SignIn, SignOut, GetMe, UpdateProfile (FieldMask), LegacyResetPassword; роли BUYER/SELLER, статусы пользователя
- [x] catalog.v1: CatalogService (GetProduct, SearchProducts, ImportProducts client-stream с заголовком в oneof, ExportProducts server-stream c updated_since), StockService (GetStock, ReserveStock, ReleaseStock); Product.price_kopecks int64
- [x] catalog.v2 CatalogService: GetProduct, SearchProducts с обязательным region_id; price — common.v1.Money под другим номером поля, price_kopecks удалён без reserved
- [x] orders.v1 OrderService: корзина, Checkout, GetOrder, ListOrders (фильтр по статусу, пагинация), CancelOrder, TrackOrder; enum статусов CREATED..DELIVERED, CANCELLED
- [x] support.v1 SupportService: Chat (oneof входящих join/message/read и исходящих joined/ack/message/agent_typing), GetChatHistory
- [x] make gen, сгенерированный код закоммитить; ruff и mypy исключают gen/
- [x] тест: все _pb2 импортируются, нужные сервисы и методы есть в пуле дескрипторов с правильными флагами стриминга
- [x] make check && make test — зелёные

### Task 3: stand_core — settings, логирование, ошибки, контекст, клиенты Postgres и Redis

**Files:**

- Create: `packages/stand_core/src/stand_core/settings.py` (Settings(Client) на pydantic-settings)
- Create: `packages/stand_core/src/stand_core/logging.py` (structlog JSON, маскировка секретов)
- Create: `packages/stand_core/src/stand_core/grpc/errors.py` (доменные исключения → статус + google.rpc details)
- Create: `packages/stand_core/src/stand_core/grpc/context.py` (Context, contextvars request_id и current_user)
- Create: `packages/stand_core/src/stand_core/clients/postgres.py` (asyncpg pool, применение schema.sql)
- Create: `packages/stand_core/src/stand_core/clients/redis.py`
- Create: `packages/stand_core/tests/...`
- [x] Settings как nuke-di Client: читает env, без захардкоженных адресов
- [x] логирование structlog в JSON, функция маскировки паролей, токенов и кодов
- [x] иерархия исключений (InvalidArgument, NotFound, AlreadyExists, Unauthenticated, PermissionDenied, FailedPrecondition, ResourceExhausted, DependencyUnavailable) и функция сборки grpc Status с details через grpcio-status
- [x] contextvars: request_id, current_user (id, role)
- [x] Postgres(Client) и Redis(Client): I/O только в connect/disconnect, в __init__ только зависимости
- [x] тесты: маппинг каждого исключения в статус и тип details, маскировка в логах, чтение Settings из env
- [x] make check && make test — зелёные

### Task 4: stand_core — декоратор rpc, grpc_server и связка с nuke-di

**Files:**

- Create: `packages/stand_core/src/stand_core/grpc/rpc.py` (GrpcTypeEnum, MethodSignature, MethodAnnotation, GRPC_HANDLERS, rpc)
- Create: `packages/stand_core/src/stand_core/grpc/server.py` (grpc_server(): generic handlers, сверка с дескрипторами, reflection, health, graceful stop)
- Create: `packages/stand_core/src/stand_core/grpc/di.py` (inject_handlers, resolve_interceptors)
- Create: `packages/stand_core/src/stand_core/grpc/healthcheck.py` (скрипт healthcheck для compose)
- Create: `packages/stand_core/tests/...` (тестовый proto или реальные дескрипторы из gen)
- [ ] rpc: проверка сигнатуры (request и context первыми, есть type hints, есть аннотация возврата), иначе ValueError; тип вызова по AsyncIterator в hints; функция возвращается без изменений
- [ ] grpc_server: keepalive-опции из Nuke, группировка по package.service, METHOD_MAP, add_generic_rpc_handlers, порт из GRPC_PORT
- [ ] сверка с proto до start(): метод существует, флаги стриминга и классы сообщений совпадают; методы без хэндлера — warning при старте и UNIMPLEMENTED
- [ ] reflection по зарегистрированным сервисам, health SERVING по каждому сервису, stop(grace) и stop(None) в finally
- [ ] inject_handlers / resolve_interceptors по гайду nuke-di; main.py-шаблон с @worker последним в модуле
- [ ] скрипт healthcheck на Python через стандартный health service
- [ ] тесты: неверные сигнатуры падают при декорировании; расхождения с дескриптором (тип стрима, классы сообщений, несуществующий метод) падают до старта; поднятый in-process сервер отвечает на unary и все виды стримов, health и reflection работают
- [ ] make check && make test — зелёные

### Task 5: stand_core — интерцепторы и базовый клиент к соседям

**Files:**

- Create: `packages/stand_core/src/stand_core/grpc/interceptors/` (request_id, logging, auth, stream_count, exception_handling)
- Create: `packages/stand_core/src/stand_core/clients/grpc_client.py` (базовый клиент к соседям)
- Modify: `packages/stand_core/src/stand_core/grpc/server.py` (если stream_count и exception_handling делаем обёрткой хэндлера)
- Modify: `docs/decisions.md`
- [ ] RequestIdInterceptor: x-request-id из metadata или uuid, contextvar, initial metadata в ответ
- [ ] LoggingInterceptor: одна JSON-строка на вызов (метод, тип, request_id, статус, длительность, число сообщений для стримов)
- [ ] AuthInterceptor: x-api-key обязателен везде, кроме reflection и health; таблица политик (service/user/seller) передаётся сервисом; Bearer-токен из Redis session:{token} → current_user; seller-методы для покупателя → PERMISSION_DENIED + ErrorInfo(SELLER_ROLE_REQUIRED)
- [ ] StreamCountInterceptor (x-items-count) и ExceptionHandlingInterceptor (домен → статус + details, прочее → INTERNAL, стек только в лог); если для стримов в grpc.aio это неудобно, делаем обёртку хэндлера в grpc_server и пишем это в decisions.md
- [ ] базовый клиент к соседям (nuke-di Client): канал grpc.aio, дефолтный deadline, проброс x-request-id, оставшегося deadline и authorization, UNAVAILABLE/DEADLINE_EXCEEDED → DependencyUnavailable, адрес из env
- [ ] тесты: x-request-id выставляется и пробрасывается; x-items-count в trailing metadata; доменные исключения дают нужные статусы и details; нет x-api-key → UNAUTHENTICATED; роль покупателя на seller-методе → PERMISSION_DENIED; базовый клиент превращает UNAVAILABLE и DEADLINE_EXCEEDED в DependencyUnavailable
- [ ] make check && make test — зелёные

### Task 6: catalog-service — CatalogService v1/v2

**Files:**

- Create: `services/catalog/pyproject.toml`, `services/catalog/src/catalog_service/{main.py,repository.py,schema.sql,auth.py}`
- Create: `services/catalog/src/catalog_service/handlers/{__init__.py,get_product_u_u.py,search_products_u_u.py,import_products_s_u.py,export_products_u_s.py,v2_get_product_u_u.py,v2_search_products_u_u.py}`
- Create: `services/catalog/tests/...`
- Modify: `docker-compose.yml`, `.env.example`
- [ ] schema.sql (схема catalog: товары, остатки, резервы) и сиды: 20–30 товаров продавца-сида в 3–4 категориях
- [ ] GetProduct, SearchProducts (текст, категория, диапазон цены, сортировка, page_token; невалидный токен → INVALID_ARGUMENT)
- [ ] ImportProducts: заголовок обязателен первым (иначе INVALID_ARGUMENT), режимы UPSERT/CREATE_ONLY, ошибки по строкам без падения импорта, лимит IMPORT_MAX_ROWS → RESOURCE_EXHAUSTED + QuotaFailure
- [ ] ExportProducts: товары текущего продавца по одному, фильтр updated_since, проверка context.done()
- [ ] catalog.v2 GetProduct/SearchProducts на том же порту (Money, обязательный region_id)
- [ ] main.py по шаблону @worker; блок в compose (healthcheck, mem_limit, depends_on healthy)
- [ ] тесты: unit-тесты хэндлеров с замоканным репозиторием (включая плохие строки импорта, лимит, стрим без заголовка, невалидный page_token), тест wiring'а дерева клиентов
- [ ] make check && make test — зелёные

### Task 7: catalog-service — StockService

**Files:**

- Create: `services/catalog/src/catalog_service/handlers/{get_stock_u_u.py,reserve_stock_u_u.py,release_stock_u_u.py}`
- Modify: `services/catalog/src/catalog_service/repository.py`, `services/catalog/tests/...`
- [ ] GetStock: доступный остаток
- [ ] ReserveStock: атомарный резерв под order_id в транзакции, нехватка → FAILED_PRECONDITION + PreconditionFailure по товарам, идемпотентность по order_id; задержка STOCK_RESERVE_DELAY_MS и x-debug-delay-ms
- [ ] ReleaseStock: идемпотентное снятие резерва
- [ ] тесты: нехватка с деталями, повтор с тем же order_id, release дважды, задержка из env и metadata (с проверкой deadline)
- [ ] make check && make test — зелёные

### Task 8: user-service

**Files:**

- Create: `services/users/pyproject.toml`, `services/users/src/user_service/{main.py,repository.py,schema.sql,auth.py,passwords.py}`
- Create: `services/users/src/user_service/handlers/{sign_up_u_u.py,confirm_email_u_u.py,sign_in_u_u.py,sign_out_u_u.py,get_me_u_u.py,update_profile_u_u.py,legacy_reset_password_u_u.py,__init__.py}`
- Create: `services/users/tests/...`
- Modify: `docker-compose.yml`, `.env.example`
- [ ] schema.sql (схема users), хэширование паролей средствами stdlib (hashlib.scrypt) — без лишних зависимостей; сид seller@stand.local с паролем SEED_SELLER_PASSWORD, подтверждён
- [ ] SignUp (валидация → BadRequest, ALREADY_EXISTS, код в Redis confirm:{email} с TTL 15 мин), ConfirmEmail (INVALID_ARGUMENT / NOT_FOUND / FAILED_PRECONDITION)
- [ ] SignIn (session:{token} с TTL SESSION_TTL_S, expires_at; UNAUTHENTICATED / FAILED_PRECONDITION), SignOut, GetMe
- [ ] UpdateProfile через FieldMask (display_name, phone; неизвестный путь → INVALID_ARGUMENT)
- [ ] LegacyResetPassword — намеренный антипример: context.abort(UNKNOWN, "Validation failed"), с комментарием в коде
- [ ] блок в compose
- [ ] тесты: unit-тесты всех хэндлеров с замоканными репозиторием и Redis, тест wiring'а
- [ ] make check && make test — зелёные

### Task 9: order-service — корзина и Checkout со StockClient

**Files:**

- Create: `services/orders/pyproject.toml`, `services/orders/src/order_service/{main.py,repository.py,schema.sql,auth.py,stock_client.py,catalog_client.py}`
- Create: `services/orders/src/order_service/handlers/{add_cart_item_u_u.py,remove_cart_item_u_u.py,get_cart_u_u.py,checkout_u_u.py,get_order_u_u.py,list_orders_u_u.py,cancel_order_u_u.py,__init__.py}`
- Create: `services/orders/tests/...`
- Modify: `docker-compose.yml`, `.env.example`
- [ ] StockClient (и клиент к CatalogService для цен) на базовом клиенте stand_core, адрес из CATALOG_ADDR
- [ ] корзина в Redis cart:{user_id}; GetCart подтягивает цены и остатки из catalog; товар не найден → NOT_FOUND
- [ ] Checkout: idempotency-key обязателен, idem:{user_id}:{key} TTL 24 ч, пустая корзина → FAILED_PRECONDITION, ReserveStock с пробросом deadline и x-request-id, нехватка → FAILED_PRECONDITION с деталями от catalog, catalog недоступен → UNAVAILABLE без создания заказа, заказ CREATED, очистка корзины
- [ ] GetOrder (чужой → NOT_FOUND), ListOrders (новые первыми, пагинация, фильтр), CancelOrder (до HANDED_TO_COURIER, иначе FAILED_PRECONDITION; ReleaseStock)
- [ ] блок в compose
- [ ] тесты: unit-тесты с подменой StockClient через DI.override (идемпотентность, нехватка, DependencyUnavailable → UNAVAILABLE, чужой заказ, отмена после передачи курьеру), тест wiring'а
- [ ] make check && make test — зелёные

### Task 10: order-service — имитация доставки и TrackOrder

**Files:**

- Create: `services/orders/src/order_service/fulfillment.py`
- Create: `services/orders/src/order_service/handlers/track_order_u_s.py`
- Modify: `services/orders/src/order_service/main.py`, `services/orders/tests/...`
- [ ] фоновая задача внутри процесса: CREATED → PAID → ASSEMBLING → HANDED_TO_COURIER → DELIVERED с шагом FULFILLMENT_STEP_MS; каждая смена пишется в Postgres и публикуется в Redis orders.status.{order_id}; отменённые заказы не продвигаются
- [ ] TrackOrder: сначала подписка, затем текущий статус из БД (событие не теряется), дальше изменения с changed_at; закрытие после DELIVERED/CANCELLED, x-items-count
- [ ] тесты: последовательность статусов при маленьком шаге, TrackOrder отдаёт текущий статус первым и закрывается на финальном статусе (Redis pub/sub замокан или из compose)
- [ ] make check && make test — зелёные

### Task 11: support-service — Chat и GetChatHistory

**Files:**

- Create: `services/support/pyproject.toml`, `services/support/src/support_service/{main.py,repository.py,schema.sql,auth.py,orders_client.py,chat_hub.py}`
- Create: `services/support/src/support_service/handlers/{chat_s_s.py,get_chat_history_u_u.py,__init__.py}`
- Create: `services/support/tests/...`
- Modify: `docker-compose.yml`, `.env.example`
- [ ] OrdersClient (ORDERS_ADDR) с пробросом пользовательского authorization и x-request-id
- [ ] Chat: join первым (иначе FAILED_PRECONDITION), проверка заказа (чужой/нет → NOT_FOUND), joined с last_messages, ack на каждое message, сохранение в Postgres, read
- [ ] независимая отправка: через SUPPORT_AGENT_DELAY_MS — agent_typing и приветствие AGENT; чтение входящих и отправка исходящих — отдельные таски, общая очередь
- [ ] бот на «статус»/«где»: статус из order-service, при DependencyUnavailable — «Не удалось получить статус, попробуйте позже», стрим не рвётся
- [ ] idle timeout SUPPORT_IDLE_TIMEOUT_S → завершение OK с x-close-reason: idle
- [ ] GetChatHistory с пагинацией
- [ ] блок в compose
- [ ] тесты: unit-тесты Chat с подменой OrdersClient (join не первым, чужой заказ, приветствие без запроса клиента, ответ бота, недоступный order-service, idle), тест wiring'а
- [ ] make check && make test — зелёные

### Task 12: gateway (BFF)

**Files:**

- Create: `services/gateway/pyproject.toml`, `services/gateway/src/gateway/{api.py,main.py,clients.py,errors.py}`
- Create: `services/gateway/tests/...`
- Modify: `docker-compose.yml`, `.env.example`
- [ ] FastAPI + nuke_di.fastapi.setup; gRPC-клиенты к users, catalog, orders как nuke-di Client, сами подставляют x-api-key и пробрасывают authorization
- [ ] эндпоинты: /auth/sign-up, /auth/confirm, /auth/sign-in, /me, /products, /products/{id}, /cart, /cart/items, /cart/items/{product_id}, /checkout (Idempotency-Key), /orders, /orders/{id}
- [ ] маппинг gRPC-статусов в HTTP-коды
- [ ] блок в compose (healthcheck по HTTP)
- [ ] тесты: эндпоинты через httpx/TestClient с замоканными клиентами, маппинг ошибок, проброс заголовков
- [ ] make check && make test — зелёные

### Task 13: Smoke-сценарий против поднятого стенда и замер памяти

**Files:**

- Create: `tests/smoke/test_smoke.py` (маркер stand)
- Modify: `Makefile` (цель smoke), `docker-compose.yml` (подстройка mem_limit)
- [ ] smoke: SignUp → код из Redis → ConfirmEmail → SignIn; SearchProducts → AddCartItem → Checkout с idempotency-key; TrackOrder до DELIVERED; Chat: join → приветствие → «где заказ» → ответ бота; продавцом: ImportProducts с плохой строкой → отчёт → ExportProducts содержит импорт
- [ ] проверки DoD в smoke: без x-api-key → UNAUTHENTICATED; seller-метод покупателем → PERMISSION_DENIED; reflection перечисляет catalog.v1 и catalog.v2
- [ ] make up — все контейнеры healthy; прогнать smoke
- [ ] make stats — проверить ≤ ~1 ГБ, при необходимости подстроить mem_limit, записать цифры
- [ ] make check && make test — зелёные

### Task 14: Verify acceptance criteria

- [ ] make install && make gen && make check — зелёные, нет type: ignore вне gen/ без обоснования
- [ ] make check && make test на Python 3.12 и 3.14 (uv run --python 3.12 / --python 3.14)
- [ ] сборка образа с PYTHON_VERSION=3.12 и 3.14
- [ ] smoke против поднятого стенда зелёный
- [ ] покрытие тестами stand_core и хэндлеров — 80%+

### Task 15: Update documentation

- [ ] README.md: запуск за 3 команды, таблица портов, схема из раздела 3, как добавить новый сервис, результаты make stats
- [ ] docs/api.md: все методы, Auth, статус-коды, details, metadata (x-api-key, authorization, x-request-id, x-items-count, idempotency-key, x-debug-delay-ms, x-close-reason), пометка антипримера LegacyResetPassword, различия catalog v1/v2
- [ ] docs/decisions.md: все принятые по ходу решения
- [ ] CLAUDE.md: соглашения проекта (именование хэндлеров, шаблон main.py, команды Makefile)

## Post-Completion

- Ручная проверка на чистой машине: make up поднимает стенд с нуля
- grpcurl -plaintext localhost:50051..50054 list — сервисы видны через reflection
- Ручная проверка отказов: docker compose stop catalog → Checkout отдаёт UNAVAILABLE и не висит; docker compose stop orders → Chat работает, бот сообщает о недоступности
