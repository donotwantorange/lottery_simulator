from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "请使用 init_admin 初始化首个管理员，后续账号在受控页面创建"

    def handle(self, *args, **options):
        raise CommandError("此入口已禁用，请使用 init_admin 或受控管理员页面")
