from datetime import timedelta

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


OVERDUE_DAYS = 2


class Ticket(models.Model):
    """工单（项目维度）。一个工单包含若干个需求条目。"""

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "处理中"
        PENDING_FEEDBACK = "pending_feedback", "待前端确认"
        CLOSED = "closed", "已关闭"

    project_no = models.CharField("项目编号", max_length=64, db_index=True)
    project_name = models.CharField("项目名称", max_length=200)
    client_name = models.CharField("客户名称", max_length=200, blank=True)
    description = models.TextField("项目备注", blank=True)
    status = models.CharField(
        "状态",
        max_length=32,
        choices=Status.choices,
        default=Status.IN_PROGRESS,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="提单人",
        on_delete=models.PROTECT,
        related_name="tickets_created",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="当前处理人",
        on_delete=models.PROTECT,
        related_name="tickets_assigned",
        null=True,
        blank=True,
    )
    assigned_at = models.DateTimeField("指派时间", null=True, blank=True)
    submitted_for_review_at = models.DateTimeField("提交待确认时间", null=True, blank=True)
    closed_at = models.DateTimeField("关闭时间", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "工单"
        verbose_name_plural = "工单"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["assigned_to", "status"]),
            models.Index(fields=["project_no"]),
        ]

    def __str__(self):
        return f"{self.project_no} {self.project_name}"

    def get_absolute_url(self):
        return reverse("tickets:detail", kwargs={"pk": self.pk})

    @property
    def is_closed(self) -> bool:
        return self.status == self.Status.CLOSED

    @property
    def is_active(self) -> bool:
        return self.status in (self.Status.IN_PROGRESS, self.Status.PENDING_FEEDBACK)

    @property
    def has_overdue_requirement(self) -> bool:
        return any(r.is_overdue for r in self.requirements.all())


class Requirement(models.Model):
    """工单下的单个需求条目。"""

    class Difficulty(models.TextChoices):
        LOW = "low", "低"
        MEDIUM = "medium", "中"
        HIGH = "high", "高"

    class Status(models.TextChoices):
        PENDING = "pending", "待处理"
        DOING = "doing", "处理中"
        DONE = "done", "后端已完成"
        ACCEPTED = "accepted", "前端已确认"
        REJECTED = "rejected", "被打回"

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="requirements",
        verbose_name="所属工单",
    )
    title = models.CharField("需求标题", max_length=200)
    detail = models.TextField("需求详情", blank=True)
    difficulty = models.CharField(
        "难度",
        max_length=16,
        choices=Difficulty.choices,
        default=Difficulty.MEDIUM,
    )
    due_at = models.DateTimeField("期望完成时间")
    status = models.CharField(
        "状态",
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    order = models.PositiveIntegerField("顺序", default=0)
    done_at = models.DateTimeField("后端完成时间", null=True, blank=True)
    accepted_at = models.DateTimeField("前端确认时间", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "需求条目"
        verbose_name_plural = "需求条目"

    def __str__(self):
        return self.title

    @property
    def is_finished(self) -> bool:
        return self.status in (self.Status.DONE, self.Status.ACCEPTED)

    @property
    def is_overdue(self) -> bool:
        if self.status == self.Status.DONE:
            return False
        return timezone.now() - self.created_at > timedelta(days=OVERDUE_DAYS)


def ticket_attachment_upload_to(instance, filename):
    return f"ticket_attachments/{instance.ticket.project_no}/{filename}"


class TicketAttachment(models.Model):
    """工单附件，区分客户输入资料与交付结果。

    交付结果可关联到具体的需求条目（requirement 非空），实现"每条需求一份交付物"。
    客户输入资料挂在工单级别，requirement 为空。
    """

    class Kind(models.TextChoices):
        INPUT = "input", "客户输入"
        DELIVERABLE = "deliverable", "交付结果"

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name="工单",
    )
    requirement = models.ForeignKey(
        "Requirement",
        on_delete=models.SET_NULL,
        related_name="attachments",
        verbose_name="关联需求",
        null=True,
        blank=True,
    )
    kind = models.CharField("类型", max_length=16, choices=Kind.choices)
    file = models.FileField("文件", upload_to=ticket_attachment_upload_to)
    original_name = models.CharField("原始文件名", max_length=255, blank=True)
    size = models.PositiveBigIntegerField("大小(字节)", default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ticket_attachments",
        verbose_name="上传人",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = "附件"
        verbose_name_plural = "附件"


class TicketComment(models.Model):
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name="工单",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ticket_comments",
        verbose_name="作者",
    )
    body = models.TextField("内容")
    is_reject_reason = models.BooleanField("是否打回原因", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "评论"
        verbose_name_plural = "评论"


class TicketEvent(models.Model):
    """工单时间线/审计记录。"""

    class Kind(models.TextChoices):
        SUBMITTED = "submitted", "创建工单"
        ASSIGNED = "assigned", "分派"
        REQ_DONE = "req_done", "需求完成"
        REQ_ACCEPTED = "req_accepted", "前端确认需求"
        REQ_SENT_BACK = "req_sent_back", "前端打回需求"
        REQ_REOPENED = "req_reopened", "需求重置"
        SENT_FOR_REVIEW = "sent_for_review", "提交待确认"
        REJECTED = "rejected", "前端打回工单"
        CLOSED = "closed", "关闭工单"
        REOPENED = "reopened", "重新打开工单"
        COMMENTED = "commented", "评论"
        ATTACHED = "attached", "上传附件"

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="events",
        verbose_name="工单",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_events",
        verbose_name="操作人",
    )
    kind = models.CharField("类型", max_length=32, choices=Kind.choices)
    message = models.CharField("摘要", max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "事件"
        verbose_name_plural = "事件"


class Notification(models.Model):
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="接收人",
    )
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="关联工单",
        null=True,
        blank=True,
    )
    text = models.CharField("内容", max_length=300)
    url = models.CharField("跳转地址", max_length=300, blank=True)
    is_read = models.BooleanField("已读", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "站内通知"
        verbose_name_plural = "站内通知"
        indexes = [models.Index(fields=["recipient", "is_read"])]
