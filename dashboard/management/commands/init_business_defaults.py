"""Create the fixed public rule and pool without overwriting either."""

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.recorder import MigrationRecorder

from dashboard.models import AppMeta, Pool, Rule, User
from lottery_simulator.config_documents import (
    DEFAULT_POOL_PATH, DEFAULT_RULE_PATH, load_pool_document, load_rule_document,
    read_config_json,
)
from lottery_simulator.rules.runtime import compile_pool


def initialize_business_defaults():
    rule_doc = load_rule_document(read_config_json(DEFAULT_RULE_PATH))
    pool_doc = load_pool_document(read_config_json(DEFAULT_POOL_PATH))
    if pool_doc.rule_ref != {"id": rule_doc.id, "name": rule_doc.name}:
        raise CommandError("默认角色池引用与默认规则不一致")
    rule_data, pool_data = rule_doc.to_dict(), pool_doc.to_dict()
    with transaction.atomic():
        if not User.objects.filter(is_active=True, is_superuser=True, deleting=False).exists():
            raise CommandError("请先创建可用管理员")
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA user_version")
            if cursor.fetchone()[0] != 6:
                raise CommandError("请先完整迁移到数据库版本6")
        if not MigrationRecorder(connection).migration_qs.filter(
            app="dashboard", name="0002_independent_rules_v6"
        ).exists():
            raise CommandError("请先完整迁移到数据库版本6")
        name_conflicts = (Rule.objects.filter(kind=Rule.PUBLIC, name_key=rule_doc.name)
                          .exclude(pk=rule_doc.id).exists() or
                          Pool.objects.filter(kind=Pool.PUBLIC, name_key=pool_doc.name)
                          .exclude(pk=pool_doc.id).exists())
        if name_conflicts:
            raise CommandError("默认资源名称已被其他ID占用")
        rule, created = Rule.objects.get_or_create(
            pk=rule_doc.id,
            defaults={"name": rule_doc.name, "name_key": rule_doc.name,
                      "kind": Rule.PUBLIC, "owner": None, "visibility": Rule.PUBLIC,
                      "original_author": rule_doc.original_author or "项目默认配置",
                      "algorithm": rule_doc.algorithm, "config_json": rule_data, "revision": 1},
        )
        if rule.kind != Rule.PUBLIC or rule.owner_id is not None:
            raise CommandError("默认规则ID不是公共规则")
        pool = Pool.objects.filter(pk=pool_doc.id).first()
        if pool is None:
            from lottery_simulator.rules.definitions import RuleDefinition
            current_rule = rule_doc if created else RuleDefinition.from_dict(rule.config_json)
            compile_pool(current_rule, pool_doc)
            pool = Pool.objects.create(
                id=pool_doc.id, name=pool_doc.name, name_key=pool_doc.name,
                kind=Pool.PUBLIC, owner=None, visibility=Pool.PUBLIC,
                original_author=pool_doc.original_author or "项目默认配置",
                rule=rule, config_json=pool_data, revision=1,
            )
        if pool.kind != Pool.PUBLIC or pool.owner_id is not None:
            raise CommandError("默认池ID不是公共池")
        AppMeta.objects.update_or_create(key="initialized", defaults={"value": {"version": 6}})


class Command(BaseCommand):
    help = "使用固定默认配置创建公共规则和角色池（须先运行migrate）"

    def handle(self, *args, **options):
        if not {"users", "rules", "pools", "app_meta", "django_migrations"}.issubset(
            connection.introspection.table_names()
        ):
            raise CommandError("请先运行 migrate")
        try:
            initialize_business_defaults()
        except (IntegrityError, ValueError) as error:
            raise CommandError("默认资源与现有数据冲突，未覆盖任何资源") from error
        self.stdout.write(self.style.SUCCESS("默认公共规则和角色池已就绪"))
