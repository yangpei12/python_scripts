"""工单系统角色与权限判定。

三个 Group：
- frontend：前端（与客户沟通、提交工单、确认结果）
- backend：后端（实际处理需求）
- manager：管理员（可看全量、查统计，兜底转派）

superuser / is_staff 自动视为 manager。
"""

from django.contrib.auth.models import Group

from .models import Requirement, Ticket

GROUP_FRONTEND = "frontend"
GROUP_BACKEND = "backend"
GROUP_MANAGER = "manager"

ALL_GROUPS = (GROUP_FRONTEND, GROUP_BACKEND, GROUP_MANAGER)


def _in_group(user, name):
    if not user.is_authenticated:
        return False
    return user.groups.filter(name=name).exists()


def is_manager(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return _in_group(user, GROUP_MANAGER)


def is_frontend(user) -> bool:
    return _in_group(user, GROUP_FRONTEND)


def is_backend(user) -> bool:
    return _in_group(user, GROUP_BACKEND)


def ensure_groups():
    for name in ALL_GROUPS:
        Group.objects.get_or_create(name=name)


def can_view_ticket(user, ticket: Ticket) -> bool:
    if not user.is_authenticated:
        return False
    if is_manager(user):
        return True
    return (
        ticket.created_by_id == user.id
        or ticket.assigned_to_id == user.id
    )


def can_create_ticket(user) -> bool:
    return is_frontend(user) or is_manager(user)


def can_handle_ticket(user, ticket: Ticket) -> bool:
    """后端当前处理人可标记需求完成 / 提交待确认。"""
    if not user.is_authenticated:
        return False
    if ticket.status != Ticket.Status.IN_PROGRESS:
        return False
    return ticket.assigned_to_id == user.id


def can_submit_for_review(user, ticket: Ticket) -> bool:
    if not can_handle_ticket(user, ticket):
        return False
    reqs = list(ticket.requirements.all())
    if not reqs:
        return False
    finished = {Requirement.Status.DONE, Requirement.Status.ACCEPTED}
    return all(r.status in finished for r in reqs)


def can_confirm_or_reject(user, ticket: Ticket) -> bool:
    """前端提单人在「待前端确认」状态下可整单打回。"""
    if not user.is_authenticated:
        return False
    if ticket.status != Ticket.Status.PENDING_FEEDBACK:
        return False
    return ticket.created_by_id == user.id or is_manager(user)


def can_close_ticket(user, ticket: Ticket) -> bool:
    """前端提单人/管理员可关闭工单的两种情形：
    1) 工单整体处于「待前端确认」（后端整单提交流程）；
    2) 工单仍是「处理中」但所有需求条目已被前端确认（按条目逐条确认完的尾巴）。
    """
    if not user.is_authenticated or ticket.is_closed:
        return False
    if not (ticket.created_by_id == user.id or is_manager(user)):
        return False
    if ticket.status == Ticket.Status.PENDING_FEEDBACK:
        return True
    if ticket.status == Ticket.Status.IN_PROGRESS:
        reqs = list(ticket.requirements.all())
        if not reqs:
            return False
        return all(r.status == Requirement.Status.ACCEPTED for r in reqs)
    return False


def can_reopen_ticket(user, ticket: Ticket) -> bool:
    if not user.is_authenticated:
        return False
    if ticket.status != Ticket.Status.CLOSED:
        return False
    return ticket.created_by_id == user.id or is_manager(user)


def can_comment(user, ticket: Ticket) -> bool:
    return can_view_ticket(user, ticket)


def can_upload_input(user, ticket: Ticket) -> bool:
    """前端提单人或 manager 可上传客户输入资料。"""
    if ticket.is_closed:
        return False
    if is_manager(user):
        return True
    return ticket.created_by_id == user.id and is_frontend(user)


def can_upload_deliverable(user, ticket: Ticket) -> bool:
    """当前后端处理人可上传交付结果。"""
    if ticket.is_closed:
        return False
    if is_manager(user):
        return True
    return (
        ticket.assigned_to_id == user.id
        and is_backend(user)
        and ticket.status == Ticket.Status.IN_PROGRESS
    )


def can_confirm_requirement(user, ticket: Ticket, requirement: Requirement) -> bool:
    """前端提单人（或 manager）在需求状态为「后端已完成」时可确认接收或打回单条需求。"""
    if not user.is_authenticated or ticket.is_closed:
        return False
    if requirement.status != Requirement.Status.DONE:
        return False
    if is_manager(user):
        return True
    return ticket.created_by_id == user.id and is_frontend(user)
