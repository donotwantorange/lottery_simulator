"""Create the first administrator and default public pool exactly once."""

from getpass import getpass

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from dashboard.models import AppMeta, Pool, User
from dashboard.services.accounts import AccountError, create_account, validate_password
from lottery_simulator.config_documents import DEFAULT_POOL_PATH, load_pool_document, read_config_json


class Command(BaseCommand):
    help = "交互式创建首个管理员和默认公共角色池（须先运行migrate）"

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True, help="首个管理员用户名")

    def handle(self, *args, **options):
        if not {"users", "pools", "app_meta", "django_session"}.issubset(
            connection.introspection.table_names()
        ):
            raise CommandError("请先运行 migrate")
        if AppMeta.objects.filter(key="initialized").exists() or User.objects.exists() or Pool.objects.exists():
            raise CommandError("已完成初始化，不能重复创建管理员或默认池")
        password = getpass("密码：")
        if password != getpass("再次输入密码："):
            raise CommandError("两次密码不一致")
        try:
            validate_password(password)
            document = load_pool_document(read_config_json(DEFAULT_POOL_PATH))
            with transaction.atomic():
                if AppMeta.objects.filter(key="initialized").exists() or User.objects.exists() or Pool.objects.exists():
                    raise AccountError("已完成初始化")
                create_account(None, options["username"], password,
                               admin=True, must_change_password=False)
                Pool.objects.create(id=document.id, name=document.name,
                    name_key=document.name, kind="public", owner=None,
                    visibility="public", original_author="项目默认配置",
                    rule_name=document.rule_name,
                    config_json={**document.pool_config,
                                 "format_version": document.format_version,
                                 "rarity_labels": document.rarity_labels}, revision=1)
                AppMeta.objects.create(key="initialized", value={"version": 5})
        except (AccountError, ValueError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(self.style.SUCCESS("首个管理员和默认公共池已创建"))
