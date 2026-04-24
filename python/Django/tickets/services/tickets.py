"""工单流转业务逻辑。所有状态变更都统一走这里，负责：
- 状态转换
- 记录事件
- 产生站内通知
"""

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from ..models import (
    Notification,
    Requirement,
    Ticket,
    TicketComment,
    TicketEvent,
)
from .assignment import select_backend


def _notify(recipient, ticket, text):
    if recipient is None:
        return
    Notification.objects.create(
        recipient=recipient,
        ticket=ticket,
        text=text,
        url=reverse("tickets:detail", kwargs={"pk": ticket.pk}),
    )


def _log(ticket, actor, kind, message=""):
    TicketEvent.objects.create(ticket=ticket, actor=actor, kind=kind, message=message)


@transaction.atomic
def create_ticket(*, creator, ticket: Ticket, requirements_data):
    """创建工单 + 需求条目 + 自动分派给负载最少的后端。

    requirements_data: list[dict]，每个 dict 含 title/detail/difficulty/due_at/order。
    返回 (ticket, assignee_or_none)。
    """
    ticket.created_by = creator
    ticket.status = Ticket.Status.IN_PROGRESS

    assignee = select_backend(project_no=ticket.project_no)
    if assignee:
        ticket.assigned_to = assignee
        ticket.assigned_at = timezone.now()

    ticket.save()

    for idx, data in enumerate(requirements_data):
        Requirement.objects.create(
            ticket=ticket,
            title=data["title"],
            detail=data.get("detail", ""),
            difficulty=data["difficulty"],
            due_at=data["due_at"],
            order=data.get("order", idx),
        )

    _log(ticket, creator, TicketEvent.Kind.SUBMITTED, f"创建工单 {ticket.project_no}")
    if assignee:
        _log(ticket, creator, TicketEvent.Kind.ASSIGNED, f"自动分派给 {assignee.get_username()}")
        _notify(assignee, ticket, f"新工单 {ticket.project_no} 已分派给你")
    return ticket, assignee


@transaction.atomic
def mark_requirement_done(*, actor, requirement: Requirement):
    if requirement.status == Requirement.Status.DONE:
        return requirement
    requirement.status = Requirement.Status.DONE
    requirement.done_at = timezone.now()
    requirement.save(update_fields=["status", "done_at", "updated_at"])
    ticket = requirement.ticket
    _log(
        ticket,
        actor,
        TicketEvent.Kind.REQ_DONE,
        f"标记需求「{requirement.title}」为已完成",
    )
    _notify(
        ticket.created_by,
        ticket,
        f"工单 {ticket.project_no} 的需求「{requirement.title}」已完成，等待你确认",
    )
    return requirement


@transaction.atomic
def reopen_requirement(*, actor, requirement: Requirement):
    reopenable = (
        Requirement.Status.DONE,
        Requirement.Status.ACCEPTED,
        Requirement.Status.REJECTED,
    )
    if requirement.status not in reopenable:
        return requirement
    requirement.status = Requirement.Status.DOING
    requirement.done_at = None
    requirement.accepted_at = None
    requirement.save(update_fields=["status", "done_at", "accepted_at", "updated_at"])
    _log(
        requirement.ticket,
        actor,
        TicketEvent.Kind.REQ_REOPENED,
        f"重置需求「{requirement.title}」为处理中",
    )
    return requirement


@transaction.atomic
def accept_requirement(*, actor, requirement: Requirement):
    """前端确认单条需求结果。"""
    if requirement.status != Requirement.Status.DONE:
        return requirement
    requirement.status = Requirement.Status.ACCEPTED
    requirement.accepted_at = timezone.now()
    requirement.save(update_fields=["status", "accepted_at", "updated_at"])
    ticket = requirement.ticket
    _log(ticket, actor, TicketEvent.Kind.REQ_ACCEPTED, f"前端确认需求「{requirement.title}」结果")
    _notify(ticket.assigned_to, ticket, f"需求「{requirement.title}」已被前端确认接收")
    return requirement


@transaction.atomic
def send_back_requirement(*, actor, requirement: Requirement):
    """前端打回单条需求，要求后端重做。"""
    if requirement.status != Requirement.Status.DONE:
        return requirement
    requirement.status = Requirement.Status.REJECTED
    requirement.done_at = None
    requirement.accepted_at = None
    requirement.save(update_fields=["status", "done_at", "accepted_at", "updated_at"])
    ticket = requirement.ticket
    _log(ticket, actor, TicketEvent.Kind.REQ_SENT_BACK, f"前端打回需求「{requirement.title}」，要求重做")
    _notify(ticket.assigned_to, ticket, f"需求「{requirement.title}」被前端打回，请重新处理")
    return requirement


@transaction.atomic
def submit_for_review(*, actor, ticket: Ticket):
    ticket.status = Ticket.Status.PENDING_FEEDBACK
    ticket.submitted_for_review_at = timezone.now()
    ticket.save(update_fields=["status", "submitted_for_review_at", "updated_at"])
    _log(ticket, actor, TicketEvent.Kind.SENT_FOR_REVIEW, "提交待前端确认")
    _notify(
        ticket.created_by,
        ticket,
        f"工单 {ticket.project_no} 已完成，等待你确认",
    )
    return ticket


@transaction.atomic
def reject_ticket(*, actor, ticket: Ticket, reason: str):
    """前端打回：工单回到处理中，所有已完成需求重置为处理中，并写入评论。"""
    ticket.status = Ticket.Status.IN_PROGRESS
    ticket.submitted_for_review_at = None
    ticket.save(update_fields=["status", "submitted_for_review_at", "updated_at"])
    ticket.requirements.filter(status=Requirement.Status.DONE).update(
        status=Requirement.Status.DOING,
        done_at=None,
    )
    TicketComment.objects.create(
        ticket=ticket,
        author=actor,
        body=reason,
        is_reject_reason=True,
    )
    _log(ticket, actor, TicketEvent.Kind.REJECTED, f"打回重做：{reason[:80]}")
    _notify(
        ticket.assigned_to,
        ticket,
        f"工单 {ticket.project_no} 被打回重做",
    )
    return ticket


@transaction.atomic
def close_ticket(*, actor, ticket: Ticket):
    ticket.status = Ticket.Status.CLOSED
    ticket.closed_at = timezone.now()
    ticket.save(update_fields=["status", "closed_at", "updated_at"])
    _log(ticket, actor, TicketEvent.Kind.CLOSED, "关闭工单")
    _notify(ticket.assigned_to, ticket, f"工单 {ticket.project_no} 已被确认关闭")
    return ticket


@transaction.atomic
def reopen_ticket(*, actor, ticket: Ticket):
    ticket.status = Ticket.Status.IN_PROGRESS
    ticket.closed_at = None
    ticket.save(update_fields=["status", "closed_at", "updated_at"])
    _log(ticket, actor, TicketEvent.Kind.REOPENED, "重新打开工单")
    _notify(ticket.assigned_to, ticket, f"工单 {ticket.project_no} 已被重新打开")
    return ticket


@transaction.atomic
def add_comment(*, actor, ticket: Ticket, body: str):
    comment = TicketComment.objects.create(ticket=ticket, author=actor, body=body)
    _log(ticket, actor, TicketEvent.Kind.COMMENTED, body[:80])
    other = ticket.assigned_to if actor == ticket.created_by else ticket.created_by
    if other and other != actor:
        _notify(other, ticket, f"{actor.get_username()} 在工单 {ticket.project_no} 发表了评论")
    return comment
