from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max, Q
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from datetime import timedelta

from .forms import (
    AttachmentForm,
    CommentForm,
    RejectForm,
    RequirementFormSet,
    TicketForm,
)
from .models import Notification, OVERDUE_DAYS, Requirement, Ticket, TicketAttachment
from .permissions import (
    can_close_ticket,
    can_comment,
    can_confirm_or_reject,
    can_confirm_requirement,
    can_create_ticket,
    can_handle_ticket,
    can_reopen_ticket,
    can_submit_for_review,
    can_upload_deliverable,
    can_upload_input,
    can_view_ticket,
    is_manager,
)
from .services import tickets as ticket_service


def _ticket_queryset(user):
    qs = Ticket.objects.select_related("created_by", "assigned_to").prefetch_related(
        "requirements"
    )
    if is_manager(user):
        return qs
    return qs.filter(Q(created_by=user) | Q(assigned_to=user)).distinct()


@login_required
def ticket_list(request):
    qs = _ticket_queryset(request.user)
    q = (request.GET.get("q") or "").strip()
    status = request.GET.get("status") or ""
    scope = request.GET.get("scope") or ""

    if q:
        qs = qs.filter(
            Q(project_no__icontains=q)
            | Q(project_name__icontains=q)
            | Q(client_name__icontains=q)
            | Q(requirements__title__icontains=q)
        ).distinct()
    if status:
        qs = qs.filter(status=status)
    if scope == "created":
        qs = qs.filter(created_by=request.user)
    elif scope == "assigned":
        qs = qs.filter(assigned_to=request.user)

    return render(
        request,
        "tickets/ticket_list.html",
        {
            "tickets": qs,
            "q": q,
            "status": status,
            "scope": scope,
            "status_choices": Ticket.Status.choices,
        },
    )


@login_required
def ticket_create(request):
    if not can_create_ticket(request.user):
        return HttpResponseForbidden("仅前端人员可创建工单。")
    if request.method == "POST":
        form = TicketForm(request.POST)
        formset = RequirementFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            ticket = form.save(commit=False)
            reqs_data = [
                {
                    "title": f.cleaned_data["title"],
                    "detail": f.cleaned_data.get("detail", ""),
                    "difficulty": f.cleaned_data["difficulty"],
                    "due_at": f.cleaned_data["due_at"],
                    "order": f.cleaned_data.get("order") or idx,
                }
                for idx, f in enumerate(formset.forms)
                if f.cleaned_data and not f.cleaned_data.get("DELETE")
            ]
            ticket, assignee = ticket_service.create_ticket(
                creator=request.user, ticket=ticket, requirements_data=reqs_data
            )
            if assignee:
                messages.success(request, f"工单已创建，已自动分派给 {assignee.get_username()}。")
            else:
                messages.warning(request, "工单已创建，但系统未找到可用的后端处理人。请联系管理员。")
            return redirect(ticket.get_absolute_url())
        sniff_project_no = (request.POST.get("project_no") or "").strip()
    else:
        prefill_pn = (request.GET.get("project_no") or "").strip()
        initial = {}
        if prefill_pn:
            initial["project_no"] = prefill_pn
            latest = (
                Ticket.objects.filter(project_no=prefill_pn)
                .order_by("-created_at")
                .values("project_name", "client_name")
                .first()
            )
            if latest:
                initial.setdefault("project_name", latest["project_name"])
                initial.setdefault("client_name", latest["client_name"])
        form = TicketForm(initial=initial)
        formset = RequirementFormSet()
        sniff_project_no = prefill_pn

    existing_count = 0
    if sniff_project_no:
        existing_count = Ticket.objects.filter(project_no=sniff_project_no).count()

    return render(
        request,
        "tickets/ticket_form.html",
        {
            "form": form,
            "formset": formset,
            "sniff_project_no": sniff_project_no,
            "existing_project_ticket_count": existing_count,
        },
    )


@login_required
def ticket_detail(request, pk):
    ticket = get_object_or_404(
        Ticket.objects.select_related("created_by", "assigned_to"), pk=pk
    )
    if not can_view_ticket(request.user, ticket):
        raise Http404()

    can_input = can_upload_input(request.user, ticket)
    can_deliverable = can_upload_deliverable(request.user, ticket)

    # 按需求 ID 索引交付结果附件，并直接挂到 requirement 对象上
    requirements = list(ticket.requirements.all())
    req_del_map: dict = {}
    for att in ticket.attachments.filter(
        kind=TicketAttachment.Kind.DELIVERABLE,
        requirement__isnull=False,
    ).select_related("uploaded_by"):
        req_del_map.setdefault(att.requirement_id, []).append(att)
    for r in requirements:
        r.deliverables = req_del_map.get(r.pk, [])
        r.can_confirm = can_confirm_requirement(request.user, ticket, r)

    ctx = {
        "ticket": ticket,
        "requirements": requirements,
        "inputs": ticket.attachments.filter(kind=TicketAttachment.Kind.INPUT).select_related("uploaded_by"),
        "comments": ticket.comments.select_related("author").all(),
        "events": ticket.events.select_related("actor").all()[:80],
        "comment_form": CommentForm() if can_comment(request.user, ticket) else None,
        "reject_form": RejectForm() if can_confirm_or_reject(request.user, ticket) else None,
        "can_upload_input": can_input,
        "can_upload_deliverable": can_deliverable,
        "can_handle": can_handle_ticket(request.user, ticket),
        "can_submit_for_review": can_submit_for_review(request.user, ticket),
        "can_confirm_or_reject": can_confirm_or_reject(request.user, ticket),
        "can_close": can_close_ticket(request.user, ticket),
        "can_reopen": can_reopen_ticket(request.user, ticket),
    }
    return render(request, "tickets/ticket_detail.html", ctx)


def _get_ticket_or_403(user, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    if not can_view_ticket(user, ticket):
        raise Http404()
    return ticket


@login_required
@require_POST
def requirement_done(request, pk, req_pk):
    ticket = _get_ticket_or_403(request.user, pk)
    if not can_handle_ticket(request.user, ticket):
        return HttpResponseForbidden("仅当前处理人可更新需求状态。")
    requirement = get_object_or_404(Requirement, pk=req_pk, ticket=ticket)
    ticket_service.mark_requirement_done(actor=request.user, requirement=requirement)
    messages.success(request, f"需求「{requirement.title}」已标记完成。")
    return redirect(ticket.get_absolute_url())


@login_required
@require_POST
def requirement_reopen(request, pk, req_pk):
    ticket = _get_ticket_or_403(request.user, pk)
    if not can_handle_ticket(request.user, ticket):
        return HttpResponseForbidden("仅当前处理人可重置需求状态。")
    requirement = get_object_or_404(Requirement, pk=req_pk, ticket=ticket)
    ticket_service.reopen_requirement(actor=request.user, requirement=requirement)
    messages.success(request, f"需求「{requirement.title}」已重置为处理中。")
    return redirect(ticket.get_absolute_url())


@login_required
@require_POST
def ticket_submit_for_review(request, pk):
    ticket = _get_ticket_or_403(request.user, pk)
    if not can_submit_for_review(request.user, ticket):
        messages.error(request, "请先将所有需求条目标记为已完成，再提交待确认。")
        return redirect(ticket.get_absolute_url())
    ticket_service.submit_for_review(actor=request.user, ticket=ticket)
    messages.success(request, "已提交给前端确认。")
    return redirect(ticket.get_absolute_url())


@login_required
@require_POST
def ticket_close(request, pk):
    ticket = _get_ticket_or_403(request.user, pk)
    if not can_close_ticket(request.user, ticket):
        return HttpResponseForbidden("当前状态或身份无法关闭工单。")
    ticket_service.close_ticket(actor=request.user, ticket=ticket)
    messages.success(request, "工单已关闭。")
    return redirect(ticket.get_absolute_url())


@login_required
@require_POST
def ticket_reject(request, pk):
    ticket = _get_ticket_or_403(request.user, pk)
    if not can_confirm_or_reject(request.user, ticket):
        return HttpResponseForbidden("当前状态或身份无法打回工单。")
    form = RejectForm(request.POST)
    if not form.is_valid():
        messages.error(request, "请填写打回原因。")
        return redirect(ticket.get_absolute_url())
    ticket_service.reject_ticket(
        actor=request.user, ticket=ticket, reason=form.cleaned_data["reason"]
    )
    messages.success(request, "已打回给后端重新处理。")
    return redirect(ticket.get_absolute_url())


@login_required
@require_POST
def ticket_reopen(request, pk):
    ticket = _get_ticket_or_403(request.user, pk)
    if not can_reopen_ticket(request.user, ticket):
        return HttpResponseForbidden("无法重开该工单。")
    ticket_service.reopen_ticket(actor=request.user, ticket=ticket)
    messages.success(request, "工单已重新打开。")
    return redirect(ticket.get_absolute_url())


@login_required
@require_POST
def comment_create(request, pk):
    ticket = _get_ticket_or_403(request.user, pk)
    if not can_comment(request.user, ticket):
        return HttpResponseForbidden()
    form = CommentForm(request.POST)
    if not form.is_valid():
        messages.error(request, "评论内容不能为空。")
        return redirect(ticket.get_absolute_url())
    ticket_service.add_comment(
        actor=request.user, ticket=ticket, body=form.cleaned_data["body"]
    )
    return redirect(ticket.get_absolute_url() + "#comments")


@login_required
@require_POST
def attachment_upload(request, pk):
    ticket = _get_ticket_or_403(request.user, pk)
    form = AttachmentForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "上传失败：%s" % form.errors.as_text())
        return redirect(ticket.get_absolute_url())
    kind = form.cleaned_data["kind"]
    f = form.cleaned_data["file"]

    if kind == TicketAttachment.Kind.INPUT and not can_upload_input(request.user, ticket):
        return HttpResponseForbidden("无权上传客户输入资料。")
    if kind == TicketAttachment.Kind.DELIVERABLE and not can_upload_deliverable(request.user, ticket):
        return HttpResponseForbidden("无权上传交付结果。")

    att = TicketAttachment.objects.create(
        ticket=ticket,
        kind=kind,
        file=f,
        original_name=getattr(f, "name", "") or "",
        size=getattr(f, "size", 0) or 0,
        uploaded_by=request.user,
    )
    from .models import TicketEvent
    TicketEvent.objects.create(
        ticket=ticket,
        actor=request.user,
        kind=TicketEvent.Kind.ATTACHED,
        message=f"上传{att.get_kind_display()}：{att.original_name}",
    )
    messages.success(request, "附件已上传。")
    return redirect(ticket.get_absolute_url() + "#attachments")


@login_required
@require_POST
def requirement_accept(request, pk, req_pk):
    """前端确认单条需求结果。"""
    ticket = _get_ticket_or_403(request.user, pk)
    requirement = get_object_or_404(Requirement, pk=req_pk, ticket=ticket)
    if not can_confirm_requirement(request.user, ticket, requirement):
        return HttpResponseForbidden("当前状态或身份无法确认该需求。")
    ticket_service.accept_requirement(actor=request.user, requirement=requirement)
    messages.success(request, f"需求「{requirement.title}」已确认接收。")
    return redirect(ticket.get_absolute_url() + "#req-" + str(req_pk))


@login_required
@require_POST
def requirement_send_back(request, pk, req_pk):
    """前端打回单条需求，要求后端重做。"""
    ticket = _get_ticket_or_403(request.user, pk)
    requirement = get_object_or_404(Requirement, pk=req_pk, ticket=ticket)
    if not can_confirm_requirement(request.user, ticket, requirement):
        return HttpResponseForbidden("当前状态或身份无法打回该需求。")
    ticket_service.send_back_requirement(actor=request.user, requirement=requirement)
    messages.warning(request, f"需求「{requirement.title}」已打回，后端将重新处理。")
    return redirect(ticket.get_absolute_url() + "#req-" + str(req_pk))


@login_required
@require_POST
def requirement_attachment_upload(request, pk, req_pk):
    """后端处理人为单条需求上传交付结果。"""
    ticket = _get_ticket_or_403(request.user, pk)
    requirement = get_object_or_404(Requirement, pk=req_pk, ticket=ticket)
    if not can_upload_deliverable(request.user, ticket):
        return HttpResponseForbidden("无权为该需求上传交付结果。")
    form = AttachmentForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "上传失败：%s" % form.errors.as_text())
        return redirect(ticket.get_absolute_url())
    f = form.cleaned_data["file"]
    att = TicketAttachment.objects.create(
        ticket=ticket,
        requirement=requirement,
        kind=TicketAttachment.Kind.DELIVERABLE,
        file=f,
        original_name=getattr(f, "name", "") or "",
        size=getattr(f, "size", 0) or 0,
        uploaded_by=request.user,
    )
    from .models import TicketEvent
    TicketEvent.objects.create(
        ticket=ticket,
        actor=request.user,
        kind=TicketEvent.Kind.ATTACHED,
        message=f"上传需求「{requirement.title}」交付结果：{att.original_name}",
    )
    messages.success(request, f"需求「{requirement.title}」的交付结果已上传。")
    return redirect(ticket.get_absolute_url() + "#req-" + str(req_pk))


@login_required
def attachment_download(request, pk, att_pk):
    ticket = _get_ticket_or_403(request.user, pk)
    att = get_object_or_404(TicketAttachment, pk=att_pk, ticket=ticket)
    if not att.file:
        raise Http404()
    return FileResponse(
        att.file.open("rb"),
        as_attachment=True,
        filename=att.original_name or att.file.name.rsplit("/", 1)[-1],
    )


@login_required
def home(request):
    """工作台首页：我的待办、我提交的进行中、超期预警、最近通知。"""
    user = request.user
    active = [Ticket.Status.IN_PROGRESS, Ticket.Status.PENDING_FEEDBACK]
    base = Ticket.objects.select_related("created_by", "assigned_to").prefetch_related("requirements")

    my_todo = base.filter(assigned_to=user, status=Ticket.Status.IN_PROGRESS)

    # 待我确认：我创建的、未关闭、且至少有一条需求处于「后端已完成」等待我接收/打回
    my_review = (
        base.filter(created_by=user)
        .exclude(status=Ticket.Status.CLOSED)
        .annotate(
            pending_review_count=Count(
                "requirements",
                filter=Q(requirements__status=Requirement.Status.DONE),
                distinct=True,
            ),
            total_req_count=Count("requirements", distinct=True),
        )
        .filter(pending_review_count__gt=0)
    )

    # 等待我关闭：我创建的、未关闭、所有需求条目都已被前端确认（无论工单状态是 IN_PROGRESS 还是 PENDING_FEEDBACK）
    my_to_close = (
        base.filter(created_by=user, status__in=active)
        .annotate(
            total_req_count=Count("requirements", distinct=True),
            unaccepted_count=Count(
                "requirements",
                filter=~Q(requirements__status=Requirement.Status.ACCEPTED),
                distinct=True,
            ),
        )
        .filter(total_req_count__gt=0, unaccepted_count=0)
    )

    # 我提交的进行中：排除「所有需求条目都已被前端确认」的工单（这些已经在"等待我关闭"里）
    my_created_active = (
        base.filter(created_by=user, status__in=active)
        .annotate(
            unconfirmed_req_count=Count(
                "requirements",
                filter=~Q(requirements__status=Requirement.Status.ACCEPTED),
                distinct=True,
            ),
        )
        .filter(unconfirmed_req_count__gt=0)
    )

    cutoff = timezone.now() - timedelta(days=OVERDUE_DAYS)
    overdue_reqs = (
        Requirement.objects.select_related("ticket")
        .filter(
            status__in=[Requirement.Status.PENDING, Requirement.Status.DOING],
            created_at__lt=cutoff,
        )
    )
    if not is_manager(user):
        overdue_reqs = overdue_reqs.filter(
            Q(ticket__assigned_to=user) | Q(ticket__created_by=user)
        ).distinct()
    overdue_reqs = overdue_reqs.order_by("created_at")[:20]

    recent_notifs = user.notifications.select_related("ticket").all()[:10]

    return render(
        request,
        "tickets/home.html",
        {
            "my_todo": my_todo,
            "my_review": my_review,
            "my_to_close": my_to_close,
            "my_created_active": my_created_active,
            "overdue_reqs": overdue_reqs,
            "recent_notifs": recent_notifs,
        },
    )


@login_required
def notification_list(request):
    qs = request.user.notifications.select_related("ticket")
    if request.GET.get("unread") == "1":
        qs = qs.filter(is_read=False)
    return render(request, "tickets/notifications.html", {"notifications": qs[:200]})


@login_required
@require_POST
def notification_mark_read(request, pk):
    notif = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notif.is_read = True
    notif.save(update_fields=["is_read"])
    if notif.url:
        return redirect(notif.url)
    return redirect("tickets:notifications")


@login_required
@require_POST
def notification_mark_all_read(request):
    request.user.notifications.filter(is_read=False).update(is_read=True)
    messages.success(request, "已将所有通知标记为已读。")
    return redirect("tickets:notifications")


@login_required
def stats_page(request):
    """管理员统计页：按后端人员 + 按月 + 全局指标。"""
    if not is_manager(request.user):
        return HttpResponseForbidden("仅管理员可查看统计。")

    from collections import defaultdict

    from django.contrib.auth import get_user_model
    from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F
    from django.db.models.functions import TruncMonth

    from .permissions import GROUP_BACKEND

    User = get_user_model()

    active_statuses = [Ticket.Status.IN_PROGRESS, Ticket.Status.PENDING_FEEDBACK]

    backends = list(
        User.objects.filter(groups__name=GROUP_BACKEND)
        .annotate(
            total_assigned=Count("tickets_assigned", distinct=True),
            active_count=Count(
                "tickets_assigned",
                filter=Q(tickets_assigned__status__in=active_statuses),
                distinct=True,
            ),
            closed_count=Count(
                "tickets_assigned",
                filter=Q(tickets_assigned__status=Ticket.Status.CLOSED),
                distinct=True,
            ),
        )
        .order_by("username")
    )

    # 当前负载按难度细分：在"处理中"工单下、状态为 待处理/处理中 的需求条数
    unfinished_req_statuses = [Requirement.Status.PENDING, Requirement.Status.DOING]
    diff_rows = (
        Requirement.objects.filter(
            status__in=unfinished_req_statuses,
            ticket__status=Ticket.Status.IN_PROGRESS,
            ticket__assigned_to__isnull=False,
        )
        .values("ticket__assigned_to_id", "difficulty")
        .annotate(cnt=Count("id"))
    )
    diff_map = defaultdict(lambda: {
        Requirement.Difficulty.LOW: 0,
        Requirement.Difficulty.MEDIUM: 0,
        Requirement.Difficulty.HIGH: 0,
    })
    for row in diff_rows:
        diff_map[row["ticket__assigned_to_id"]][row["difficulty"]] = row["cnt"]
    from .services.assignment import DIFFICULTY_WEIGHT

    for b in backends:
        buckets = diff_map[b.id]
        b.load_low = buckets[Requirement.Difficulty.LOW]
        b.load_medium = buckets[Requirement.Difficulty.MEDIUM]
        b.load_high = buckets[Requirement.Difficulty.HIGH]
        b.load_total = b.load_low + b.load_medium + b.load_high
        b.load_weighted = (
            b.load_low * DIFFICULTY_WEIGHT[Requirement.Difficulty.LOW]
            + b.load_medium * DIFFICULTY_WEIGHT[Requirement.Difficulty.MEDIUM]
            + b.load_high * DIFFICULTY_WEIGHT[Requirement.Difficulty.HIGH]
        )

    closed_qs = Ticket.objects.filter(
        status=Ticket.Status.CLOSED,
        assigned_at__isnull=False,
        closed_at__isnull=False,
    ).annotate(
        handle_duration=ExpressionWrapper(
            F("closed_at") - F("assigned_at"), output_field=DurationField()
        )
    )

    global_avg = closed_qs.aggregate(avg=Avg("handle_duration"))["avg"]

    per_backend_avg = []
    for u in backends:
        avg = closed_qs.filter(assigned_to=u).aggregate(avg=Avg("handle_duration"))["avg"]
        per_backend_avg.append({"user": u, "avg": avg})

    monthly = (
        closed_qs
        .annotate(month=TruncMonth("closed_at"))
        .values("month", "assigned_to__username")
        .annotate(cnt=Count("id"))
        .order_by("-month", "assigned_to__username")
    )
    monthly_rows = list(monthly[:60])

    total_reqs = Requirement.objects.count()
    overdue_reqs = Requirement.objects.filter(
        status__in=[Requirement.Status.PENDING, Requirement.Status.DOING],
        created_at__lt=timezone.now() - timedelta(days=OVERDUE_DAYS),
    ).count()
    in_flight_reqs = Requirement.objects.filter(
        status__in=[Requirement.Status.PENDING, Requirement.Status.DOING],
    ).count()
    overdue_rate = (overdue_reqs / in_flight_reqs * 100) if in_flight_reqs else 0

    return render(
        request,
        "tickets/stats.html",
        {
            "backends": backends,
            "per_backend_avg": per_backend_avg,
            "global_avg": global_avg,
            "monthly_rows": monthly_rows,
            "total_reqs": total_reqs,
            "overdue_reqs": overdue_reqs,
            "in_flight_reqs": in_flight_reqs,
            "overdue_rate": overdue_rate,
        },
    )


def _project_visible_filter(user):
    """返回作用于 Ticket 表的 Q：限定用户能看到的工单（manager 看全部）。"""
    if is_manager(user):
        return Q()
    return Q(created_by=user) | Q(assigned_to=user)


@login_required
def project_archive_list(request):
    """项目归档列表：按 project_no 聚合。"""
    user = request.user
    visible = _project_visible_filter(user)

    q = (request.GET.get("q") or "").strip()
    scope = request.GET.get("scope") or ""  # "active" | "closed" | ""

    base = Ticket.objects.filter(visible)
    if q:
        base = base.filter(
            Q(project_no__icontains=q)
            | Q(project_name__icontains=q)
            | Q(client_name__icontains=q)
        )

    # 先按 project_no 聚合统计
    rows = (
        base.values("project_no")
        .annotate(
            ticket_count=Count("id", distinct=True),
            req_total=Count("requirements", distinct=True),
            req_accepted=Count(
                "requirements",
                filter=Q(requirements__status=Requirement.Status.ACCEPTED),
                distinct=True,
            ),
            active_ticket_count=Count(
                "id",
                filter=~Q(status=Ticket.Status.CLOSED),
                distinct=True,
            ),
            last_activity=Max("updated_at"),
        )
        .order_by("-last_activity")
    )

    if scope == "active":
        rows = rows.filter(active_ticket_count__gt=0)
    elif scope == "closed":
        rows = rows.filter(active_ticket_count=0)

    rows = list(rows)

    # 取每个项目"最新一条工单"的项目名 / 客户名作为展示
    project_nos = [r["project_no"] for r in rows]
    if project_nos:
        latest_meta = {}
        for t in (
            Ticket.objects.filter(project_no__in=project_nos)
            .order_by("project_no", "-created_at")
            .values("project_no", "project_name", "client_name")
        ):
            latest_meta.setdefault(
                t["project_no"],
                {"project_name": t["project_name"], "client_name": t["client_name"]},
            )
        for r in rows:
            meta = latest_meta.get(r["project_no"], {})
            r["project_name"] = meta.get("project_name", "")
            r["client_name"] = meta.get("client_name", "")

    return render(
        request,
        "tickets/project_list.html",
        {
            "rows": rows,
            "q": q,
            "scope": scope,
        },
    )


@login_required
def project_archive_detail(request, project_no):
    """单个项目的归档视图：跨工单聚合所有需求条目。"""
    user = request.user
    visible = _project_visible_filter(user)

    tickets = list(
        Ticket.objects.filter(visible, project_no=project_no)
        .select_related("created_by", "assigned_to")
        .order_by("created_at")
    )
    if not tickets:
        raise Http404("无可见的该项目工单")

    # 取最新一条工单的展示元数据
    latest = tickets[-1]
    project_name = latest.project_name
    client_name = latest.client_name

    name_variants = sorted({t.project_name for t in tickets if t.project_name})
    client_variants = sorted({t.client_name for t in tickets if t.client_name})

    requirements = list(
        Requirement.objects.filter(ticket__in=tickets)
        .select_related("ticket")
        .order_by("-created_at")
    )

    total_reqs = len(requirements)
    accepted_reqs = sum(1 for r in requirements if r.status == Requirement.Status.ACCEPTED)
    done_reqs = sum(1 for r in requirements if r.status == Requirement.Status.DONE)
    inflight_reqs = sum(
        1 for r in requirements
        if r.status in (Requirement.Status.PENDING, Requirement.Status.DOING, Requirement.Status.REJECTED)
    )

    active_tickets = [t for t in tickets if t.status != Ticket.Status.CLOSED]
    closed_tickets = [t for t in tickets if t.status == Ticket.Status.CLOSED]

    return render(
        request,
        "tickets/project_detail.html",
        {
            "project_no": project_no,
            "project_name": project_name,
            "client_name": client_name,
            "name_variants": name_variants,
            "client_variants": client_variants,
            "tickets": tickets,
            "active_tickets": active_tickets,
            "closed_tickets": closed_tickets,
            "requirements": requirements,
            "total_reqs": total_reqs,
            "accepted_reqs": accepted_reqs,
            "done_reqs": done_reqs,
            "inflight_reqs": inflight_reqs,
            "can_create_more": can_create_ticket(user),
        },
    )
