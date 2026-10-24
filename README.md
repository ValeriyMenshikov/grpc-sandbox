# grpc-stand

Учебный стенд для курса «gRPC API Test Automation (Python)»: упрощённый бэкенд маркетплейса из четырёх gRPC-сервисов и REST-шлюза. Поднимается одной командой в docker compose вместе с Postgres и Redis. Все четыре типа вызовов gRPC, rich error model, авторизация по metadata, deadline, идемпотентность, стримы без брокеров.

- Требования и поведение — [docs/stand/grpc-stand-TZ.md](docs/stand/grpc-stand-TZ.md)
- Методы, статус-коды, metadata — [docs/api.md](docs/api.md)
- Решения, принятые при реализации — [docs/decisions.md](docs/decisions.md)

## Запуск

Нужны Docker с compose v2, [uv](https://docs.astral.sh/uv/) и make.

```bash
cp .env.example .env   # необязательно: без .env compose берёт те же значения по умолчанию
make up                # собрать образ и поднять стенд, дождаться healthy
make smoke             # (нужен make install) прогнать smoke-сценарий против стенда
```

Проверить, что сервисы видны через reflection:

```bash
grpcurl -plaintext localhost:50052 list
# catalog.v1.CatalogService
# catalog.v1.StockService
# catalog.v2.CatalogService
# grpc.health.v1.Health
# grpc.reflection.v1alpha.ServerReflection

grpcurl -plaintext -H 'x-api-key: stand-secret-key' \
  -d '{"category": "books", "pagination": {"page_size": 3}}' \
  localhost:50052 catalog.v1.CatalogService/SearchProducts
```

`make smoke` берёт адреса только из окружения процесса, `.env` он не читает: по умолчанию хост `localhost` (`STAND_HOST`) и порты из `.env.example`. Если порты в `.env` изменены, экспортируйте его перед запуском — `set -a; . ./.env; set +a; make smoke`. Redis для чтения кода подтверждения — `redis://$STAND_HOST:$REDIS_PORT/0`, переопределяется целиком через `SMOKE_REDIS_URL`.

Остановить и удалить данные — `make down`, пересоздать с чистыми данными — `make reset`.

## Компоненты и порты

| Компонент | Порт (хост) | Протокол | За что отвечает |
|---|---|---|---|
| gateway | 8080 | REST (FastAPI) → gRPC | BFF для веб-фронта |
| user-service | 50051 | gRPC | Регистрация, подтверждение email, вход, профиль |
| catalog-service | 50052 | gRPC | Каталог и поиск (v1 и v2); импорт/экспорт товаров продавца; остатки и резервы (`StockService`) |
| order-service | 50053 | gRPC | Корзина, оформление заказа, заказы, отслеживание доставки |
| support-service | 50054 | gRPC | Чат покупателя с поддержкой по заказу |
| postgres | 5432 | SQL | Одна БД `stand` (`stand`/`stand`), схема на сервис: `users`, `catalog`, `orders`, `support` |
| redis | 6379 | RESP | Коды подтверждения (user-service); сессии `session:{token}` читают все gRPC-сервисы (AuthInterceptor); корзины, ключи идемпотентности, pub/sub статусов заказов (order-service) |

Порты, ключи и задержки задаются в `.env` (см. `.env.example`). Ключ сервиса-клиента `x-api-key` — `stand-secret-key`; продавец-сид — `seller@stand.local` / `seller-password`.

## Архитектура

```
Браузер ──HTTP/JSON──> gateway (BFF) ──gRPC──> user-service ───────────────> Postgres, Redis
                                     ├─gRPC──> catalog-service ─────────────> Postgres, Redis
                                     └─gRPC──> order-service ──gRPC──> catalog-service (StockService)
                                                    └──> Postgres, Redis
               приложение поддержки ──gRPC──> support-service ──gRPC──> order-service
                                                    └──> Postgres, Redis
Автотесты курса ──gRPC──> любой сервис;  ──SQL/Redis──> проверки состояния
```

| Тип | Метод | Зачем |
|---|---|---|
| unary | почти все методы | обычные запрос-ответ |
| client stream | `catalog.v1.CatalogService/ImportProducts` | продавец загружает фид, в ответ — отчёт об импорте |
| server stream | `catalog.v1.CatalogService/ExportProducts` | продавец выгружает каталог без пагинации |
| server stream | `orders.v1.OrderService/TrackOrder` | статус доставки в реальном времени (Redis pub/sub) |
| bidi | `support.v1.SupportService/Chat` | чат: клиент и поддержка пишут независимо |

## Структура

```
protos/            контракты: common/v1, users/v1, catalog/v1, catalog/v2, orders/v1, support/v1
gen/               сгенерированный код (make gen), в git
packages/stand_core/  общая библиотека: Settings, логи, ошибки, декоратор rpc, grpc_server,
                   интерцепторы, клиенты Postgres/Redis и базовый gRPC-клиент к соседям
services/<name>/   сервисы: users, catalog, orders, support, gateway
tests/             тесты контрактов и smoke-сценарий (маркер stand)
docker/Dockerfile  один образ для всех Python-сервисов
```

## Команды

| Цель | Что делает |
|---|---|
| `make install` | `uv sync` всех пакетов workspace |
| `make gen` | `protos/**` → `gen/` (protoc + mypy-protobuf) |
| `make format` / `make lint` | ruff format + fix / проверка |
| `make typecheck` | mypy strict |
| `make check` | lint + typecheck |
| `make test` | тесты stand_core и сервисов, без smoke |
| `make cov` | тесты с покрытием (порог 80%) |
| `make smoke` | smoke-сценарий против поднятого стенда |
| `make up` / `make down` | поднять (с пересборкой образа, `--wait`) / остановить и удалить данные |
| `make reset` | `down` + `up` |
| `make logs` / `make ps` / `make stats` | логи, статус, память контейнеров |

Другая версия Python: `UV_PROJECT_ENVIRONMENT=/tmp/stand-venv-314 PYTHON=3.14.2 make install check test` — отдельный venv, `.venv` на 3.12 не трогается; нужен обычный CPython, а не free-threaded `3.14t` (под него нет колёс grpcio-tools). Образ — `PYTHON_VERSION=3.14 make up` (поддерживаются 3.12 и 3.14).

## Память (`make stats`)

Замер сразу после `make up` и smoke, Python 3.12:

| Контейнер | Факт | `mem_limit` |
|---|---|---|
| users | ~56 МБ | 128m |
| gateway | ~50 МБ | 128m |
| catalog | ~40 МБ | 128m |
| orders | ~40 МБ | 128m |
| support | ~40 МБ | 128m |
| postgres | ~75 МБ | 256m |
| redis | ~19 МБ | 64m |
| **Итого** | **~320 МБ** | **960 МБ** |

## Как добавить новый сервис

Новый сервис = контракт `protos/<name>/v1` + папка `services/<name>` + блок в `docker-compose.yml`. Образ, настройки, клиенты, декоратор `rpc` и сборка сервера берутся из `stand_core`. Пример — `services/catalog`.

1. **Контракт.** `protos/<name>/v1/<name>.proto` с `package <name>.v1;`, стиль buf STANDARD (`<Method>Request`/`<Method>Response`, enum с префиксом и `*_UNSPECIFIED = 0`). У каждого метода в комментарии — `Auth: service|user|seller`. `make gen`. Добавьте сервис в `tests/contracts/test_protos.py`.
2. **Пакет.** `services/<name>/pyproject.toml` (как у catalog: зависимости `stand-core`, `stand-protos` из workspace, `packages = ["src/<name>_service"]`), добавьте `services/<name>/src` в `mypy_path` корневого `pyproject.toml` и пакет в `COV_PACKAGES` Makefile. `make install`.
3. **Настройки.** `settings.py`: `class <Name>Settings(Settings)` с полями сервиса и `def __init__(self) -> None` (см. docs/decisions.md §7).
4. **Хэндлеры.** `handlers/<method>_<in>_<out>.py`, по одному на файл, `u` — unary, `s` — stream (`get_order_u_u.py`, `track_order_u_s.py`, `chat_s_s.py`). Хэндлер — свободная async-функция, первые два аргумента `request` и `context`, дальше зависимости-клиенты по type hint:

   ```python
   @rpc("GetThing", package="<name>.v1", service="<Name>Service")
   async def get_thing(
       request: thing_pb2.GetThingRequest,
       context: Context,
       repository: ThingRepository,
   ) -> thing_pb2.GetThingResponse: ...
   ```

   Ошибки — доменные исключения из `stand_core.grpc` (`InvalidArgument`, `NotFound`, `FailedPrecondition`, ...): статус и details выставит интерцептор. `handlers/__init__.py` импортирует все модули хэндлеров.
5. **Авторизация.** `auth.py` с `AUTH_POLICIES: dict[str, AuthPolicy]` на каждый метод (`"/<name>.v1.<Name>Service/GetThing": AuthPolicy.USER`). Метод без строки требует пользователя.
6. **Клиенты.** Postgres/Redis — `stand_core.clients`; репозиторий — `Client` с `schema.sql` (схема `<name>`), применяется в `connect()`. Сосед — подкласс `GrpcClient` с `address_env = "<NEIGHBOUR>_ADDR"`.
7. **`main.py`** — копия `services/catalog/src/catalog_service/main.py` с заменой имён.
8. **compose.** Блок с `<<: *python-service`, `command: ["python", "-m", "<name>_service.main"]`, `environment` (`<<: *common-env`, `GRPC_PORT`), `ports`, `depends_on` с `condition: service_healthy`, `healthcheck: *grpc-healthcheck`. Новые переменные — в `.env.example`. Не забудьте про бюджет памяти (`make stats`).
9. **Тесты.** `services/<name>/tests/`: хэндлеры напрямую с фейками, `test_server.py` in-process со всеми интерцепторами, `test_wiring.py`. `make check && make test`.
