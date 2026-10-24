"""Общие проверки входных данных user-service."""

import re

from stand_core.grpc import FieldViolation

MIN_PASSWORD_LENGTH = 8
MAX_EMAIL_LENGTH = 254
MAX_DISPLAY_NAME_LENGTH = 100
# Намеренно простая проверка: одна @, непустые части, точка в домене, без пробелов
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
# Цифры с необязательным + в начале, как в E.164
PHONE_RE = re.compile(r"\+?[0-9]{5,15}")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def email_violations(email: str, field: str = "email") -> list[FieldViolation]:
    """`email` — уже нормализованный (`normalize_email`)."""
    if not email:
        return [FieldViolation(field, "must not be empty")]
    if len(email) > MAX_EMAIL_LENGTH or not EMAIL_RE.fullmatch(email):
        return [FieldViolation(field, "must be a valid email address")]
    return []


def password_violations(password: str, field: str = "password") -> list[FieldViolation]:
    if len(password) < MIN_PASSWORD_LENGTH:
        return [FieldViolation(field, f"must be at least {MIN_PASSWORD_LENGTH} characters long")]
    return []


def display_name_violations(display_name: str, field: str = "display_name") -> list[FieldViolation]:
    """`display_name` — уже без пробелов по краям."""
    if not display_name:
        return [FieldViolation(field, "must not be empty")]
    if len(display_name) > MAX_DISPLAY_NAME_LENGTH:
        return [FieldViolation(field, f"must be at most {MAX_DISPLAY_NAME_LENGTH} characters long")]
    return []


def phone_violations(phone: str, field: str = "phone") -> list[FieldViolation]:
    if not PHONE_RE.fullmatch(phone):
        return [FieldViolation(field, "must be 5-15 digits with an optional leading +")]
    return []
