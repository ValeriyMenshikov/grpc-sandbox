"""Настройки notification-service поверх общих `Settings` стенда."""

from stand_core import Settings


class NotificationSettings(Settings):
    def __init__(self) -> None:
        # Явный __init__ — как у базового Settings: иначе плагин nuke-di считает поля зависимостями
        super().__init__()

    # SMTP-сервер (в стенде — Mailpit); без адреса по умолчанию, как у postgres_dsn/redis_url
    smtp_host: str | None = None
    smtp_port: int = 1025
    smtp_timeout_s: float = 10.0
    mail_from: str = "Маркетплейс-стенд <noreply@stand.local>"
    # Очередь писем, привязанная к exchange событий (`events_exchange`)
    email_queue: str = "notifications.email"
    # Куда уходят сообщения после nack(requeue=False): письмо не отправлено или событие битое
    dead_letter_exchange: str = "stand.events.dead"
    dead_letter_queue: str = "notifications.email.dead"
    # Очередь событий order.status_changed (письмо о доставке) и её отдельный dead-letter:
    # dead-letter писем — fanout, общий exchange смешал бы мёртвые события двух очередей
    order_status_queue: str = "notifications.order_status"
    order_status_dead_letter_exchange: str = "notifications.order_status.dead"
    order_status_dead_letter_queue: str = "notifications.order_status.dead"
