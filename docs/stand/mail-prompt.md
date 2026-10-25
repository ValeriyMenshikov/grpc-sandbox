# Промт: настоящая почта вместо кода из Redis

Готовый промт для агента/разработчика. Факты сверены с кодом на коммите `80e490a`.

---

## Задача

Сейчас код подтверждения email существует только в Redis (`confirm:{email}`): письма стенд не
отправляет, поэтому UI показывает команду `docker compose exec redis redis-cli get confirm:<email>`,
а smoke-тест лезет в Redis напрямую. Это костыль — его нужно убрать.

Делаем нормальный путь: **users-service публикует событие в RabbitMQ → notification-service
забирает его и отправляет письмо по SMTP в Mailpit → письмо видно в веб-ящике и доступно по его
REST API** (им пользуются тесты). Код подтверждения по-прежнему хранится в Redis и сверяется там
же — меняется только доставка.

## Что меняется в требованиях

Ограничение C2 в `docs/stand/grpc-stand-TZ.md` сейчас запрещает RabbitMQ и почтовые сервисы. Это
осознанное изменение владельца стенда: C2 переписывается закрытым списком —

> C2. Инфраструктура — **только Postgres, Redis, RabbitMQ и Mailpit**. Ничего сверх этого списка:
> никаких Kafka, ZooKeeper, NATS, Envoy, Prometheus и т.п.

C3 (весь стенд в покое ~1 ГБ) **не поднимаем**: сейчас фактически ~330 МБ, RabbitMQ без
management-плагина (~100–120 МБ) и Mailpit (~25 МБ) в бюджет укладываются. Сумма `mem_limit`
вырастет — это нормально, C3 меряется `docker stats`, а не суммой лимитов. Новую цифру замера
кладём в README.

## Архитектура

```
users-service ──publish──> RabbitMQ (exchange stand.events, topic)
                                │  routing key user.email_confirmation_requested
                                ▼
                          notification-service ──SMTP──> Mailpit ──> веб-ящик + REST API
                                │
                                └──> Postgres: журнал попыток (ListNotifications)
```

- **Брокер** — `rabbitmq:4-alpine` (без management-плагина: он ест память, а UI брокера стенду не
  нужен). Клиент — `aio-pika`, оформлен как nuke-di `Client` в `stand_core` (его переиспользует
  любой сервис, который позже захочет публиковать события).
- **Почтовый сервер** — `axllent/mailpit`: SMTP на 1025, веб-интерфейс и REST API на 8025. Писем
  наружу не шлёт, хранит всё у себя — ровно то, что нужно стенду.
- **notification-service** (`services/notifications`, модуль `notification_service`) — обычный
  сервис стенда: `settings.py`, `models.py`, `repository.py` + `schema.sql`, `convert.py`,
  `auth.py`, `handlers/`, `main.py`. Consumer очереди запускается фоновой задачей внутри `serve`
  через `BackgroundTasks` — как `Fulfillment` в order-service.
- Публикует **users-service напрямую в очередь**, а не вызовом gRPC «поставь в очередь»: иначе
  очередь теряет смысл.
- Код подтверждения остаётся в Redis и сверяется в `ConfirmEmail` без изменений. Письмо — канал
  доставки, Redis — источник истины.

## Обязательные требования

1. **Регистрация не падает из-за брокера.** Если RabbitMQ недоступен, `SignUp` логирует ошибку и
   возвращает успех: пользователь создан, код в Redis есть. Исключение наружу не выпускаем.
2. **Доставка at-least-once.** Consumer подтверждает (`ack`) сообщение только после успешной
   отправки SMTP; при ошибке — `nack` без requeue в dead-letter exchange (`x-dead-letter-exchange`)
   и отдельную очередь мёртвых писем. Бесконечный requeue запрещён. Дубль письма с кодом безвреден
   — это зафиксировать в `docs/decisions.md`.
3. **Журнал попыток в Postgres** (`notifications.sent_emails`: id, to_email, subject, status, error,
   created_at). Он даёт gRPC-поверхность сервису (`ListNotifications`, auth `service`), healthcheck
   по общей схеме стенда и видимость сбоев, которые до Mailpit не дошли.
4. **Конфигурация только через env** (C9): адрес брокера, имена exchange/очередей, SMTP-хост и
   порт, адрес отправителя, порты на хосте. Всё новое — в `.env.example`, `docker-compose.yml`
   (с дефолтом `${VAR:-...}`) и `Settings` сервиса.
5. **Порядок старта**: `depends_on` с `condition: service_healthy` для rabbitmq и mailpit;
   у обоих — healthcheck, иначе `make up --wait` ничего не гарантирует.
6. **Фронтенд**: на экране подтверждения вместо подсказки про `redis-cli` — текст «письмо с кодом
   отправлено» и ссылка на почтовый ящик стенда. Ссылка относительная (`/mail/`): nginx фронта
   проксирует её на Mailpit (`MP_WEBROOT=/mail`), чтобы в SPA не было захардкоженного порта и
   браузер ходил на один origin. Прямой доступ к ящику с хоста — `${MAILPIT_UI_PORT:-8025}`.
7. **Smoke-тест** берёт код из REST API Mailpit (поиск по получателю → тело письма), прямое чтение
   Redis из smoke убираем: smoke должен проверять путь пользователя. Письмо приходит асинхронно —
   нужен поллинг с таймаутом и очистка ящика перед сценарием.
8. **Юнит-тесты** — по схеме стенда: хэндлеры и consumer с фейками (`tests/fakes.py`), тесты против
   живых RabbitMQ/Mailpit пропускаются, если их нет (как с Postgres и Redis).

## Что НЕ делаем в этой задаче

- Письма о статусе заказа (создан/доставлен) — следующая задача: шина и consumer к тому моменту
  уже будут готовы, расширение станет дешёвым.
- `LegacyResetPassword` остаётся намеренным антипримером и писем не шлёт.
- Никакого внешнего SMTP-релея и настоящей отправки почты.

## Документация

- `docs/stand/grpc-stand-TZ.md` — C2, дерево каталогов, строка `SignUp` в таблице методов
- `docs/api.md` — описание `SignUp` (письмо + Redis), контракт `notifications.v1`
- `docs/decisions.md` — новый пункт: почему RabbitMQ, почему Mailpit, почему код остаётся в Redis,
  почему sign-up не падает без брокера, at-least-once и дубли, почему `/mail/` через nginx
- `README.md` — новые сервисы и порты, как посмотреть письма, обновлённый замер памяти
- `CLAUDE.md` — модуль нового сервиса и его особенности
- `.env.example` — все новые переменные с комментариями

## Критерии готовности

1. `make up` — все контейнеры healthy, включая rabbitmq, mailpit и notifications
2. Регистрация в браузере: после отправки формы письмо с кодом видно в `/mail/`, код подходит
3. `docker compose stop rabbitmq` — регистрация по-прежнему проходит (без письма), ошибка в логах
4. `docker compose stop mailpit` — письмо попадает в dead-letter очередь и в журнал со статусом
   ошибки, consumer не уходит в бесконечный цикл
5. `make check`, `make test`, `make front-lint`, `make front-test`, `make smoke` — зелёные
6. `make stats` после smoke — стенд в покое укладывается в 1 ГБ (C3), цифра обновлена в README
