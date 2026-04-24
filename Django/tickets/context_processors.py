from .permissions import can_create_ticket, is_backend, is_frontend, is_manager


def role_flags(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    unread = user.notifications.filter(is_read=False).count()
    return {
        "is_frontend": is_frontend(user),
        "is_backend": is_backend(user),
        "is_manager": is_manager(user),
        "perms_can_create_ticket": can_create_ticket(user),
        "unread_notifications_count": unread,
    }
