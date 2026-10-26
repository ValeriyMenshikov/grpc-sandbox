# order.status_changed: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Смены статуса заказа становятся доменным событием `order.status_changed` в RabbitMQ с двумя независимыми потребителями, а страница заказа показывает таймлайн с метками времени вместо одного текущего статуса.

**Architecture:** order-service пишет историю статусов в Postgres в одной транзакции со сменой статуса и публикует событие в topic exchange `stand.events` best-effort. Две очереди на плоский routing key `order.status_changed`: notification-service шлёт письмо на `DELIVERED` (брокер обязателен, как и для писем с кодом), support-service строит идемпотентную проекцию `support.order_events` фоновым консьюмером с переподключением (брокер не обязателен — `Chat` обязан выживать). `GetOrder` отдаёт историю и авторитетный порядок шагов доставки, фронт рисует и то и другое из ответа.

**Tech Stack:** Python 3.12, grpc.aio, aio-pika, asyncpg, nuke-di, pydantic-settings, Vue 3 + TypeScript + Vite, RabbitMQ, Postgres, Mailpit.

**Spec:** `docs/plans/20261026-order-status-events-design.md`

## Global Constraints

- Python ≥ 3.12, mypy strict, ruff (строка 100). `type: ignore` вне `pb/` запрещён.
- `pb/` генерируется `make gen` после правки `protos/`; руками не правится, но коммитится.
- Комментарии, докстринги и docs — на русском; сообщения ошибок gRPC — на английском.
- Один хэндлер на файл `handlers/<method_snake>_<in>_<out>.py`, модуль — в импорт и `__all__` `handlers/__init__.py`, метод — в `auth.py`.
- Ошибки — только доменные исключения `stand_core.grpc`; `context.abort` не вызывать.
- Зависимости — только через nuke-di: `@client_dataclass` + `Client`, зависимости — приватные поля по типу, своё состояние — `field(default=..., init=False)`, заполняется в `connect()`. `__init__` не писать (кроме подклассов `Settings`).
- Новая переменная окружения — в `.env.example`, `docker-compose.yml` (с дефолтом `${VAR:-...}`) и `Settings` сервиса. Порт внутри контейнера — литералом в compose.
- Перед коммитом: `make check && make test` зелёные. Коммиты, трогающие `frontend/`: ещё `make front-lint && make front-test`.
- Сообщения коммитов: `feat: ...` / `fix: ...` / `docs: ...`.
- Тесты против Postgres/Redis/RabbitMQ/Mailpit пропускаются, если контейнеров нет.

## Review Focus

- **Заказ без строк истории** (оформлен до этого изменения): `GetOrder` отдаёт пустую `history`, страница заказа рендерится и прогресс-бар работает по `delivery_steps`. — Task 7, Task 8.
- **Повторная доставка одного события** (at-least-once): проекция `support.order_events` не плодит дубликаты. — Task 6.
- **Событие с неизвестным статусом** (издатель новее потребителя): `InvalidEvent`, `nack(requeue=False)` в dead-letter, запись/лог остаётся — сообщение не крутится в очереди. — Task 5, Task 6.
- **Пустой `email` в событии** на `DELIVERED`: notification-service `ack` + строка `SKIPPED` в журнале, не dead-letter и не молча. — Task 5.
- **RabbitMQ недоступен при старте support-service**: сервис стартует, `Chat` и `GetChatHistory` работают, консьюмер переподключается в фоне. — Task 6.

---

## Структура файлов

**Создаются:**
- `services/orders/src/order_service/users_client.py` — `UsersClient`: `GetMe` за email покупателя.
- `services/orders/src/order_service/domain_events.py` — `DomainEvents`: публикация `order.status_changed` в RabbitMQ.
- `services/notifications/src/notification_service/order_status_consumer.py` — `OrderStatusConsumer`: вторая очередь, письмо о доставке.
- `services/support/src/support_service/order_status_consumer.py` — `OrderStatusConsumer`: проекция с переподключением.
- `services/support/src/support_service/handlers/get_order_timeline_u_u.py` — `get_order_timeline`.

**Изменяются:** `packages/core/src/stand_core/events.py`; в orders — `models.py`, `schema.sql`, `repository.py`, `fulfillment.py`, `convert.py`, `settings.py`, `handlers/checkout_u_u.py`, `handlers/cancel_order_u_u.py`, `handlers/get_order_u_u.py`, `main.py`; в notifications — `models.py`, `schema.sql`, `templates.py`, `settings.py`, `convert.py`, `main.py`; в support — `models.py`, `schema.sql`, `repository.py`, `settings.py`, `convert.py`, `auth.py`, `handlers/__init__.py`, `main.py`; `protos/orders/v1/orders.proto`, `protos/notifications/v1/notifications.proto`, `protos/support/v1/support.proto`; gateway — `schemas.py`, `routers/orders.py`; фронт — `api/types.ts`, `orders.ts`, `components/OrderProgress.vue`, `pages/OrderPage.vue`; `docker-compose.yml`, `.env.example`; документация.

---

### Task 1: Событие `order.status_changed` в `stand_core.events`

**Files:**
- Modify: `packages/core/src/stand_core/events.py`
- Test: `packages/core/tests/test_events.py`

**Interfaces:**
- Consumes: существующие приватные помощники `_load`, `_require_str`, `_optional_str`.
- Produces:
  - `ORDER_STATUS_CHANGED = "order.status_changed"`
  - `@dataclass(frozen=True) class OrderStatusChanged: order_id: str; user_id: str; status: str; changed_at: datetime; email: str = ""; request_id: str | None = None`
  - `order_status_changed_payload(event: OrderStatusChanged) -> dict[str, Any]` — `changed_at` сериализуется `.isoformat()`
  - `parse_order_status_changed(body: bytes | str | Mapping[str, Any]) -> OrderStatusChanged`

`status` здесь строка, а не enum: `stand_core` не знает доменных типов сервисов, проверка значения — на стороне потребителя (Task 5, Task 6). `email` опционален и по умолчанию пустой (дизайн §5).

- [x] **Step 1: Написать падающие тесты**

```python
def test_order_status_changed_roundtrip() -> None:
    changed_at = datetime(2026, 10, 26, 12, 0, 1, tzinfo=UTC)
    event = OrderStatusChanged(
        order_id="o-1",
        user_id="u-1",
        status="DELIVERED",
        changed_at=changed_at,
        email="buyer@example.com",
        request_id="r-1",
    )
    payload = order_status_changed_payload(event)
    assert payload["changed_at"] == changed_at.isoformat()
    assert parse_order_status_changed(json.dumps(payload).encode()) == event


def test_order_status_changed_email_is_optional() -> None:
    payload = {
        "order_id": "o-1",
        "user_id": "u-1",
        "status": "DELIVERED",
        "changed_at": "2026-10-26T12:00:01+00:00",
    }
    assert parse_order_status_changed(payload).email == ""


@pytest.mark.parametrize(
    "payload",
    [
        {"user_id": "u-1", "status": "PAID", "changed_at": "2026-10-26T12:00:01+00:00"},
        {"order_id": "o-1", "status": "PAID", "changed_at": "2026-10-26T12:00:01+00:00"},
        {"order_id": "o-1", "user_id": "u-1", "changed_at": "2026-10-26T12:00:01+00:00"},
        {"order_id": "o-1", "user_id": "u-1", "status": "PAID", "changed_at": "не дата"},
        {"order_id": "o-1", "user_id": "u-1", "status": "PAID"},
    ],
)
def test_order_status_changed_invalid(payload: dict[str, object]) -> None:
    with pytest.raises(InvalidEvent):
        parse_order_status_changed(payload)
```

- [x] **Step 2: Запустить тесты, убедиться, что падают**

Run: `uv run pytest packages/core/tests/test_events.py -v`
Expected: FAIL — `ImportError` / `NameError` на `OrderStatusChanged`.

- [x] **Step 3: Реализовать событие в `packages/core/src/stand_core/events.py`**

Добавить константу, dataclass, `order_status_changed_payload`, `parse_order_status_changed` и приватный `_require_datetime(data, name) -> datetime` (разбор `datetime.fromisoformat`, `ValueError`/`TypeError` → `InvalidEvent` с тем же стилем сообщения, что у соседних помощников).

- [x] **Step 4: Запустить тесты и проверки**

Run: `uv run pytest packages/core/tests/test_events.py -v && make check`
Expected: PASS.

- [x] **Step 5: Коммит**

```bash
git add packages/core/src/stand_core/events.py packages/core/tests/test_events.py
git commit -m "feat: событие order.status_changed в stand_core.events"
```

---

### Task 2: История статусов в order-service

**Files:**
- Modify: `services/orders/src/order_service/schema.sql`, `models.py`, `repository.py`, `handlers/cancel_order_u_u.py`
- Test: `services/orders/tests/test_repository.py`

**Interfaces:**
- Produces:
  - `models.OrderStatusEvent` — `@dataclass(frozen=True)` с полями `order_id: str`, `user_id: str`, `email: str`, `status: OrderStatus`, `changed_at: datetime`; метод `change(self) -> StatusChange` для Redis-публикации.
  - `models.DELIVERY_STEPS: tuple[OrderStatus, ...]` — `(CREATED, PAID, ASSEMBLING, HANDED_TO_COURIER, DELIVERED)`, выведено из `NEXT_STATUS` (не второй литерал).
  - `OrderRepository.advance_due(step: timedelta) -> list[OrderStatusEvent]` (было `list[StatusChange]`).
  - `OrderRepository.status_history(order_id: str) -> list[StatusChange]` — в порядке возрастания `changed_at`.
  - `OrderRepository.cancel` и `create_order` пишут строку истории в той же операции.

Таблица `orders.order_status_history` (`order_id` с `REFERENCES orders.orders ON DELETE CASCADE`, `status`, `changed_at timestamptz NOT NULL DEFAULT now()`) и индекс по `(order_id, changed_at)`. `advance_due` переписывается в один statement: `WITH advanced AS (UPDATE ... RETURNING order_id, user_id, email, status, updated_at) INSERT INTO orders.order_status_history (order_id, status, changed_at) SELECT ... FROM advanced RETURNING ...` — атомарность без явной транзакции и без второго round-trip. Поле `email` появляется в Task 3; в этой задаче `advance_due` возвращает `email=""`, и `OrderStatusEvent.email` заполняется в Task 3.

- [x] **Step 1: Написать падающие тесты** (пропускаются без Postgres, как соседние в файле)

```python
async def test_status_history_records_each_change(repository: OrderRepository) -> None:
    order = await repository.create_order(order_id(), "u-1", [item()])
    assert [change.status for change in await repository.status_history(order.order_id)] == [
        OrderStatus.CREATED
    ]
    await repository.advance_due(timedelta(0))
    assert [change.status for change in await repository.status_history(order.order_id)] == [
        OrderStatus.CREATED,
        OrderStatus.PAID,
    ]


async def test_cancel_records_history(repository: OrderRepository) -> None:
    order = await repository.create_order(order_id(), "u-1", [item()])
    await repository.cancel(order.order_id)
    assert [change.status for change in await repository.status_history(order.order_id)][-1] == (
        OrderStatus.CANCELLED
    )


async def test_advance_due_returns_user_id(repository: OrderRepository) -> None:
    order = await repository.create_order(order_id(), "u-1", [item()])
    events = await repository.advance_due(timedelta(0))
    assert [(event.order_id, event.user_id) for event in events] == [(order.order_id, "u-1")]


async def test_delivery_steps_match_next_status() -> None:
    assert DELIVERY_STEPS[-1] == OrderStatus.DELIVERED
    assert all(
        NEXT_STATUS[step] == DELIVERY_STEPS[i + 1] for i, step in enumerate(DELIVERY_STEPS[:-1])
    )
```

- [x] **Step 2: Запустить тесты, убедиться, что падают**

Run: `uv run pytest services/orders/tests/test_repository.py -v`
Expected: FAIL — нет `status_history` / `DELIVERY_STEPS`.

- [x] **Step 3: Реализовать**

Таблицу в `schema.sql`, `OrderStatusEvent` и `DELIVERY_STEPS` в `models.py`, `status_history` и правку `_ADVANCE`/`create_order`/`_CANCEL` в `repository.py`. `cancel_order_u_u.py` правится только под новый тип, если `cancel` стал возвращать больше, — публикация в Redis остаётся как есть.

- [x] **Step 4: Запустить тесты и проверки**

Run: `uv run pytest services/orders -v && make check`
Expected: PASS (тесты `test_fulfillment.py` могут требовать правки под новый тип `advance_due` — поправить их здесь же).

- [x] **Step 5: Коммит**

```bash
git add services/orders
git commit -m "feat: история статусов заказа в Postgres"
```

---

### Task 3: Снимок email покупателя в заказе

**Files:**
- Create: `services/orders/src/order_service/users_client.py`
- Modify: `services/orders/src/order_service/schema.sql`, `models.py`, `repository.py`, `settings.py`, `handlers/checkout_u_u.py`, `main.py`, `docker-compose.yml`, `.env.example`
- Test: `services/orders/tests/test_checkout.py`, `services/orders/tests/test_wiring.py`, `services/orders/tests/fakes.py`

**Interfaces:**
- Produces:
  - `UsersClient(GrpcClient)` с `address_env = "USERS_ADDR"`, `dependency = "users"`, метод `async def email(self) -> str` — `GetMe` с пробросом `authorization` (`forward_authorization=True`, как в `support_service.orders_client`); любая ошибка соседа и пустой ответ дают `""`, а не исключение.
  - `OrderSettings.users_email_timeout_s: float = 2.0` (по образцу `confirm_publish_timeout_s` в users-service).
  - `OrderRepository.create_order(order_id: str, user_id: str, items: Sequence[OrderItem], email: str = "") -> Order`.
  - `models.Order` получает поле `email: str`.

`orders.orders` получает `email text NOT NULL DEFAULT ''`. `Checkout` зовёт `users.email()` **до** `place_order` (то есть до `ReserveStock`), под `asyncio.timeout(settings.users_email_timeout_s)`; таймаут и любая ошибка — пустой email и предупреждение в лог. Контракт ошибок `Checkout` не меняется.

- [x] **Step 1: Написать падающие тесты**

```python
async def test_checkout_snapshots_email(...) -> None:
    response = await checkout(..., users=FakeUsers(email="buyer@example.com"), ...)
    order = await repository.get_order(response.order.order_id)
    assert order is not None and order.email == "buyer@example.com"


async def test_checkout_succeeds_when_users_unavailable(...) -> None:
    response = await checkout(..., users=FakeUsers(error=DependencyUnavailable("users")), ...)
    order = await repository.get_order(response.order.order_id)
    assert order is not None and order.email == ""


async def test_checkout_does_not_reserve_before_users_call(...) -> None:
    """users спрашиваем до резерва: его отказ не должен попадать в компенсацию."""
    stock = FakeStock()
    await checkout(..., users=FakeUsers(error=DependencyUnavailable("users")), stock=stock, ...)
    assert stock.released == []
```

- [x] **Step 2: Запустить тесты, убедиться, что падают**

Run: `uv run pytest services/orders/tests/test_checkout.py -v`
Expected: FAIL — у `checkout` нет параметра `users`.

- [x] **Step 3: Реализовать `UsersClient`, колонку, снимок в `Checkout`**

`FakeUsers` — в `services/orders/tests/fakes.py` рядом с существующими фейками. В `docker-compose.yml` у `orders`: `USERS_ADDR: users:50051` и `users` в `depends_on` (`condition: service_healthy`), с комментарием, что зависимость нужна только для снимка email и `Checkout` без неё не падает.

- [x] **Step 4: Запустить тесты и проверки**

Run: `uv run pytest services/orders -v && make check`
Expected: PASS.

- [x] **Step 5: Коммит**

```bash
git add services/orders docker-compose.yml .env.example
git commit -m "feat: снимок email покупателя в заказе"
```

---

### Task 4: Публикация `order.status_changed` из order-service

**Files:**
- Create: `services/orders/src/order_service/domain_events.py`
- Modify: `services/orders/src/order_service/fulfillment.py`, `handlers/checkout_u_u.py`, `handlers/cancel_order_u_u.py`, `main.py`
- Test: `services/orders/tests/test_events.py`, `services/orders/tests/test_fulfillment.py`, `services/orders/tests/test_wiring.py`

**Interfaces:**
- Consumes: `stand_core.events.ORDER_STATUS_CHANGED`, `OrderStatusChanged`, `order_status_changed_payload` (Task 1); `models.OrderStatusEvent` (Task 2).
- Produces:
  - `DomainEvents(Client)` с `_rabbit: Rabbit`; `async def publish_quietly(self, event: OrderStatusEvent) -> None` — публикует в `stand.events` с routing key `order.status_changed`; любая ошибка брокера логируется (`orders.domain_publish_failed`) и не бросается.

Публикуют все три источника смены: `Fulfillment.advance` (по событию из `advance_due`), `Checkout` (`CREATED`, после `finalize`), `CancelOrder` (`CANCELLED`). Redis-публикация остаётся нетронутой рядом.

Плоский routing key (дизайн §1): пока ни один потребитель не объявил очередь, `publish` падает из-за `on_return_raises=True` — это и есть причина, по которой публикация best-effort.

- [x] **Step 1: Написать падающие тесты**

```python
async def test_publishes_order_status_changed(fake_rabbit: FakeRabbit) -> None:
    events = DomainEvents(_rabbit=fake_rabbit)
    await events.publish_quietly(order_status_event(status=OrderStatus.DELIVERED))
    (routing_key, payload), = fake_rabbit.published
    assert routing_key == ORDER_STATUS_CHANGED
    assert parse_order_status_changed(payload).status == "DELIVERED"


async def test_publish_survives_broker_failure(fake_rabbit: FakeRabbit) -> None:
    fake_rabbit.error = RuntimeError("no broker")
    await DomainEvents(_rabbit=fake_rabbit).publish_quietly(order_status_event())


async def test_fulfillment_publishes_each_change(...) -> None:
    await fulfillment.advance()
    assert [parse_order_status_changed(p).status for _, p in fake_rabbit.published] == ["PAID"]
```

- [x] **Step 2: Запустить тесты, убедиться, что падают**

Run: `uv run pytest services/orders/tests/test_events.py -v`
Expected: FAIL — нет `DomainEvents`.

- [x] **Step 3: Реализовать `DomainEvents` и подключить к трём источникам**

`Fulfillment` получает поле `_domain: DomainEvents`; `Checkout` и `CancelOrder` — параметр `domain: DomainEvents` после остальных клиентов. `request_id` в событие не передаём руками: `Rabbit.publish` сам ставит `correlation_id` из contextvars.

- [x] **Step 4: Запустить тесты и проверки**

Run: `uv run pytest services/orders -v && make check`
Expected: PASS.

- [x] **Step 5: Коммит**

```bash
git add services/orders
git commit -m "feat: order-service публикует order.status_changed в RabbitMQ"
```

---

### Task 5: notification-service — письмо о доставке и статус `SKIPPED`

**Files:**
- Create: `services/notifications/src/notification_service/order_status_consumer.py`
- Modify: `protos/notifications/v1/notifications.proto`, `services/notifications/src/notification_service/{models,schema.sql,templates,settings,convert,main}.py`
- Test: `services/notifications/tests/test_consumer.py`, `test_convert.py`, `test_repository.py`, `test_wiring.py`

**Interfaces:**
- Consumes: `parse_order_status_changed`, `ORDER_STATUS_CHANGED` (Task 1).
- Produces:
  - `NotificationStatus.SKIPPED` (+ `NOTIFICATION_STATUS_SKIPPED = 3` в proto, `'SKIPPED'` в `CHECK` схемы, запись в `STATUS_TO_PROTO`).
  - `templates.delivered_email(event: OrderStatusChanged) -> EmailContent` — тема «Заказ доставлен», в теле номер заказа; без кода и без HTML.
  - `NotificationSettings.order_status_queue: str = "notifications.order_status"`.
  - `OrderStatusConsumer(Client)` — отдельный клиент рядом с `EmailConsumer`, та же механика (`prefetch`, dead-letter через `x-dead-letter-exchange`, `ack` только после SMTP), своя очередь на `order.status_changed`.

Поведение на одно сообщение: статус не `DELIVERED` → `ack` без письма и без записи; `DELIVERED` с пустым `email` → `ack` + строка `SKIPPED` в журнале; `DELIVERED` с адресом → письмо, `SENT`/`FAILED` как у `EmailConsumer`; неразбираемое тело или неизвестный статус → `InvalidEvent`, строка `FAILED`, `nack(requeue=False)`.

- [ ] **Step 1: Написать падающие тесты**

```python
async def test_sends_email_on_delivered(...) -> None:
    await consumer.handle(message(status="DELIVERED", email="buyer@example.com"))
    assert mailer.sent == [("buyer@example.com", "Заказ доставлен")]
    assert repository.records[-1].status is NotificationStatus.SENT


async def test_skips_other_statuses(...) -> None:
    await consumer.handle(message(status="PAID", email="buyer@example.com"))
    assert mailer.sent == [] and repository.records == []
    assert acked


async def test_empty_email_is_skipped_not_dead_lettered(...) -> None:
    msg = message(status="DELIVERED", email="")
    await consumer.handle(msg)
    assert mailer.sent == []
    assert repository.records[-1].status is NotificationStatus.SKIPPED
    assert msg.acked and not msg.nacked


async def test_unknown_status_goes_to_dead_letter(...) -> None:
    msg = message(status="TELEPORTED", email="buyer@example.com")
    await consumer.handle(msg)
    assert msg.nacked and repository.records[-1].status is NotificationStatus.FAILED
```

- [ ] **Step 2: Запустить тесты, убедиться, что падают**

Run: `uv run pytest services/notifications -v`
Expected: FAIL — нет `OrderStatusConsumer`.

- [ ] **Step 3: `make gen` и реализация**

Run: `make gen` (после правки proto), затем реализовать консьюмера, шаблон, статус и настройку. `main.py`: второй `tasks.spawn(order_status_consumer.run(), name="order-status-consumer")` рядом с существующим; `tasks.watch` остаётся один.

- [ ] **Step 4: Запустить тесты и проверки**

Run: `uv run pytest services/notifications -v && make check`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add protos pb services/notifications docker-compose.yml .env.example
git commit -m "feat: письмо о доставке заказа и статус SKIPPED в журнале"
```

---

### Task 6: support-service — проекция событий и `GetOrderTimeline`

**Files:**
- Create: `services/support/src/support_service/order_status_consumer.py`, `services/support/src/support_service/handlers/get_order_timeline_u_u.py`
- Modify: `protos/support/v1/support.proto`, `services/support/src/support_service/{models,schema.sql,repository,settings,convert,auth,main}.py`, `handlers/__init__.py`, `docker-compose.yml`, `.env.example`
- Test: `services/support/tests/test_repository.py`, новый `services/support/tests/test_order_status_consumer.py`, `test_server.py`, `test_wiring.py`

**Interfaces:**
- Consumes: `parse_order_status_changed`, `ORDER_STATUS_CHANGED` (Task 1).
- Produces:
  - `models.OrderEvent` — `@dataclass(frozen=True)` с `order_id: str`, `status: str`, `changed_at: datetime`.
  - `SupportRepository.record_order_event(event: OrderEvent) -> None` — идемпотентная вставка (`ON CONFLICT DO NOTHING` по `(order_id, status)`).
  - `SupportRepository.order_events(order_id: str) -> list[OrderEvent]` — по возрастанию `changed_at`.
  - `SupportSettings.order_events_queue: str = "support.order_events"`, `order_events_reconnect_delay_s: float = 1.0`, `order_events_reconnect_max_delay_s: float = 30.0`.
  - `OrderStatusConsumer(Client)` — брокер **не** открывается в `connect()`; `run()` — внешний цикл: подключиться, объявить и привязать очередь, потреблять; любая ошибка — лог, пауза с экспоненциальным backoff до максимума, снова.
  - `support.v1.SupportService.GetOrderTimeline` (auth `SERVICE`) с `GetOrderTimelineRequest { string order_id = 1; }` и `GetOrderTimelineResponse { repeated OrderEvent events = 1; }`.

Таблица `support.order_events` (`order_id text NOT NULL`, `status text NOT NULL`, `changed_at timestamptz NOT NULL`, `PRIMARY KEY (order_id, status)`) — естественный ключ идемпотентности: один заказ проходит каждый статус один раз. `main.py`: `tasks.spawn(...)` **без** `tasks.watch(... shutdown.set())` — падение консьюмера не валит сервис, `Chat` обязан работать без брокера. В `docker-compose.yml` rabbitmq у support — только порядок старта, как mailpit у notifications, с комментарием об этом.

Неизвестный статус в событии: `nack(requeue=False)` + лог; проекция хранит статус строкой, но значение проверяется по `support.v1.OrderStatus`, чтобы мусор не оседал в таблице.

- [ ] **Step 1: Написать падающие тесты**

```python
async def test_projection_is_idempotent(repository: SupportRepository) -> None:
    event = OrderEvent(order_id="o-1", status="PAID", changed_at=moment())
    await repository.record_order_event(event)
    await repository.record_order_event(event)
    assert await repository.order_events("o-1") == [event]


async def test_consumer_records_projection(...) -> None:
    await consumer.handle(message(order_id="o-1", status="PAID"))
    assert [event.status for event in repository.events["o-1"]] == ["PAID"]
    assert acked


async def test_consumer_reconnects_after_broker_failure(...) -> None:
    """Первая попытка падает, вторая работает: run() не умирает насовсем."""
    ...


async def test_chat_works_without_broker(...) -> None:
    """support стартует и обслуживает Chat, когда Rabbit.open() бросает."""
    ...
```

- [ ] **Step 2: Запустить тесты, убедиться, что падают**

Run: `uv run pytest services/support -v`
Expected: FAIL — нет `record_order_event` / `OrderStatusConsumer`.

- [ ] **Step 3: `make gen` и реализация**

Run: `make gen`, затем схема, модель, репозиторий, консьюмер с backoff, хэндлер, `AUTH_POLICIES` (`GetOrderTimeline` → `AuthPolicy.SERVICE`), `handlers/__init__.py`, `main.py`, compose.

- [ ] **Step 4: Запустить тесты и проверки**

Run: `uv run pytest services/support -v && make check`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add protos pb services/support docker-compose.yml .env.example
git commit -m "feat: support-service строит проекцию статусов заказа из событий"
```

---

### Task 7: `GetOrder` отдаёт историю и цепочку шагов

**Files:**
- Modify: `protos/orders/v1/orders.proto`, `services/orders/src/order_service/{convert,handlers/get_order_u_u}.py`, `services/gateway/src/gateway/{schemas,routers/orders}.py`
- Test: `services/orders/tests/test_orders.py`, `services/gateway/tests/test_api.py`, `tests/contracts/test_protos.py`

**Interfaces:**
- Consumes: `OrderRepository.status_history`, `models.DELIVERY_STEPS` (Task 2).
- Produces:
  - proto: `message OrderStatusChange { OrderStatus status = 1; google.protobuf.Timestamp changed_at = 2; }`; `GetOrderResponse` получает `repeated OrderStatusChange history = 2;` и `repeated OrderStatus delivery_steps = 3;`.
  - `convert.status_change_pb(change: StatusChange) -> orders_pb2.OrderStatusChange`.
  - gateway: `schemas.OrderStatusChange { status: str; changed_at: datetime }`, `schemas.OrderDetail(Order)` с `history: list[OrderStatusChange]` и `delivery_steps: list[str]`; `schemas.order_detail(response: orders_pb2.GetOrderResponse) -> OrderDetail`; `GET /orders/{order_id}` возвращает `OrderDetail`.

`delivery_steps` отдаётся из `models.DELIVERY_STEPS` — единственный источник порядка. `Order` в `ListOrders` не меняется.

- [ ] **Step 1: Написать падающие тесты**

```python
async def test_get_order_returns_history_and_steps(...) -> None:
    response = await get_order(request, context, repository)
    assert [change.status for change in response.history] == [ORDER_STATUS_CREATED]
    assert list(response.delivery_steps) == [
        ORDER_STATUS_CREATED, ORDER_STATUS_PAID, ORDER_STATUS_ASSEMBLING,
        ORDER_STATUS_HANDED_TO_COURIER, ORDER_STATUS_DELIVERED,
    ]


async def test_get_order_without_history(...) -> None:
    """Заказ, оформленный до этого изменения: history пустая, delivery_steps на месте."""
    response = await get_order(request, context, repository_without_history)
    assert list(response.history) == []
    assert len(response.delivery_steps) == 5


async def test_gateway_order_detail_shape(client) -> None:
    body = (await client.get(f"/orders/{order_id}")).json()
    assert body["delivery_steps"] == ["CREATED", "PAID", "ASSEMBLING", "HANDED_TO_COURIER", "DELIVERED"]
    assert body["history"][0]["status"] == "CREATED"
```

- [ ] **Step 2: Запустить тесты, убедиться, что падают**

Run: `uv run pytest services/orders/tests/test_orders.py services/gateway -v`
Expected: FAIL — нет поля `history`.

- [ ] **Step 3: `make gen` и реализация**

Run: `make gen`, затем `convert.py`, хэндлер, gateway-схемы и роутер. `tests/contracts/test_protos.py` дополнить новым сообщением, если он перечисляет поля.

- [ ] **Step 4: Запустить тесты и проверки**

Run: `make test && make check`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add protos pb services/orders services/gateway tests
git commit -m "feat: GetOrder отдаёт историю статусов и порядок шагов доставки"
```

---

### Task 8: Фронт — таймлайн заказа и шаги с бэка

**Files:**
- Modify: `frontend/src/api/types.ts`, `frontend/src/api/endpoints.ts`, `frontend/src/orders.ts`, `frontend/src/components/OrderProgress.vue`, `frontend/src/pages/OrderPage.vue`
- Test: `frontend/src/pages/order-pages.test.ts`, `frontend/src/api/testing.ts`

**Interfaces:**
- Consumes: `OrderDetail` из gateway (Task 7).
- Produces:
  - `types.ts`: `OrderStatusChange { status: OrderStatus; changed_at: string }`, `OrderDetail extends Order { history: OrderStatusChange[]; delivery_steps: OrderStatus[] }`.
  - `endpoints.getOrder(orderId: string): Promise<OrderDetail>`.
  - `OrderProgress` принимает `{ status: OrderStatus; steps: OrderStatus[]; history: OrderStatusChange[] }`.
  - `orders.ts`: `DELIVERY_STEPS` **удаляется**; `ORDER_STATUS_LABELS` и `isFinalStatus` остаются.

`OrderProgress` рисует шаги по `steps` из ответа, подписи берёт из `ORDER_STATUS_LABELS`, а для пройденных шагов показывает время из `history` (`formatDate`). Пустая `history` — шаги без времени, страница рендерится. После `DELIVERED` — заметка «Мы отправили письмо о доставке» со ссылкой на `/mail/`, по образцу `.mail-note` в `ConfirmPage.vue`.

- [ ] **Step 1: Написать падающие тесты**

```ts
it('рисует шаги из ответа бэка, а не из локальной константы', async () => {
  // delivery_steps из фикстуры короче полной цепочки — на экране ровно столько шагов
})

it('показывает время пройденных шагов из history', async () => { /* ... */ })

it('заказ без history рендерится', async () => { /* ... */ })

it('после DELIVERED показывает заметку про письмо со ссылкой на /mail/', async () => { /* ... */ })
```

- [ ] **Step 2: Запустить тесты, убедиться, что падают**

Run: `make front-test`
Expected: FAIL.

- [ ] **Step 3: Реализовать**

Обновить фикстуру заказа в `frontend/src/api/testing.ts` под `OrderDetail`, затем типы, `endpoints`, `orders.ts`, компонент и страницу. Проверить, что `DELIVERY_STEPS` больше не упоминается: `grep -rn "DELIVERY_STEPS" frontend/src` — пусто.

- [ ] **Step 4: Запустить проверки фронта**

Run: `make front-lint && make front-test`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add frontend
git commit -m "feat: таймлайн заказа на фронте, шаги доставки приезжают с бэка"
```

---

### Task 9: Документация, ТЗ и smoke

**Files:**
- Modify: `docs/stand/grpc-stand-TZ.md`, `docs/api.md`, `docs/decisions.md`, `tests/smoke/test_smoke.py`
- Create: демо-рецепт в `docs/stand/`

**Interfaces:**
- Consumes: всё предыдущее.

Правки ТЗ (дизайн §9): убрать «письма о статусе заказа» из §11 «Вне рамок»; переписать C2 в §2 и формулировку «RabbitMQ — только доставка писем» в §3; диаграмму §3 — два издателя и два потребителя; таблицы методов §6 — `GetOrderTimeline`; DoD §10.

`docs/api.md`: новые поля `GetOrder`, `GetOrderTimeline`, `NOTIFICATION_STATUS_SKIPPED`, событие и его routing key.

`docs/decisions.md` — новыми пунктами: событие и fan-out (со ссылкой на прецедент §28 для правки ТЗ); снимок email и best-effort `GetMe`; `SKIPPED` при пустом адресе; отсутствие outbox и последствия; консьюмер саппорта переживает брокер в отличие от notification-service; UI поддержки отложен; подписи статусов остаются на фронте.

Демо-рецепт: `rabbitmqctl list_queues name messages consumers` и `list_bindings`; эксперимент `docker compose stop notifications` → заказ едет, проекция саппорта пополняется, фронт жив, очередь писем копится → `start` → дренится, письма задним числом.

- [ ] **Step 1: Написать падающий smoke**

```python
async def test_order_status_reaches_both_consumers(...) -> None:
    """Заказ доехал до DELIVERED: письмо о доставке в журнале, проекция у саппорта заполнена."""
    # ждём DELIVERED поллингом GetOrder, затем:
    # ListNotifications(to_email=email) содержит письмо «Заказ доставлен»
    # GetOrderTimeline(order_id) содержит все пять статусов
```

- [ ] **Step 2: Запустить smoke против поднятого стенда**

Run: `make up && make smoke`
Expected: сначала FAIL, если что-то не доехало; разобраться и починить.

- [ ] **Step 3: Починить существующее ожидание smoke**

`tests/smoke/test_smoke.py:99` ждёт ровно одну строку журнала на email покупателя — теперь у покупателя появляется второе письмо. Переписать на «есть письмо с нужной темой», а не «ровно одно письмо».

- [ ] **Step 4: Обновить документацию**

ТЗ, `api.md`, `decisions.md`, демо-рецепт — по списку выше.

- [ ] **Step 5: Полная проверка и коммит**

Run: `make check && make test && make front-lint && make front-test && make smoke`

```bash
git add docs tests
git commit -m "docs: событие order.status_changed в ТЗ, api и decisions, демо-рецепт fan-out"
```

---

## Самопроверка плана

**Покрытие дизайна:** §1 → Task 1, Task 4. §2 → Task 4 (три источника). §3 → Task 2. §4 → Task 7. §5 → Task 3, Task 5 (`SKIPPED`). §6 → Task 5. §7 → Task 6. §8 → Task 8. §9 → Task 9. Не-цели плана не нарушают: `Fulfillment` остаётся поллингом, Redis pub/sub не тронут, management UI не возвращается, стримов в gateway нет, UI поддержки нет, outbox нет.

**Review Focus:** заказ без истории — Task 7 Step 1 и Task 8 Step 1; идемпотентность проекции — Task 6 Step 1; неизвестный статус — Task 5 Step 1 и Task 6; пустой email — Task 5 Step 1; support без брокера — Task 6 Step 1.

**Согласованность имён:** `OrderStatusEvent` (orders, Task 2) и `OrderEvent` (support, Task 6) — разные типы в разных сервисах, пересечения нет. `OrderStatusConsumer` есть и в notifications, и в support — в разных пакетах, по образцу одноимённых `repository.py`. `DELIVERY_STEPS` в `order_service.models` появляется (Task 2) и во `frontend/src/orders.ts` исчезает (Task 8) — это намеренный перенос источника истины, а не коллизия.

**Открытый риск:** Task 2 меняет тип возврата `advance_due`, Task 3 — подпись `create_order`, поэтому существующие тесты `test_fulfillment.py` и `test_checkout.py` правятся внутри этих задач, а не отдельной задачей.
