# API стенда

Справочник по контрактам из `protos/`: методы, авторизация, статус-коды, rich details и metadata. Поведение — по ТЗ (docs/stand/grpc-stand-TZ.md, раздел 6); где ТЗ оставляло выбор, ссылка ведёт на docs/decisions.md.

| Сервис | Адрес с хоста | Пакеты proto |
|---|---|---|
| user-service | `localhost:50051` | `users.v1.UserService` |
| catalog-service | `localhost:50052` | `catalog.v1.CatalogService`, `catalog.v1.StockService`, `catalog.v2.CatalogService` |
| order-service | `localhost:50053` | `orders.v1.OrderService` |
| support-service | `localhost:50054` | `support.v1.SupportService` |
| notification-service | `localhost:50055` | `notifications.v1.NotificationService` |
| gateway | `http://localhost:8080` | REST, см. последний раздел |

На каждом gRPC-порту включены reflection (`grpcurl -plaintext localhost:50052 list`) и `grpc.health.v1.Health`.

## Авторизация

| Auth | Что нужно в metadata | Ошибка |
|---|---|---|
| `service` | `x-api-key` | нет или неверный → `UNAUTHENTICATED: Missing or invalid x-api-key` |
| `user` | `x-api-key` + `authorization: Bearer <access_token>` | нет токена → `UNAUTHENTICATED: Missing bearer token`; сессии нет или истекла → `UNAUTHENTICATED: Session is expired or does not exist` |
| `seller` | как `user`, роль пользователя `SELLER` | покупатель → `PERMISSION_DENIED` + `ErrorInfo(reason="SELLER_ROLE_REQUIRED")` |

- `x-api-key` — ключ сервиса-клиента внутри контура, значение — env `STAND_API_KEY` (по умолчанию `stand-secret-key`). Обязателен везде, кроме reflection и health.
- `access_token` выдаёт `users.v1.UserService/SignIn`; сессия лежит в Redis `session:{token}` (TTL `SESSION_TTL_S`, по умолчанию 3600 с).
- Продавец-сид: `seller@stand.local`, пароль — env `SEED_SELLER_PASSWORD` (по умолчанию `seller-password`).

## Metadata

| Ключ | Направление | Где | Смысл |
|---|---|---|---|
| `x-api-key` | запрос | все методы | ключ сервиса-клиента, см. «Авторизация» |
| `authorization` | запрос | Auth `user`/`seller` | `Bearer <access_token>`; сервисы пробрасывают его соседям, когда действуют от имени пользователя (support → orders) |
| `x-request-id` | запрос и initial metadata ответа | все методы | id вызова: берётся из запроса или генерируется (uuid4), возвращается в ответе, пишется в логи и пробрасывается в исходящие вызовы к соседям |
| `x-items-count` | trailing metadata | `ExportProducts`, `TrackOrder`, `Chat` (все исходящие стримы) | сколько сообщений сервер отправил; ставится только при успешном завершении стрима |
| `idempotency-key` | запрос | `orders.v1.OrderService/Checkout` | обязателен, ≤ 128 символов, не пустой; повтор с тем же ключом возвращает тот же заказ (Redis `idem:{user_id}:{key}`, TTL `IDEMPOTENCY_TTL_S` = 24 ч) |
| `x-debug-delay-ms` | запрос | `catalog.v1.StockService/ReserveStock` | искусственная задержка перед резервом в мс, переопределяет env `STOCK_RESERVE_DELAY_MS` (`0` отключает); не целое или < 0 → `INVALID_ARGUMENT` |
| `x-close-reason` | trailing metadata | `support.v1.SupportService/Chat` | почему сервер закрыл чат со статусом `OK`: `idle` (простой `SUPPORT_IDLE_TIMEOUT_S`) или `client_closed` (клиент закончил писать) |
| `grpc-status-details-bin` | trailing metadata | любые ошибки с details | сериализованный `google.rpc.Status` с rich details (см. ниже) |

## Ошибки и rich details

Ошибки возвращаются по [google.rpc error model](https://google.aip.dev/193): код, сообщение и `google.rpc.Status` с details в `grpc-status-details-bin`. В Python details читаются через `grpc_status.rpc_status.from_call(...)` (в тестах стенда — `stand_core.testing.rich_status`).

| Код | Details | Когда |
|---|---|---|
| `INVALID_ARGUMENT` | `BadRequest` (`field_violations[].field`, `description`) | невалидные поля запроса, битый `page_token`, отрицательный `page_size`, неверный код подтверждения, нет `idempotency-key` |
| `NOT_FOUND` | `ResourceInfo` (`resource_type`, `resource_name`) | нет ресурса или он чужой (неразличимо) |
| `ALREADY_EXISTS` | `ResourceInfo` | email уже зарегистрирован |
| `FAILED_PRECONDITION` | `PreconditionFailure` (`violations[].type`, `subject`, `description`) | состояние не позволяет выполнить операцию |
| `RESOURCE_EXHAUSTED` | `QuotaFailure` | импорт длиннее `IMPORT_MAX_ROWS` |
| `UNAUTHENTICATED` | — | нет `x-api-key` / токена, неверная пара email + пароль |
| `PERMISSION_DENIED` | `ErrorInfo(reason=SELLER_ROLE_REQUIRED)` | метод продавца вызван покупателем |
| `UNAVAILABLE` | `ErrorInfo(reason=DEPENDENCY_UNAVAILABLE, metadata.dependency=<сосед>)` | сосед недоступен или не ответил в срок |
| `DEADLINE_EXCEEDED` | — | истёк deadline клиента (в том числе во время задержки `ReserveStock`) |
| `INTERNAL` | — | непойманное исключение; текст всегда `Internal error`, стек — только в логе |
| `UNKNOWN` | — | только антипример `LegacyResetPassword` |
| `UNIMPLEMENTED` | — | метод есть в proto, но хэндлера нет (отвечает сам grpc) |

`ErrorInfo.domain` — всегда `stand.local`.

`type` в `PreconditionFailure`:

| type | Метод | subject |
|---|---|---|
| `INSUFFICIENT_STOCK` | `ReserveStock`, `Checkout` | `product:<id>`, description `requested N, available M` |
| `PRODUCT_NOT_FOUND` | `ReserveStock`, `Checkout` | `product:<id>` |
| `EMAIL_ALREADY_CONFIRMED` | `ConfirmEmail` | `user:<email>` |
| `EMAIL_NOT_CONFIRMED` | `SignIn` | `user:<email>` |
| `CART_EMPTY` | `Checkout` | `cart:<user_id>` |
| `CHECKOUT_IN_PROGRESS` | `Checkout` | `idempotency-key:<key>`: параллельный вызов с тем же ключом ещё не завершён |
| `ORDER_NOT_CANCELLABLE` | `CancelOrder` | `order:<id>`, в description — текущий статус |
| `JOIN_REQUIRED` | `Chat` | `chat`: первым сообщением пришёл не `join` |
| `ALREADY_JOINED` | `Chat` | `chat:<chat_id>`: повторный `join` в том же стриме |

## Общие типы (`common.v1`)

- `Money{currency_code, units, nanos}` — как `google.type.Money`: 199.90 RUB = `{units: 199, nanos: 900000000, currency_code: "RUB"}`. В стенде только `RUB` с точностью до копейки.
- `Pagination{page_size, page_token}` — вкладывается в списочные запросы полем `pagination`. `page_size`: 0 → 20, больше 100 → 100, отрицательный → `INVALID_ARGUMENT`. `page_token` — непрозрачный, берётся из `next_page_token` предыдущего ответа; пустой `next_page_token` — последняя страница. Битый токен → `INVALID_ARGUMENT` + `BadRequest(pagination.page_token)`.
- Даты — `google.protobuf.Timestamp`. Enum — с префиксом типа и нулевым `*_UNSPECIFIED`.

## users.v1.UserService (50051)

| Метод | Тип | Auth | Поведение | Ошибки |
|---|---|---|---|---|
| `SignUp` | unary | service | Создаёт пользователя `USER_STATUS_PENDING`. Код подтверждения (6 цифр) — в Redis `confirm:{email}`, TTL `CONFIRM_CODE_TTL_S` (900 с), и письмом: событие `user.email_confirmation_requested` в RabbitMQ → notification-service → Mailpit (тест берёт письмо из REST API Mailpit `/mail/api/v1`). Брокер недоступен — ответ тот же, ошибка в логе, письма нет. `role` не задана → `USER_ROLE_BUYER`. Email нормализуется (обрезка, нижний регистр). | `INVALID_ARGUMENT` + `BadRequest` со всеми нарушениями сразу (email, пароль < 8, пустое `display_name`, неизвестная `role`); `ALREADY_EXISTS` |
| `ConfirmEmail` | unary | service | Переводит пользователя в `USER_STATUS_ACTIVE`, код удаляется. | пустые поля → `INVALID_ARGUMENT`; нет пользователя → `NOT_FOUND` (`ResourceInfo` user); уже подтверждён → `FAILED_PRECONDITION` (`EMAIL_ALREADY_CONFIRMED`); кода нет или истёк → `NOT_FOUND` (`ResourceInfo` confirmation_code); код не совпал → `INVALID_ARGUMENT` (`BadRequest` по `code`) |
| `SignIn` | unary | service | `access_token`, `expires_at`, `user`. Каждый вход — новая сессия. | нет пользователя или неверный пароль → `UNAUTHENTICATED: Invalid email or password` (одинаково); email не подтверждён → `FAILED_PRECONDITION` (`EMAIL_NOT_CONFIRMED`) |
| `SignOut` | unary | user | Удаляет текущую сессию (остальные сессии живут до TTL). | — |
| `GetMe` | unary | user | Профиль текущего пользователя. | пользователь удалён → `NOT_FOUND` |
| `UpdateProfile` | unary | user | Частичное обновление по `update_mask` (`display_name`, `phone`); поля вне маски не меняются. `phone` в маске без значения удаляет телефон. | пустая маска или неизвестный путь → `INVALID_ARGUMENT` (`update_mask.paths[i]`); телефон не 5–15 цифр с необязательным `+` → `INVALID_ARGUMENT` |
| `LegacyResetPassword` | unary | service | **Намеренный антипример.** Меняет пароль по email. | любая ошибка (невалидный email, короткий пароль, неизвестный пользователь) → `UNKNOWN: Validation failed` **без details** |

> ⚠️ `LegacyResetPassword` — так делать нельзя: клиент не может отличить ошибку валидации от сбоя сервера и не знает, какое поле исправить. Метод нужен курсу как материал для теста-«обличителя». Правильный вариант — `INVALID_ARGUMENT` + `BadRequest`, как у `SignUp`.

## catalog.v1.CatalogService (50052)

| Метод | Тип | Auth | Поведение | Ошибки |
|---|---|---|---|---|
| `GetProduct` | unary | service | Товар по `product_id`. `stock` — доступный остаток (остаток − резервы). | пустой id → `INVALID_ARGUMENT`; нет товара → `NOT_FOUND` |
| `SearchProducts` | unary | service | `query` — подстрока названия без учёта регистра; `category` — точное совпадение; `min_price_kopecks`/`max_price_kopecks` — включительно; `sort`: по названию (по умолчанию), `PRICE_ASC`, `PRICE_DESC`, `NEWEST`; пагинация. | битый `page_token`, отрицательный `page_size`, отрицательные цены, `min > max` → `INVALID_ARGUMENT` |
| `ImportProducts` | client stream | seller | Первое сообщение — `header{mode}` (`UPSERT` / `CREATE_ONLY`), дальше `row{offer_id, name, category, price_kopecks, stock}`. Ответ — отчёт `created`, `updated`, `failed`, `errors[]{row_number, field, description}`. Плохие строки попадают в `errors`, остальные пишутся одной транзакцией. В `CREATE_ONLY` существующий `offer_id` — ошибка строки. | нет заголовка, `IMPORT_MODE_UNSPECIFIED`, второй заголовок → `INVALID_ARGUMENT`; строк больше `IMPORT_MAX_ROWS` (10 000) → `RESOURCE_EXHAUSTED` + `QuotaFailure(subject="seller:<id>")`, ничего не пишется |
| `ExportProducts` | server stream | seller | Товары текущего продавца по одному (`updated_at, product_id`), `updated_since` — включительно. Trailing `x-items-count`. | — |

Проверки строки импорта: `offer_id`, `name`, `category` не пустые и не длиннее 64/255/64 символов; `0 < price_kopecks <= 10¹²` (10 млрд ₽); `stock >= 0`. Номер строки — с 1, заголовок не считается.

## catalog.v1.StockService (50052, внутренний)

Вызывает order-service. Курс может звать напрямую — для уроков про deadline и ретраи.

| Метод | Тип | Auth | Поведение | Ошибки |
|---|---|---|---|---|
| `GetStock` | unary | service | Доступный остаток `available`. | пустой id → `INVALID_ARGUMENT`; нет товара → `NOT_FOUND` |
| `ReserveStock` | unary | service | Атомарный резерв всех позиций под `order_id`: либо все, либо ни одной. Повтор с тем же `order_id` возвращает существующий резерв. Задержка перед резервом — env `STOCK_RESERVE_DELAY_MS` или metadata `x-debug-delay-ms`; если deadline короче задержки, вызов завершается `DEADLINE_EXCEEDED` без резерва. | пустой `order_id`/список/`product_id`, `quantity <= 0`, повтор товара → `INVALID_ARGUMENT` (`items[i].quantity`, ...); нехватка или нет товара → `FAILED_PRECONDITION` + `PreconditionFailure` по каждому товару (`INSUFFICIENT_STOCK` / `PRODUCT_NOT_FOUND`) |
| `ReleaseStock` | unary | service | Снимает резерв, идемпотентно: `released=false`, если резерва уже не было. Идущий `ReserveStock` с тем же `order_id` дожидается. | пустой `order_id` → `INVALID_ARGUMENT` |

## catalog.v2.CatalogService (50052)

Новая версия контракта на том же порту, что и v1. Только `GetProduct` и `SearchProducts`, Auth — `service`, поведение и ошибки как в v1, кроме отличий:

| | catalog.v1 | catalog.v2 |
|---|---|---|
| Цена товара | `int64 price_kopecks = 6` | `common.v1.Money price = 10`; поле 6 удалено **без `reserved`** |
| Фильтр цены в поиске | `optional int64 min_price_kopecks = 3`, `max_price_kopecks = 4` | `Money min_price = 8`, `max_price = 9` (номера 3 и 4 не используются) |
| Регион | нет | `string region_id = 7`, **обязателен**: пустой или из пробелов → `INVALID_ARGUMENT`; на выдачу пока не влияет |
| Методы | `GetProduct`, `SearchProducts`, `ImportProducts`, `ExportProducts` | только `GetProduct`, `SearchProducts` |

`Money` в фильтрах v2: только `RUB` (пустой `currency_code` = RUB), неотрицательная, `nanos` кратны 10⁷ (копейки); сумма не больше предела bigint в копейках; нарушения → `INVALID_ARGUMENT` с полем (`min_price.currency_code`, `max_price.nanos`, `max_price.units`, ...). Токены пагинации v1 и v2 совместимы.

Чем это интересно курсу: клиент v1, прочитавший товар v2 (и наоборот), молча получит цену 0 — номер поля другой, а удалённый номер не зарезервирован. `buf breaking` такое ловит.

## orders.v1.OrderService (50053)

Все методы — Auth `user`.

| Метод | Тип | Поведение | Ошибки |
|---|---|---|---|
| `AddCartItem` | unary | Прибавляет `quantity` к позиции в Redis `cart:{user_id}`; остаток не проверяет. Возвращает корзину. | пустой `product_id`, `quantity <= 0`, `quantity` или итог позиции больше 10 000 → `INVALID_ARGUMENT`; товара нет в catalog → `NOT_FOUND`; catalog недоступен → `UNAVAILABLE` |
| `RemoveCartItem` | unary | Удаляет позицию целиком. | позиции нет → `NOT_FOUND` (`ResourceInfo` cart_item); catalog недоступен → `UNAVAILABLE` |
| `GetCart` | unary | Позиции с актуальными названием, ценой (`unit_price`) и остатком (`available`) из catalog, `total`. Пропавшие из catalog товары в ответ не попадают. | catalog недоступен → `UNAVAILABLE` |
| `Checkout` | unary | `idempotency-key` → email покупателя через `UserService.GetMe` с его `authorization` (best-effort, таймаут `USERS_EMAIL_TIMEOUT_S`; не получили — заказ оформляется с пустым email, ошибок не добавляет, docs/decisions.md §31) → резерв `StockService.ReserveStock` (с пробросом deadline и `x-request-id`) → снимок цен → заказ `ORDER_STATUS_CREATED` → корзина очищается. Повтор с тем же ключом — тот же заказ в текущем статусе. | нет/пустой/длинный `idempotency-key` → `INVALID_ARGUMENT`; пустая корзина → `FAILED_PRECONDITION` (`CART_EMPTY`); нехватка → `FAILED_PRECONDITION` с деталями от catalog как есть; параллельный повтор → `FAILED_PRECONDITION` (`CHECKOUT_IN_PROGRESS`); catalog недоступен или не ответил в срок → `UNAVAILABLE` (`DEPENDENCY_UNAVAILABLE`, dependency=catalog), заказ не создаётся. При любой ошибке ключ освобождается |
| `GetOrder` | unary | Заказ по `order_id`, `history` — смены статуса `{status, changed_at}` (старые первыми; у заказа, оформленного до появления истории, пусто), `delivery_steps` — порядок шагов доставки `CREATED → … → DELIVERED` (без `CANCELLED`). Подписи статусов — дело клиента. | пустой id → `INVALID_ARGUMENT`; чужой или нет → `NOT_FOUND` (неразличимо) |
| `ListOrders` | unary | Заказы пользователя, новые первыми, фильтр `status` (не задан или `UNSPECIFIED` — все), пагинация. | неизвестный `status`, битый токен → `INVALID_ARGUMENT` |
| `CancelOrder` | unary | Отмена в статусах `CREATED`, `PAID`, `ASSEMBLING` + `ReleaseStock`. Повторная отмена отменённого — не ошибка (снова снимает резерв). | `HANDED_TO_COURIER`/`DELIVERED` → `FAILED_PRECONDITION` (`ORDER_NOT_CANCELLABLE`); чужой/нет → `NOT_FOUND`; catalog недоступен при снятии резерва → `UNAVAILABLE` |
| `TrackOrder` | server stream | Первым сообщением — текущий статус, дальше каждое изменение с `changed_at`. Закрывается `OK` после `DELIVERED` или `CANCELLED`, trailing `x-items-count`. Изменения — через Redis pub/sub `orders.status.{order_id}`. | пустой id → `INVALID_ARGUMENT`; чужой/нет → `NOT_FOUND` |

Каждая смена статуса (`Checkout` → `CREATED`, доставка, `CancelOrder` → `CANCELLED`) пишется строкой в `orders.order_status_history` в той же операции и публикуется событием `order.status_changed` (см. «События RabbitMQ»).

Доставка: `CREATED → PAID → ASSEMBLING → HANDED_TO_COURIER → DELIVERED`, шаг `FULFILLMENT_STEP_MS` (2000 мс). Любой заказ доезжает до `DELIVERED` за ~8 с, если его не отменить.

## support.v1.SupportService (50054)

`Chat` и `GetChatHistory` — Auth `user`, `GetOrderTimeline` — Auth `service`.

### Chat (bidi stream)

Входящие `ChatRequest.payload`:

| Сообщение | Что делает |
|---|---|
| `join{order_id}` | Обязательно первым. Заказ проверяется через order-service `GetOrder` с `authorization` пользователя и `x-request-id`. Ответ — `joined{chat_id, last_messages}` (старые первыми). |
| `message{client_message_id, text}` | Сохраняется в Postgres, сервер сразу шлёт `ack{client_message_id, message_id, created_at}`. |
| `read{message_id}` | Отмечает сообщение прочитанным; неизвестный id — без ошибки. |

Исходящие `ChatResponse.payload`: `joined`, `ack`, `message{message_id, author, text, created_at}` (`AUTHOR_AGENT` / `AUTHOR_BOT`, а также сообщения покупателя из другого стрима того же чата), `agent_typing`.

Поведение:

- **Сервер пишет сам.** Через `SUPPORT_AGENT_DELAY_MS` (1500 мс) после `join` приходят `agent_typing` и сообщение `AGENT` «Здравствуйте, я оператор поддержки. Чем могу помочь?» — без запроса клиента. Тест не может читать стрим строго «запрос → ответ».
- **Бот.** Если в тексте есть «статус» или «где» (без учёта регистра), бот спрашивает order-service и отвечает `BOT` «Заказ {order_id}: {статус}». Order-service недоступен → `BOT` «Не удалось получить статус, попробуйте позже», стрим **не рвётся**.
- **Простой.** `SUPPORT_IDLE_TIMEOUT_S` (60 с) без `message`/`read` от клиента → стрим завершается `OK`, trailing `x-close-reason: idle`.
- **Клиент закончил писать** (half-close) → сервер дожидается ответов бота на заданные вопросы и завершает `OK` с `x-close-reason: client_closed`.
- Trailing `x-items-count` — число отправленных сервером сообщений.

Ошибки (завершают стрим):

| Код | Когда |
|---|---|
| `FAILED_PRECONDITION` + `PreconditionFailure(JOIN_REQUIRED)` | первым пришёл не `join`, или клиент закрыл стрим до `join` |
| `FAILED_PRECONDITION` (`ALREADY_JOINED`) | повторный `join` |
| `INVALID_ARGUMENT` | пустой `order_id` в `join`, пустой `text` |
| `NOT_FOUND` | заказа нет или он чужой |
| `UNAVAILABLE` | order-service недоступен в момент `join` (без заказа чат не открыть) |

### GetChatHistory (unary)

История чата по `order_id`, старые первыми, пагинация. Чата нет или он чужой → `NOT_FOUND` (`ResourceInfo` chat). Order-service не вызывается.

### GetOrderTimeline (unary)

Проекция статусов заказа `support.order_events`, которую консьюмер support-service строит из событий `order.status_changed` (очередь `support.order_events`): `events{status, changed_at}`, старые первыми; `changed_at` — когда статус сменил order-service, а не когда событие дошло. Eventual consistency: отдаёт то, что успело дойти; неизвестный заказ — пустой список, а не `NOT_FOUND` (support не знает заказов, которых не видел). Order-service не вызывается. Пустой `order_id` → `INVALID_ARGUMENT`.

Без RabbitMQ support-service стартует и `Chat` работает; консьюмер переподключается в фоне с backoff `ORDER_EVENTS_RECONNECT_DELAY_S` → `ORDER_EVENTS_RECONNECT_MAX_DELAY_S` (docs/decisions.md §33).

## notifications.v1.NotificationService (50055)

Журнал писем. Сами письма уходят не по gRPC: notification-service потребляет события из RabbitMQ (см. «События RabbitMQ»: письмо с кодом на `user.email_confirmation_requested`, письмо «Заказ доставлен» на `order.status_changed` со статусом `DELIVERED`) и отправляет их по SMTP в Mailpit. Каждая попытка — запись в журнале со статусом `NOTIFICATION_STATUS_SENT`, `NOTIFICATION_STATUS_FAILED` (в `error` — текст ошибки, сообщение уходит в dead-letter без повторов) или `NOTIFICATION_STATUS_SKIPPED` (письмо не отправлялось: у `DELIVERED` пустой email покупателя; в `error` — причина, сообщение подтверждено, docs/decisions.md §32). Остальные статусы заказа подтверждаются без письма и без записи.

| Метод | Тип | Auth | Поведение | Ошибки |
|---|---|---|---|---|
| `ListNotifications` | unary | service | Попытки отправки `{notification_id, to_email, subject, status, error, created_at}`, новые первыми; фильтр `to_email` (не задан — все адресаты, сравнение без учёта регистра), пагинация. У неразобранного события `to_email` пустой. | отрицательный `page_size`, битый `page_token` → `INVALID_ARGUMENT` |

## События RabbitMQ

Topic exchange `stand.events`, тело — JSON; формат и разбор — `stand_core.events` (издатель и потребитель пользуются одними функциями). Разбор строгий к обязательным полям и терпимый к лишним. Очереди объявляет потребитель, у каждой — свой dead-letter через `stand.events.dead`; битое тело или неизвестный статус → `nack(requeue=False)` в dead-letter.

| Routing key | Издатель | Тело | Очереди (потребитель) |
|---|---|---|---|
| `user.email_confirmation_requested` | user-service, `SignUp` | `{email, code, display_name, ttl_s, request_id?}` | `notifications.email` (notification-service: письмо с кодом) |
| `order.status_changed` | order-service: `Checkout`, доставка, `CancelOrder` | `{order_id, user_id, status, changed_at, email?, request_id?}` | `notifications.order_status` (notification-service: письмо на `DELIVERED`), `support.order_events` (support-service: проекция для `GetOrderTimeline`) |

`order.status_changed`: `status` — имя `OrderStatus` без префикса (`CREATED`, `PAID`, `ASSEMBLING`, `HANDED_TO_COURIER`, `DELIVERED`, `CANCELLED`), `changed_at` — ISO 8601 момента смены статуса, `email` — снимок email покупателя на момент оформления, может быть пустым. Публикация best-effort после записи в Postgres, без outbox: событие может потеряться (docs/decisions.md §34). Доставка at-least-once: проекция support-service идемпотентна по `(order_id, status)`. Fan-out виден в `rabbitmqctl list_bindings` — демо-рецепт в docs/stand/order-events-demo.md.

## gateway — REST (8080)

BFF для веб-фронта. Сам подставляет `x-api-key`, пробрасывает `Authorization` (только в методы Auth `user`) и `X-Request-Id` (возвращается в ответе; без него генерируется). Стримов на gateway нет.

| HTTP | gRPC | Тело / параметры |
|---|---|---|
| `POST /auth/sign-up` → 201 | `UserService/SignUp` | `{email, password, display_name, role: "BUYER"\|"SELLER"}` |
| `POST /auth/confirm` | `UserService/ConfirmEmail` | `{email, code}` |
| `POST /auth/sign-in` | `UserService/SignIn` | `{email, password}` → `{access_token, expires_at, user}` |
| `GET /me` | `UserService/GetMe` | `Authorization: Bearer …` |
| `GET /products` | `catalog.v1 SearchProducts` | `query`, `category`, `min_price_kopecks`, `max_price_kopecks`, `sort=name\|price_asc\|price_desc\|newest`, `page_size`, `page_token` |
| `GET /products/{id}` | `catalog.v1 GetProduct` | цена отдаётся как `Money` |
| `GET /cart` | `OrderService/GetCart` | |
| `POST /cart/items` | `OrderService/AddCartItem` | `{product_id, quantity=1}` |
| `DELETE /cart/items/{product_id}` | `OrderService/RemoveCartItem` | |
| `POST /checkout` | `OrderService/Checkout` | заголовок `Idempotency-Key` → metadata `idempotency-key` |
| `GET /orders` | `OrderService/ListOrders` | `status=CREATED\|…\|CANCELLED`, `page_size`, `page_token` |
| `GET /orders/{id}` | `OrderService/GetOrder` | заказ + `history: [{status, changed_at}]` и `delivery_steps: ["CREATED", …]` |
| `GET /healthz` | — | без вызовов соседей |

Маппинг gRPC → HTTP:

| gRPC | HTTP |
|---|---|
| `INVALID_ARGUMENT`, `FAILED_PRECONDITION`, `OUT_OF_RANGE` | 400 |
| `UNAUTHENTICATED` | 401 + `WWW-Authenticate: Bearer` |
| `PERMISSION_DENIED` | 403 |
| `NOT_FOUND` | 404 |
| `ALREADY_EXISTS`, `ABORTED` | 409 |
| `RESOURCE_EXHAUSTED` | 429 |
| `UNAVAILABLE` (в том числе недоступный сервис) | 503 |
| `DEADLINE_EXCEEDED` | 504 |
| прочее | 500 |

Тело ошибки: `{"error": {"code": "NOT_FOUND", "message": "...", "details": [{"@type": "type.googleapis.com/google.rpc.ResourceInfo", ...}]}}`. Невалидный HTTP-запрос (тело, неизвестный `sort`/`status`) — стандартный 422 FastAPI.
