"""Mailer и шаблоны: письмо собирается верно, ошибки SMTP не глотаются.

Последний тест — против Mailpit из compose (make up), без него пропускается.
Адреса — env TEST_SMTP_HOST/TEST_SMTP_PORT/TEST_MAILPIT_URL, по умолчанию compose на localhost.
"""

import asyncio
import os
import uuid
from email.message import EmailMessage
from typing import Any
from unittest.mock import AsyncMock

import aiosmtplib
import httpx
import pytest
from notification_service.mailer import Mailer
from notification_service.settings import NotificationSettings
from notification_service.templates import EmailContent, confirmation_email
from stand_core.events import EmailConfirmationRequested

SMTP_HOST = os.environ.get("TEST_SMTP_HOST", "localhost")
SMTP_PORT = int(os.environ.get("TEST_SMTP_PORT", "1025"))
MAILPIT_URL = os.environ.get("TEST_MAILPIT_URL", "http://localhost:8025/mail")

EVENT = EmailConfirmationRequested(
    email="buyer@example.com", code="123456", display_name="Покупатель", ttl_s=900
)


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAND_API_KEY", "test-key")
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_TIMEOUT_S", "3")
    monkeypatch.setenv("MAIL_FROM", "Стенд <noreply@stand.local>")


@pytest.fixture
def smtp_send(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    send = AsyncMock(return_value=({}, "OK"))
    monkeypatch.setattr(aiosmtplib, "send", send)
    return send


def test_confirmation_email_has_code_and_ttl_in_minutes() -> None:
    content = confirmation_email(EVENT)

    assert "123456" not in content.subject  # тема — в логе и журнале, код только в теле
    assert "Покупатель" in content.body
    assert "Ваш код подтверждения: 123456" in content.body
    assert "15 мин" in content.body


@pytest.mark.parametrize(("ttl_s", "minutes"), [(1, 1), (60, 1), (90, 2), (3600, 60)])
def test_confirmation_email_rounds_ttl_up(ttl_s: int, minutes: int) -> None:
    event = EmailConfirmationRequested(
        email="a@example.com", code="1", display_name="A", ttl_s=ttl_s
    )

    assert f"действует {minutes} мин." in confirmation_email(event).body


async def test_send_builds_message_and_uses_settings(smtp_send: AsyncMock) -> None:
    mailer = Mailer(NotificationSettings())

    await mailer.send(EVENT.email, confirmation_email(EVENT))

    smtp_send.assert_awaited_once()
    [call] = smtp_send.await_args_list
    message = call.args[0]
    assert call.kwargs == {"hostname": "smtp.test", "port": 2525, "timeout": 3.0}
    assert isinstance(message, EmailMessage)
    assert message["From"] == "Стенд <noreply@stand.local>"
    assert message["To"] == "buyer@example.com"
    assert message["Subject"] == "Подтверждение email"
    assert message.get_content_type() == "text/plain"
    assert "Ваш код подтверждения: 123456" in message.get_content()


async def test_send_propagates_smtp_errors(smtp_send: AsyncMock) -> None:
    smtp_send.side_effect = aiosmtplib.SMTPConnectError("connection refused")
    mailer = Mailer(NotificationSettings())

    with pytest.raises(aiosmtplib.SMTPConnectError):
        await mailer.send(EVENT.email, EmailContent("s", "b"))


async def test_send_without_smtp_host_fails(
    monkeypatch: pytest.MonkeyPatch, smtp_send: AsyncMock
) -> None:
    monkeypatch.delenv("SMTP_HOST")
    mailer = Mailer(NotificationSettings())

    with pytest.raises(RuntimeError, match="SMTP_HOST is not set"):
        await mailer.send(EVENT.email, EmailContent("s", "b"))
    smtp_send.assert_not_awaited()


async def test_send_reaches_mailpit(monkeypatch: pytest.MonkeyPatch) -> None:
    async with httpx.AsyncClient(base_url=MAILPIT_URL, timeout=2) as http:
        try:
            (await http.get("/api/v1/info")).raise_for_status()
        except httpx.TransportError as exc:
            # Только «не достучались»: ответ с ошибкой (404 при другом MP_WEBROOT) — падение
            pytest.skip(f"Mailpit is not available ({type(exc).__name__}: {exc}); run make up")
        monkeypatch.setenv("SMTP_HOST", SMTP_HOST)
        monkeypatch.setenv("SMTP_PORT", str(SMTP_PORT))
        # Уникальный адрес: ящик общий со стендом и smoke, чистить его тест не должен
        to_email = f"mailer-test-{uuid.uuid4().hex[:12]}@example.com"

        await Mailer(NotificationSettings()).send(to_email, confirmation_email(EVENT))

        messages: list[dict[str, Any]] = []
        for _ in range(20):
            found = await http.get("/api/v1/search", params={"query": f"to:{to_email}"})
            found.raise_for_status()
            messages = found.json()["messages"]
            if messages:
                break
            await asyncio.sleep(0.1)
        assert len(messages) == 1
        assert messages[0]["Subject"] == "Подтверждение email"
        full = (await http.get(f"/api/v1/message/{messages[0]['ID']}")).json()
        assert "Ваш код подтверждения: 123456" in full["Text"]
        await http.request("DELETE", "/api/v1/messages", json={"IDs": [messages[0]["ID"]]})
