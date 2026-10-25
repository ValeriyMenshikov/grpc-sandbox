from notifications.v1 import notifications_pb2
from stand_core import Context, rpc

from notification_service.convert import notification_pb
from notification_service.pagination import decode_page_token, encode_page_token, page_size
from notification_service.repository import NotificationRepository


@rpc("ListNotifications", package="notifications.v1", service="NotificationService")
async def list_notifications(
    request: notifications_pb2.ListNotificationsRequest,
    context: Context,
    repository: NotificationRepository,
) -> notifications_pb2.ListNotificationsResponse:
    # Пустая строка — как не заданный фильтр: письма всем адресатам
    to_email = request.to_email or None
    limit = page_size(request.pagination.page_size)
    offset = decode_page_token(request.pagination.page_token)
    # На одну запись больше лимита — признак следующей страницы
    notifications = await repository.list_notifications(to_email, offset, limit + 1)
    return notifications_pb2.ListNotificationsResponse(
        notifications=[notification_pb(item) for item in notifications[:limit]],
        next_page_token=encode_page_token(offset + limit) if len(notifications) > limit else "",
    )
