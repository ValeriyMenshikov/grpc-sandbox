# Демо: одно событие — два потребителя (`order.status_changed`)

Рецепт показывает fan-out в RabbitMQ без management UI: одно событие order-service
расходится по двум независимым очередям, и остановка одного потребителя не мешает другому.
Почему так устроено — docs/decisions.md §29–§34.

Стенд поднят: `make up`.

## 1. Две очереди на один routing key

```bash
docker compose exec rabbitmq rabbitmqctl list_bindings source_name destination_name routing_key
```

В выводе две строки с `order.status_changed` от `stand.events` — это и есть fan-out:

```
stand.events    notifications.order_status    order.status_changed
stand.events    support.order_events          order.status_changed
stand.events    notifications.email           user.email_confirmation_requested
```

Сообщения и потребители по очередям:

```bash
docker compose exec rabbitmq rabbitmqctl list_queues name messages consumers
```

У `notifications.order_status` и `support.order_events` по одному потребителю и 0 сообщений.
Очереди `*.dead` — dead-letter: туда уходят битые события и события с неизвестным статусом.

## 2. Оба следа одного заказа

Оформите заказ на фронте (`http://localhost:3000`) и дождитесь «Доставлен» (~8 с). Дальше:

```bash
# письмо о доставке — в журнале notification-service и в веб-ящике http://localhost:3000/mail/
grpcurl -plaintext -H 'x-api-key: stand-secret-key' \
  -d '{"to_email": "<email покупателя>"}' \
  localhost:50055 notifications.v1.NotificationService/ListNotifications

# проекция статусов — у support-service, все пять шагов с метками времени
grpcurl -plaintext -H 'x-api-key: stand-secret-key' \
  -d '{"order_id": "<id заказа>"}' \
  localhost:50054 support.v1.SupportService/GetOrderTimeline
```

То же проверяет `make smoke` (`test_order_status_reaches_both_consumers`).

## 3. Эксперимент: один потребитель лежит

```bash
docker compose stop notifications
```

Оформите ещё один заказ. Что видно:

- заказ доезжает до «Доставлен», фронт работает — order-service публикует событие и не ждёт
  потребителей;
- `GetOrderTimeline` по новому заказу отдаёт все пять статусов — у саппорта своя очередь;
- письма нет, а очередь писем копится:

  ```bash
  docker compose exec rabbitmq rabbitmqctl list_queues name messages consumers
  # notifications.order_status    5    0
  # support.order_events          0    1
  ```

Возвращаем потребителя:

```bash
docker compose start notifications
```

Через пару секунд `notifications.order_status` снова `0  1`: очередь дренится, письмо
«Заказ доставлен» приходит задним числом и появляется в `ListNotifications`. Событие пережило
остановку потребителя — в отличие от Redis pub/sub у `TrackOrder`, где отключённый подписчик
просто пропускает сообщения.

## 4. Бонус: support-service переживает брокер

```bash
docker compose stop rabbitmq
docker compose restart support
```

support-service стартует и остаётся healthy, `Chat` работает; в логе
(`docker compose logs -f support`) консьюмер проекции пытается переподключиться с растущей
паузой. После `docker compose start rabbitmq` консьюмер подключается сам. notification-service
устроен наоборот: без RabbitMQ он не стартует — брокер для него обязателен (docs/decisions.md §33).

Оговорка: события, опубликованные, пока брокер лежал, потеряны — outbox'а нет
(docs/decisions.md §34). Новые смены статуса снова доходят до обоих потребителей.
