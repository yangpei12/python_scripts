from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Notification, Requirement, Ticket, TicketComment, TicketEvent
from .permissions import GROUP_BACKEND, GROUP_FRONTEND, GROUP_MANAGER, ensure_groups
from .services.assignment import select_backend
from .services import tickets as ticket_service


User = get_user_model()


def _mk_user(username, group):
    u = User.objects.create_user(username=username, password="pw12345678")
    u.groups.add(Group.objects.get(name=group))
    return u


def _mk_ticket(creator, project_no="P-001"):
    return Ticket(
        project_no=project_no,
        project_name="测试项目",
        client_name="某客户",
        description="",
    )


def _req_data(title="需求A"):
    return {
        "title": title,
        "detail": "...",
        "difficulty": Requirement.Difficulty.MEDIUM,
        "due_at": timezone.now() + timedelta(days=3),
        "order": 0,
    }


class AssignmentTests(TestCase):
    def setUp(self):
        ensure_groups()
        self.fe = _mk_user("fe1", GROUP_FRONTEND)
        self.b1 = _mk_user("be1", GROUP_BACKEND)
        self.b2 = _mk_user("be2", GROUP_BACKEND)

    def test_picks_least_loaded_backend(self):
        # 给 b1 先分一个活跃工单
        t1 = _mk_ticket(self.fe, "P-001")
        t1.created_by = self.fe
        t1.assigned_to = self.b1
        t1.assigned_at = timezone.now()
        t1.save()

        picked = select_backend()
        self.assertEqual(picked, self.b2)

    def test_inactive_backend_not_picked(self):
        self.b1.is_active = False
        self.b1.save()
        picked = select_backend()
        self.assertEqual(picked, self.b2)

    def test_weighted_by_difficulty(self):
        """1 个高难度(权重 3) 应重于 2 个低难度(权重 2)，被更少权重的后端接单。"""
        # 给 b1 分 1 个高难度需求（权重 3）
        t_b1, _ = ticket_service.create_ticket(
            creator=self.fe,
            ticket=_mk_ticket(self.fe, "P-B1"),
            requirements_data=[
                {
                    "title": "高难度任务",
                    "detail": "",
                    "difficulty": Requirement.Difficulty.HIGH,
                    "due_at": timezone.now() + timedelta(days=3),
                    "order": 0,
                }
            ],
        )
        # b1 应被选中（此前两人均无负载，b1 先接）
        self.assertEqual(t_b1.assigned_to, self.b1)

        # 此时 b1 负载 = 3（1 高），b2 负载 = 0 → 下一张必然给 b2
        t_next, assignee = ticket_service.create_ticket(
            creator=self.fe,
            ticket=_mk_ticket(self.fe, "P-B2"),
            requirements_data=[
                {
                    "title": "低1",
                    "detail": "",
                    "difficulty": Requirement.Difficulty.LOW,
                    "due_at": timezone.now() + timedelta(days=3),
                    "order": 0,
                },
                {
                    "title": "低2",
                    "detail": "",
                    "difficulty": Requirement.Difficulty.LOW,
                    "due_at": timezone.now() + timedelta(days=3),
                    "order": 1,
                },
            ],
        )
        self.assertEqual(assignee, self.b2)

        # 现在 b1=3, b2=2 → 再来一张低难度(1) 应落在 b2，b2 变 2+1=3，与 b1 打平
        _, a3 = ticket_service.create_ticket(
            creator=self.fe,
            ticket=_mk_ticket(self.fe, "P-B3"),
            requirements_data=[
                {
                    "title": "低C",
                    "detail": "",
                    "difficulty": Requirement.Difficulty.LOW,
                    "due_at": timezone.now() + timedelta(days=3),
                    "order": 0,
                }
            ],
        )
        self.assertEqual(a3, self.b2)

        # 此时 b1=3, b2=3 → 打平，按"上次被分派时间最早" → b1 更早，下一张落 b1
        _, a4 = ticket_service.create_ticket(
            creator=self.fe,
            ticket=_mk_ticket(self.fe, "P-B4"),
            requirements_data=[
                {
                    "title": "低D",
                    "detail": "",
                    "difficulty": Requirement.Difficulty.LOW,
                    "due_at": timezone.now() + timedelta(days=3),
                    "order": 0,
                }
            ],
        )
        self.assertEqual(a4, self.b1)


class TicketFlowTests(TestCase):
    def setUp(self):
        ensure_groups()
        self.fe = _mk_user("fe1", GROUP_FRONTEND)
        self.be = _mk_user("be1", GROUP_BACKEND)

    def _create(self):
        t, assignee = ticket_service.create_ticket(
            creator=self.fe,
            ticket=_mk_ticket(self.fe),
            requirements_data=[_req_data("需求A"), _req_data("需求B")],
        )
        return t, assignee

    def test_create_auto_assigns_and_notifies(self):
        t, assignee = self._create()
        self.assertEqual(assignee, self.be)
        self.assertEqual(t.status, Ticket.Status.IN_PROGRESS)
        self.assertEqual(t.assigned_to, self.be)
        self.assertEqual(t.requirements.count(), 2)
        self.assertTrue(
            Notification.objects.filter(recipient=self.be, ticket=t).exists()
        )
        self.assertTrue(
            TicketEvent.objects.filter(ticket=t, kind=TicketEvent.Kind.SUBMITTED).exists()
        )

    def test_full_happy_path(self):
        t, _ = self._create()
        for r in t.requirements.all():
            ticket_service.mark_requirement_done(actor=self.be, requirement=r)
        ticket_service.submit_for_review(actor=self.be, ticket=t)
        t.refresh_from_db()
        self.assertEqual(t.status, Ticket.Status.PENDING_FEEDBACK)
        self.assertTrue(
            Notification.objects.filter(recipient=self.fe, ticket=t).exists()
        )

        ticket_service.close_ticket(actor=self.fe, ticket=t)
        t.refresh_from_db()
        self.assertEqual(t.status, Ticket.Status.CLOSED)
        self.assertIsNotNone(t.closed_at)

    def test_reject_flow_resets_done_requirements(self):
        t, _ = self._create()
        for r in t.requirements.all():
            ticket_service.mark_requirement_done(actor=self.be, requirement=r)
        ticket_service.submit_for_review(actor=self.be, ticket=t)

        ticket_service.reject_ticket(actor=self.fe, ticket=t, reason="结果有误")
        t.refresh_from_db()
        self.assertEqual(t.status, Ticket.Status.IN_PROGRESS)
        # 之前 done 的需求被重置
        self.assertFalse(
            t.requirements.filter(status=Requirement.Status.DONE).exists()
        )
        # 打回原因被写入评论
        self.assertTrue(
            TicketComment.objects.filter(ticket=t, is_reject_reason=True).exists()
        )

    def test_reopen_closed_ticket(self):
        t, _ = self._create()
        for r in t.requirements.all():
            ticket_service.mark_requirement_done(actor=self.be, requirement=r)
        ticket_service.submit_for_review(actor=self.be, ticket=t)
        ticket_service.close_ticket(actor=self.fe, ticket=t)

        ticket_service.reopen_ticket(actor=self.fe, ticket=t)
        t.refresh_from_db()
        self.assertEqual(t.status, Ticket.Status.IN_PROGRESS)
        self.assertIsNone(t.closed_at)


class PermissionTests(TestCase):
    def setUp(self):
        ensure_groups()
        self.fe = _mk_user("fe1", GROUP_FRONTEND)
        self.fe2 = _mk_user("fe2", GROUP_FRONTEND)
        self.be = _mk_user("be1", GROUP_BACKEND)
        self.t, _ = ticket_service.create_ticket(
            creator=self.fe,
            ticket=_mk_ticket(self.fe),
            requirements_data=[_req_data("需求A")],
        )

    def test_other_frontend_cannot_view(self):
        self.client.force_login(self.fe2)
        resp = self.client.get(reverse("tickets:detail", args=[self.t.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_backend_cannot_reject_or_close(self):
        # 先让后端提交待确认
        r = self.t.requirements.first()
        ticket_service.mark_requirement_done(actor=self.be, requirement=r)
        ticket_service.submit_for_review(actor=self.be, ticket=self.t)

        self.client.force_login(self.be)
        resp = self.client.post(reverse("tickets:close", args=[self.t.pk]))
        self.assertEqual(resp.status_code, 403)
        resp = self.client.post(
            reverse("tickets:reject", args=[self.t.pk]), {"reason": "不行"}
        )
        self.assertEqual(resp.status_code, 403)

    def test_stats_requires_manager(self):
        self.client.force_login(self.fe)
        resp = self.client.get(reverse("tickets:stats"))
        self.assertEqual(resp.status_code, 403)

        mgr = _mk_user("mgr", GROUP_MANAGER)
        self.client.force_login(mgr)
        resp = self.client.get(reverse("tickets:stats"))
        self.assertEqual(resp.status_code, 200)


class OverdueTests(TestCase):
    def setUp(self):
        ensure_groups()
        self.fe = _mk_user("fe1", GROUP_FRONTEND)
        self.be = _mk_user("be1", GROUP_BACKEND)

    def test_overdue_when_created_over_2_days(self):
        t, _ = ticket_service.create_ticket(
            creator=self.fe,
            ticket=_mk_ticket(self.fe),
            requirements_data=[_req_data("需求A")],
        )
        r = t.requirements.first()
        # 人工回拨创建时间
        Requirement.objects.filter(pk=r.pk).update(
            created_at=timezone.now() - timedelta(days=3)
        )
        r.refresh_from_db()
        self.assertTrue(r.is_overdue)
        self.assertTrue(t.has_overdue_requirement)

    def test_not_overdue_when_done(self):
        t, _ = ticket_service.create_ticket(
            creator=self.fe,
            ticket=_mk_ticket(self.fe),
            requirements_data=[_req_data("需求A")],
        )
        r = t.requirements.first()
        Requirement.objects.filter(pk=r.pk).update(
            created_at=timezone.now() - timedelta(days=3)
        )
        ticket_service.mark_requirement_done(actor=self.be, requirement=r)
        r.refresh_from_db()
        self.assertFalse(r.is_overdue)
