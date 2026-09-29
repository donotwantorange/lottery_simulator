from getpass import getpass

from django.core.management.base import BaseCommand, CommandError

from dashboard.models import User
from dashboard.services.accounts import AccountError, normalize_username, reset_password, validate_password


class Command(BaseCommand):
    help = "本机重置现有管理员密码；撤销旧会话并要求首次登录改密"

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)

    def handle(self, *args, **options):
        password = getpass("新密码：")
        if password != getpass("再次输入新密码："):
            raise CommandError("两次密码不一致")
        try:
            validate_password(password)
            _, key = normalize_username(options["username"])
            user = User.objects.get(username_key=key)
            reset_password(None, user.pk, password)
        except User.DoesNotExist as error:
            raise CommandError("管理员不存在") from error
        except AccountError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(self.style.SUCCESS("密码已重置，旧会话将失效"))
