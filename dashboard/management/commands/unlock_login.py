from django.core.management.base import BaseCommand, CommandError

from dashboard.services.accounts import AccountError, unlock_login


class Command(BaseCommand):
    help = "本机清除账号登录失败计数；不启用账号、不清来源限制"

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)

    def handle(self, *args, **options):
        try:
            unlock_login(None, options["username"])
        except AccountError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(self.style.SUCCESS("账号失败计数已清除"))
