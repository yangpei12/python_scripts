"""自动分派：在活跃后端中选择当前"加权负载"最小的人。

负载定义：统计该后端名下、工单处于"处理中"、需求状态为"待处理/处理中"
的需求条数，并按难度权重加权求和。

权重：低=1，中=2，高=3（即 1 个高难度 ≈ 3 个低难度）。
平手时按"上次被分派时间最早"优先，再其次按用户 id 稳定排序。
"""

from collections import defaultdict

from django.contrib.auth import get_user_model
from django.db.models import Count, Max

from ..models import Requirement, Ticket
from ..permissions import GROUP_BACKEND

User = get_user_model()

DIFFICULTY_WEIGHT = {
    Requirement.Difficulty.LOW: 1,
    Requirement.Difficulty.MEDIUM: 2,
    Requirement.Difficulty.HIGH: 3,
}


def compute_weighted_load_map():
    """返回 {user_id: weighted_load} 映射。"""
    unfinished = [Requirement.Status.PENDING, Requirement.Status.DOING]
    rows = (
        Requirement.objects.filter(
            status__in=unfinished,
            ticket__status=Ticket.Status.IN_PROGRESS,
            ticket__assigned_to__isnull=False,
        )
        .values("ticket__assigned_to_id", "difficulty")
        .annotate(cnt=Count("id"))
    )
    load = defaultdict(int)
    for row in rows:
        weight = DIFFICULTY_WEIGHT.get(row["difficulty"], 1)
        load[row["ticket__assigned_to_id"]] += weight * row["cnt"]
    return load


def _sort_key(user, load_map):
    load = load_map.get(user.id, 0)
    # last_assigned_at 为 None（从未被分派过）的人最优先 —— 用 -inf 让其排在最前
    la = user.last_assigned_at
    ts = la.timestamp() if la is not None else float("-inf")
    return (load, ts, user.id)


def select_backend(*, project_no: str | None = None):
    """选出加权负载最小的活跃后端；无可用后端时返回 None。

    若给定 project_no 且该项目下存在「未关闭」工单，
    优先沿用其当前处理人（要求其仍是活跃后端），保持同项目衔接。
    若该候选已离职/不再可用，则回退到负载最小者。
    """
    candidates = list(
        User.objects.filter(is_active=True, groups__name=GROUP_BACKEND)
        .annotate(last_assigned_at=Max("tickets_assigned__assigned_at"))
    )
    if not candidates:
        return None

    if project_no:
        existing = (
            Ticket.objects.filter(project_no=project_no, assigned_to__isnull=False)
            .exclude(status=Ticket.Status.CLOSED)
            .order_by("-created_at")
            .values_list("assigned_to_id", flat=True)
            .first()
        )
        if existing is not None:
            for u in candidates:
                if u.id == existing:
                    return u

    load_map = compute_weighted_load_map()
    candidates.sort(key=lambda u: _sort_key(u, load_map))
    return candidates[0]
