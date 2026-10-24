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
- `resolve_interceptors()` без аргументов резолвит `DEFAULT_INTERCEPTORS` (пока пусто, интерцепторы появятся в следующей задаче); можно передать свой список. `inject_handlers` возвращает копию реестра, `GRPC_HANDLERS` не меняется.
- Healthcheck для compose — `python -m stand_core.grpc.healthcheck [--addr] [--service] [--timeout]`. Вызов `Check` идёт через `channel.unary_unary`, а не `HealthStub`: в `types-grpcio-health-checking` у стаба нет методов, а `type: ignore` вне gen/ не используем. В dev-группе добавлены `types-grpcio-health-checking` и `types-grpcio-reflection`.
- Процесс `@worker`, остановленный SIGTERM, завершается кодом 143 (128 + сигнал) — так nuke-di сообщает об остановке по сигналу, это не ошибка.
- Тесты stand_core изолируют глобальный `GRPC_HANDLERS` и сбрасывают structlog после каждого теста (conftest). Шаблон `main.py` проверяется end-to-end: `tests/example_main.py` запускается отдельным процессом, отвечает на вызов с внедрённым клиентом и останавливается по SIGTERM.
