from django.core.management.base import BaseCommand

from tickets.permissions import ALL_GROUPS, ensure_groups


class Command(BaseCommand):
    help = "创建工单系统的角色分组：frontend / backend / manager"

    def handle(self, *args, **options):
        ensure_groups()
        self.stdout.write(self.style.SUCCESS("角色已就绪：%s" % ", ".join(ALL_GROUPS)))
        self.stdout.write(
            "下一步：进入 /admin/ 创建 14 个账号，并把他们加入 frontend / backend 分组。"
        )
