"""Отправка писем по SMTP (в стенде — Mailpit) через aiosmtplib."""

from email.message import EmailMessage

import aiosmtplib
from nuke_di import Client, client_dataclass

from notification_service.settings import NotificationSettings
from notification_service.templates import EmailContent


@client_dataclass
class Mailer(Client):
    """SMTP-клиент без постоянного соединения: на каждое письмо — своя короткая сессия.

    Писем мало (одно на регистрацию), а сессия на письмо не требует переподключений после
    рестарта Mailpit. Ошибки SMTP и таймаут поднимаются наружу — что с ними делать (dead-letter,
    запись `FAILED`), решает consumer.
    """

    _settings: NotificationSettings

    def build(self, to_email: str, content: EmailContent) -> EmailMessage:
        message = EmailMessage()
        message["From"] = self._settings.mail_from
        message["To"] = to_email
        message["Subject"] = content.subject
        message.set_content(content.body)
        return message

    async def send(self, to_email: str, content: EmailContent) -> None:
        """Отправляет письмо по SMTP; ошибка SMTP — наружу."""
        host = self._settings.smtp_host
        if not host:
            raise RuntimeError("SMTP_HOST is not set")
        message = self.build(to_email, content)
        await aiosmtplib.send(
            message,
            hostname=host,
            port=self._settings.smtp_port,
            timeout=self._settings.smtp_timeout_s,
        )
