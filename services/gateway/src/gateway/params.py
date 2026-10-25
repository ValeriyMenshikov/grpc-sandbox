"""Общие параметры query-строки gateway."""

from typing import Annotated

from fastapi import Query

# Верхние границы — диапазоны полей proto: значение больше не влезет в сообщение (500 вместо 422)
INT32_MAX = 2**31 - 1
INT64_MAX = 2**63 - 1

PageSize = Annotated[
    int, Query(ge=0, le=INT32_MAX, description="0 — размер страницы по умолчанию сервиса")
]
PageToken = Annotated[str, Query(description="next_page_token предыдущей страницы")]
