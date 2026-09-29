from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "请使用 reset_admin_password 重置管理员密码"

    def handle(self, *args, **options):
        raise CommandError("此入口已禁用，请使用 reset_admin_password")
