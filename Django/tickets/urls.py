from django.urls import path

from . import views

app_name = "tickets"

urlpatterns = [
    path("", views.home, name="home"),
    path("tickets/", views.ticket_list, name="list"),
    path("tickets/new/", views.ticket_create, name="create"),
    path("tickets/<int:pk>/", views.ticket_detail, name="detail"),

    path("tickets/<int:pk>/requirements/<int:req_pk>/done/", views.requirement_done, name="requirement_done"),
    path("tickets/<int:pk>/requirements/<int:req_pk>/reopen/", views.requirement_reopen, name="requirement_reopen"),
    path("tickets/<int:pk>/requirements/<int:req_pk>/accept/", views.requirement_accept, name="requirement_accept"),
    path("tickets/<int:pk>/requirements/<int:req_pk>/send-back/", views.requirement_send_back, name="requirement_send_back"),

    path("tickets/<int:pk>/submit-for-review/", views.ticket_submit_for_review, name="submit_for_review"),
    path("tickets/<int:pk>/close/", views.ticket_close, name="close"),
    path("tickets/<int:pk>/reject/", views.ticket_reject, name="reject"),
    path("tickets/<int:pk>/reopen/", views.ticket_reopen, name="reopen"),

    path("tickets/<int:pk>/comments/", views.comment_create, name="comment_create"),
    path("tickets/<int:pk>/attach/", views.attachment_upload, name="attachment_upload"),
    path("tickets/<int:pk>/requirements/<int:req_pk>/attach/", views.requirement_attachment_upload, name="requirement_attachment_upload"),
    path(
        "tickets/<int:pk>/attachments/<int:att_pk>/download/",
        views.attachment_download,
        name="attachment_download",
    ),

    path("projects/", views.project_archive_list, name="project_list"),
    path("projects/<str:project_no>/", views.project_archive_detail, name="project_detail"),

    path("notifications/", views.notification_list, name="notifications"),
    path("notifications/<int:pk>/read/", views.notification_mark_read, name="notification_read"),
    path("notifications/read-all/", views.notification_mark_all_read, name="notification_read_all"),

    path("stats/", views.stats_page, name="stats"),
]
