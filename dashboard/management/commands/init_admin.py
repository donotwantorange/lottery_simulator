"""Create the first administrator and default public rule and pool exactly once."""

from getpass import getpass

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, connection, transaction

from dashboard.models import AppMeta, Pool, Rule, User
from dashboard.services.accounts import AccountError, create_account, validate_password
from dashboard.management.commands.init_business_defaults import initialize_business_defaults


class Command(BaseCommand):
    help = "交互式创建首个管理员、默认公共规则和角色池（须先运行migrate）"

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True, help="首个管理员用户名")

    def handle(self, *args, **options):
        if not {"users", "rules", "pools", "app_meta", "django_session"}.issubset(
            connection.introspection.table_names()
        ):
            raise CommandError("请先运行 migrate")
        if AppMeta.objects.filter(key="initialized").exists() or User.objects.exists() or Pool.objects.exists() or Rule.objects.exists():
            raise CommandError("已完成初始化，不能重复创建管理员或默认池")
        password = getpass("密码：")
        if password != getpass("再次输入密码："):
            raise CommandError("两次密码不一致")
        try:
            validate_password(password)
            with transaction.atomic():
                if (AppMeta.objects.filter(key="initialized").exists() or User.objects.exists()
                        or Pool.objects.exists() or Rule.objects.exists()):
                    raise AccountError("已完成初始化")
                create_account(None, options["username"], password,
                               admin=True, must_change_password=False)
                initialize_business_defaults()
        except (AccountError, ValueError) as error:
            raise CommandError(str(error)) from error
        except IntegrityError as error:
            raise CommandError("初始化资源冲突，未创建账号或默认业务") from error
        self.stdout.write(self.style.SUCCESS("首个管理员、默认公共规则和角色池已创建"))
