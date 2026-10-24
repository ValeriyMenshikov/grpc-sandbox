# Решения, принятые при реализации стенда

ТЗ (docs/stand/grpc-stand-TZ.md) разрешает решать неоднозначности самым простым способом и записывать решение сюда.

## 1. Корень стенда = корень репозитория

В ТЗ структура описана от каталога `grpc-stand/`. В репозитории нет ничего, кроме стенда, поэтому лишний уровень вложенности не нужен: `Makefile`, `pyproject.toml`, `docker-compose.yml` и остальное лежат прямо в корне. Имя `grpc-stand` осталось у корневого проекта uv и у compose-проекта (`name: grpc-stand`).

## 2. Workspace и версия Python

- Корневой проект `grpc-stand` — виртуальный (`[tool.uv] package = false`), он только держит общие настройки ruff/mypy/pytest и dev-группу.
- Участники workspace: `packages/*` (stand_core) и `services/*`.
- `.python-version` = 3.12 — минимальная поддерживаемая версия, на ней идёт локальная разработка. Проверка на 3.14: `make check test PYTHON=3.14`.

## 3. Тесты и smoke

- `make test` запускает pytest с `-m 'not stand'` (задано в `addopts`), т.е. без smoke-сценария.
- `make smoke` запускает только тесты с маркером `stand` против поднятого `make up` стенда.
- pytest работает в `--import-mode=importlib`, чтобы одинаковые имена тестовых модулей в разных сервисах не конфликтовали.

## 4. Docker

- Один образ на все Python-сервисы: в рантайм-стадию копируется venv со всеми пакетами workspace (`uv sync --no-dev --all-packages --no-editable`). Сервис выбирается командой в compose. Так проще и образ собирается один раз; цена — в каждом контейнере лежит код соседей, на память это не влияет.
- `make up` = `docker compose up -d --build --wait`: `--build` добавлен, чтобы после правок кода не забывать пересобрать образ.
- Redis запущен без персистентности (`--save ''`, `--appendonly no`) и с `maxmemory 48mb` под `mem_limit: 64m`: данные стенда временные, `make reset` и так их сбрасывает.

## 5. mypy

`make typecheck` передаёт mypy только существующие каталоги из `packages services tests`, чтобы цель работала на любом этапе разработки. `gen/` исключён.

## 6. Proto-контракты и gen/

- Стиль — buf STANDARD: у каждого RPC свои `<Method>Request` / `<Method>Response` (даже `GetProduct` возвращает `GetProductResponse{product}`, а стримы — `ExportProductsResponse{product}`), значения enum с префиксом типа и нулевым `*_UNSPECIFIED` (`ORDER_STATUS_DELIVERED`, `USER_ROLE_SELLER`). Так контракт сразу проходит `buf lint`, а в уроках про `buf breaking` ломается только то, что сломано намеренно.
- `common.v1.Pagination{page_size, page_token}` вкладывается в списочные запросы полем `pagination`; `next_page_token` лежит прямо в ответе.
- Отчёт об импорте (`ImportReport` в ТЗ) — это сам `ImportProductsResponse` с полями `created`, `updated`, `failed`, `errors`, без лишней обёртки.
- catalog.v2: `Product.price` (`common.v1.Money`) — поле 10, номер 6 (`price_kopecks` в v1) свободен и **не** `reserved`. Фильтры цены в v2 — `Money min_price/max_price` (8, 9), номера 3 и 4 из v1 не используются. `region_id` — поле 7; обязательность проверяет сервер (в proto3 нет required).
- `gen/` — отдельный участник workspace `stand-protos` (`gen/pyproject.toml`), верхнеуровневые пакеты совпадают с каталогами protos: `common`, `users`, `catalog`, `orders`, `support`. Импорт: `from catalog.v1 import catalog_pb2`. `make gen` пересоздаёт только эти каталоги, `gen/pyproject.toml` не трогает, и докладывает `__init__.py` и `py.typed`.
- `.pyi` генерирует mypy-protobuf (`--mypy_out`, `--mypy_grpc_out`), а не `--pyi_out` protoc: оба пишут в один и тот же `*_pb2.pyi`, а стабы mypy-protobuf полнее (типизированные enum, oneof, gRPC-стабы для grpc.aio). Для mypy в dev-группе `types-grpcio` и `types-protobuf`.
- Нижние границы `grpcio` и `protobuf` в `stand-protos` равны версиям генератора: сгенерированный код проверяет версию рантайма при импорте.

## 7. stand_core: настройки, логи, ошибки, клиенты

- `Settings` наследует `BaseSettings` и `nuke_di.Client` одновременно и объявляет `__init__(self) -> None`: иначе mypy синтезирует `__init__` из полей, и плагин nuke-di считает каждое поле зависимостью-клиентом. Подклассы настроек в сервисах делают так же. Конфликт pydantic-хуков `__get_pydantic_*_schema__` у двух баз снят явным переопределением со стандартным поведением pydantic. `.env` pydantic-settings не читает — переменные приходят из окружения (compose `env_file`).
- Адреса (`POSTGRES_DSN`, `REDIS_URL`) не имеют значений по умолчанию и необязательны в `Settings`: сервис без Postgres/Redis не обязан их задавать. `Postgres` и `Redis` падают с понятной ошибкой в `connect()`, если адреса нет. `STAND_API_KEY` обязателен.
- `Postgres.apply_schema(path)` выполняет `schema.sql` целиком; вызывает его `connect()` репозитория сервиса (репозиторий зависит от `Postgres` и подключается после него).
- `Redis` работает с `decode_responses=True`: ключи и значения — `str`.
- Маскировка в логах — по именам ключей (`password`, `*_token`, `authorization`, `x-api-key`, `code`, ...) на любой глубине, плюс `Bearer <token>` в строках. Ключ `code` маскируется всегда (это код подтверждения), поэтому статус вызова логируется под ключом `status`.
- `build_status()` переводит доменное исключение в `grpc.Status` с `google.rpc.Status` в `grpc-status-details-bin`; у любого другого исключения — `INTERNAL` с текстом `Internal error`, без текста и стека исключения. `ERROR_DOMAIN` для `ErrorInfo` — `stand.local`. `DependencyUnavailable` — `ErrorInfo(reason="DEPENDENCY_UNAVAILABLE", metadata={"dependency": ...})`.
- ruff: `RUF001`–`RUF003` выключены — докстринги и комментарии на русском. mypy: `googleapis-common-protos` поставляет `.pyi` без `py.typed`, для `google.rpc.*` включён `follow_untyped_imports`; стабы `asyncpg-stubs` и `types-grpcio-status` — в dev-группе.

## 8. stand_core: декоратор rpc, grpc_server, связка с nuke-di

- `rpc` требует, чтобы первые два аргумента назывались именно `request` и `context` и были позиционными; оба с type hints, плюс аннотация возврата. Исходящий стрим — `AsyncIterator[Resp]` (принимается и `AsyncGenerator[Resp, None]`), и такой хэндлер обязан быть async-генератором; unary — `async def`. Повторная регистрация того же метода другой функцией — `ValueError` (повторное декорирование той же функции — не ошибка).
- `grpc_server(handlers, interceptors, *, port=None, grace=None, host="[::]")` отдаёт `RunningServer(server, port, services)`. `port` по умолчанию — env `GRPC_PORT` (0 — свободный порт, для тестов), `grace` — `SHUTDOWN_GRACE_SECONDS - 1`, чтобы `server.stop(grace)` гарантированно уложился в общий таймаут остановки. Env читается напрямую, а не через `Settings`: серверу не нужен `STAND_API_KEY`, и `grpc_server` остаётся вызываемым без контейнера.
- Сверка с proto собирает все расхождения в одну `ProtoMismatchError(ValueError)` до создания сервера. Методы сервиса без хэндлера — одно warning-событие `grpc.unimplemented_methods` на сервис; UNIMPLEMENTED отвечает сам grpc (generic handler не знает метода).
- Health: общий статус `""` — `NOT_SERVING` до `start()`, затем `SERVING` вместе с каждым сервисом; перед `stop(grace)` — `enter_graceful_shutdown()` (всё `NOT_SERVING`). Reflection отдаёт сервисы хэндлеров, `grpc.health.v1.Health` и сам reflection.
- Graceful stop — только при нормальном выходе из блока (`shutdown.wait()` вернулся); при исключении в блоке сразу `stop(None)` в `finally`.
- `resolve_interceptors()` без аргументов резолвит `DEFAULT_INTERCEPTORS` (раздел 9); можно передать свой список. `inject_handlers` возвращает копию реестра, `GRPC_HANDLERS` не меняется.
- Healthcheck для compose — `python -m stand_core.grpc.healthcheck [--addr] [--service] [--timeout]`. Вызов `Check` идёт через `channel.unary_unary`, а не `HealthStub`: в `types-grpcio-health-checking` у стаба нет методов, а `type: ignore` вне gen/ не используем. В dev-группе добавлены `types-grpcio-health-checking` и `types-grpcio-reflection`.
- Процесс `@worker`, остановленный SIGTERM, завершается кодом 143 (128 + сигнал) — так nuke-di сообщает об остановке по сигналу, это не ошибка.
- Тесты stand_core изолируют глобальный `GRPC_HANDLERS` и сбрасывают structlog после каждого теста (conftest). Шаблон `main.py` проверяется end-to-end: `tests/example_main.py` запускается отдельным процессом, отвечает на вызов с внедрённым клиентом и останавливается по SIGTERM.

## 9. stand_core: интерцепторы и базовый клиент к соседям

- Все пять интерцепторов — настоящие `grpc.aio.ServerInterceptor` (и nuke-di `Client`), обёртка хэндлера в `grpc_server` не понадобилась. Общая база `CallInterceptor` подменяет behavior `RpcMethodHandler` любого из четырёх типов: каждый вызов выполняется внутри `around(call)` — async context manager'а, который видит `context`, исключения хэндлера и счётчики сообщений (`received` для входящих стримов, `sent` для исходящих). Публичный API `rpc` не менялся.
- Порядок — `DEFAULT_INTERCEPTORS`: RequestId → Logging → Auth → StreamCount → ExceptionHandling (первый — самый внешний). Поэтому Logging видит уже готовый статус (после `abort`, через `context.code()`), а AuthInterceptor, который стоит снаружи ExceptionHandling, сам вызывает `abort_with_error`.
- Health и reflection (`/grpc.health.v1.Health/`, `/grpc.reflection.`) интерцепторы стенда не трогают вовсе: им не нужен `x-api-key`, а healthcheck compose не засоряет логи строкой на каждый probe. Такие вызовы идут без `x-request-id`.
- grpc.aio запускает каждый вызов в отдельной задаче, поэтому contextvars (`request_id`, `current_user`, `authorization`, deadline) не протекают между вызовами; интерцепторы всё равно сбрасывают их по выходе.
- `context.abort(code, details, trailing_metadata)` заменяет уже выставленную trailing metadata, а `set_trailing_metadata` после abort игнорируется. Поэтому `abort_with_error` склеивает текущую trailing metadata с `grpc-status-details-bin`, а `x-items-count` выставляется только при успешном завершении стрима (к trailing metadata хэндлера, например `x-close-reason`, добавляется, а не заменяет её). Trailing metadata в `abort` — только tuple, список grpc отвергает с `TypeError`.
- ExceptionHandling пропускает `grpc.aio.AbortError` как есть (хэндлер сам вызвал `context.abort`, антипример `LegacyResetPassword`), доменное исключение → статус + details, прочее → `INTERNAL: Internal error` и событие `grpc.unhandled_exception` со стеком в лог. `asyncio.CancelledError` не перехватывается.
- Logging: событие `grpc.call` с `method`, `grpc_type`, `request_id`, `status`, `duration_ms`, для стримов — `messages_received` / `messages_sent`; `info` для `OK`, `warning` для остальных статусов. Тела запросов не логируются. RequestId дополнительно привязывает `request_id` к structlog contextvars, так что его несут и логи хэндлеров.
- Таблица политик — глобальный реестр `AUTH_POLICIES` (полное имя метода → `service`/`user`/`seller`), сервис заполняет его через `register_auth_policies` рядом с регистрацией хэндлеров, как `GRPC_HANDLERS`. Метод без строки в таблице требует пользователя (`user`): забытая политика не открывает метод. `x-api-key` сравнивается через `hmac.compare_digest`.
- Сессии: `Sessions(Client)` поверх `Redis`, ключ `session:{token}`, значение — JSON `{"user_id", "role"}` с TTL. Пишет user-service, читает AuthInterceptor; битое значение = нет сессии (`UNAUTHENTICATED`). Неизвестная роль — тоже битая сессия.
- Для исходящих вызовов AuthInterceptor кладёт в contextvar исходный заголовок `authorization` пользователя, а RequestIdInterceptor — deadline входящего вызова (`time.monotonic() + context.time_remaining()`); без deadline `time_remaining()` в grpc.aio — `None`.
- `GrpcClient(Client)` — базовый клиент к соседям: подкласс задаёт `address_env` (`CATALOG_ADDR`, `ORDERS_ADDR`) и `dependency`. Адрес читается из env в `connect()` напрямую, а не через `Settings`: у каждого клиента своя переменная, и `Settings` не разрастается адресами всех соседей. Канал ленивый — сосед может подняться позже. Каждый вызов несёт `x-api-key`, `x-request-id` текущего вызова и, если `forward_authorization=True`, `authorization` пользователя; deadline — остаток входящего, иначе `GRPC_DEFAULT_DEADLINE_SECONDS`, или явный `deadline=` (имя не `timeout`: ruff ASYNC109). `UNAVAILABLE`/`DEADLINE_EXCEEDED` → `DependencyUnavailable(dependency)`, прочие статусы остаются `AioRpcError` — их разбирает сервис (например, `FAILED_PRECONDITION` с деталями от catalog в Checkout).
- Шаблон `main.py` в тестах (`tests/example_main.py`) резолвит интерцепторы без `AuthInterceptor`: тест идёт без Redis. В сервисах — `resolve_interceptors()` со всеми пятью.
- В тестах rich details читаются из `grpc-status-details-bin` хелпером `tests/rich_status.py`: `rpc_status.from_call` в `types-grpcio-status` типизирован под `grpc.Call`, а не `grpc.aio.AioRpcError`.
