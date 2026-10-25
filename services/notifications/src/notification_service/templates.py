"""Тексты писем: тема и тело plain text (без HTML — проще читать в ящике и проверять в тестах)."""

import math
from dataclasses import dataclass

from stand_core.events import EmailConfirmationRequested


@dataclass(frozen=True)
class EmailContent:
    subject: str
    body: str


def confirmation_email(event: EmailConfirmationRequested) -> EmailContent:
    """Письмо с кодом подтверждения email после `SignUp`."""
    # Срок жизни — в целых минутах с округлением вверх: 90 с → «2 мин», а не «1 мин»
    ttl_min = max(1, math.ceil(event.ttl_s / 60))
    body = (
        f"Здравствуйте, {event.display_name}!\n"
        "\n"
        f"Ваш код подтверждения: {event.code}\n"
        "\n"
        f"Код действует {ttl_min} мин. Введите его на странице подтверждения email,\n"
        "чтобы завершить регистрацию. Если код истёк, зарегистрируйтесь ещё раз —\n"
        "придёт новое письмо.\n"
        "\n"
        "Если вы не регистрировались в Маркетплейс-стенде, просто проигнорируйте это письмо.\n"
    )
    return EmailContent(subject=f"Код подтверждения: {event.code}", body=body)
