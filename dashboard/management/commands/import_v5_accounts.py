"""Import accounts from an explicit, read-only v5 database into an empty v6 DB."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from dashboard.services.account_transfer import transfer_accounts


class Command(BaseCommand):
    help = "从明确指定的只读v5数据库导入账号与登录防护"

    def add_arguments(self, parser):
        parser.add_argument("--source", required=True, help="v5数据库文件路径")

    def handle(self, *args, **options):
        try:
            summary = transfer_accounts(Path(options["source"]))
        except ValueError as error:
            raise CommandError(str(error)) from None
        except (DatabaseError, OSError):
            raise CommandError("账号导入失败；请确认v5来源及空v6目标迁移状态") from None
        self.stdout.write(self.style.SUCCESS(
            f"账号导入完成：账号 {summary['users']} 个，登录限制 {summary['login_limits']} 条"
        ))
