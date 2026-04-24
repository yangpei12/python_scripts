from django.contrib import admin

from .models import (
    Notification,
    Requirement,
    Ticket,
    TicketAttachment,
    TicketComment,
    TicketEvent,
)


class RequirementInline(admin.TabularInline):
    model = Requirement
    extra = 0
    fields = ("order", "title", "difficulty", "due_at", "status", "done_at")
    readonly_fields = ("done_at",)


class AttachmentInline(admin.TabularInline):
    model = TicketAttachment
    extra = 0
    readonly_fields = ("original_name", "size", "uploaded_by", "uploaded_at")
    fields = ("kind", "requirement", "file", "original_name", "size", "uploaded_by", "uploaded_at")


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        "project_no",
        "project_name",
        "client_name",
        "status",
        "created_by",
        "assigned_to",
        "created_at",
    )
    list_filter = ("status", "assigned_to")
    search_fields = ("project_no", "project_name", "client_name", "description")
    readonly_fields = (
        "created_at",
        "updated_at",
        "assigned_at",
        "submitted_for_review_at",
        "closed_at",
    )
    inlines = [RequirementInline, AttachmentInline]


@admin.register(Requirement)
class RequirementAdmin(admin.ModelAdmin):
    list_display = ("ticket", "title", "difficulty", "status", "due_at", "done_at")
    list_filter = ("status", "difficulty")
    search_fields = ("title", "detail", "ticket__project_no")


@admin.register(TicketComment)
class TicketCommentAdmin(admin.ModelAdmin):
    list_display = ("ticket", "author", "is_reject_reason", "created_at")
    list_filter = ("is_reject_reason",)
    search_fields = ("body", "ticket__project_no")


@admin.register(TicketEvent)
class TicketEventAdmin(admin.ModelAdmin):
    list_display = ("ticket", "kind", "actor", "created_at")
    list_filter = ("kind",)
    search_fields = ("ticket__project_no", "message")


@admin.register(TicketAttachment)
class TicketAttachmentAdmin(admin.ModelAdmin):
    list_display = ("ticket", "kind", "requirement", "original_name", "size", "uploaded_by", "uploaded_at")
    list_filter = ("kind",)
    search_fields = ("original_name", "ticket__project_no")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "text", "is_read", "created_at")
    list_filter = ("is_read",)
    search_fields = ("text", "recipient__username")
