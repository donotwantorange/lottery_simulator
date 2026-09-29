"""Pool access, mutation, import, and export rules."""

from copy import deepcopy
from uuid import uuid4

from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Q
from django.utils import timezone

from dashboard.models import ExperimentConfig, Pool, User
from dashboard.services.accounts import AccountError
from lottery_simulator.config_documents import load_pool_document, normalize_name


class PoolError(ValueError):
    """A pool operation failed for a user-correctable reason."""

    def __init__(self, message, *, status=400, code="validation_error"):
        super().__init__(message)
        self.status = status
        self.code = code


def _actor(actor, *, expected_auth_version=None):
    if actor is None or not getattr(actor, "is_authenticated", False):
        raise AccountError("请重新登录")
    if expected_auth_version is None:
        expected_auth_version = getattr(actor, "auth_version", None)
    try:
        fresh = User.objects.get(pk=actor.pk)
    except User.DoesNotExist:
        raise AccountError("请重新登录") from None
    if (not fresh.is_active or fresh.deleting or fresh.must_change_password
            or fresh.auth_version != expected_auth_version):
        raise AccountError("请重新登录")
    return fresh


def _pool_name(value):
    name = normalize_name(value, "池名称")
    if len(name) > 255:
        raise PoolError("池名称最长255字符")
    return name, name


def _document(payload):
    try:
        document = load_pool_document(payload)
    except (TypeError, ValueError) as error:
        raise PoolError(str(error)) from error
    if document.original_author is not None and len(document.original_author) > 255:
        raise PoolError("最初作者署名最长255字符")
    return document


def visible_pools(actor):
    """Return pools the current database actor may view and use."""
    actor = _actor(actor)
    pools = Pool.objects.all()
    if actor.is_superuser:
        return pools
    return pools.filter(
        Q(kind=Pool.PUBLIC) | Q(kind=Pool.PRIVATE, visibility=Pool.PUBLIC) |
        Q(kind=Pool.PRIVATE, owner_id=actor.pk)
    ).distinct()


def _can_edit(actor, pool):
    return actor.is_superuser or (pool.kind == Pool.PRIVATE and pool.owner_id == actor.pk)


def _revision(value):
    if type(value) is not int or value < 1:
        raise PoolError("expected_revision必须是正整数")
    return value


def save_pool(actor, payload: dict, *, pool_id=None, expected_revision=None) -> Pool:
    """Create a private pool or revision-guarded edit an authorized pool."""
    expected_auth_version = getattr(actor, "auth_version", None)
    actor = _actor(actor, expected_auth_version=expected_auth_version)
    if not isinstance(payload, dict):
        raise PoolError("池配置必须是对象")
    controls = {key: payload[key] for key in ("kind", "visibility") if key in payload}
    raw = {key: value for key, value in payload.items()
           if key not in {"kind", "visibility", "revision", "expected_revision"}}
    doc = _document(raw)
    name, name_key = _pool_name(doc.name)
    requested_kind = controls.get("kind")
    requested_visibility = controls.get("visibility")
    kind = requested_kind if requested_kind is not None else Pool.PRIVATE
    visibility = requested_visibility if requested_visibility is not None else Pool.HIDDEN
    if kind not in (Pool.PUBLIC, Pool.PRIVATE):
        raise PoolError("池类型无效")
    if visibility not in (Pool.PUBLIC, Pool.HIDDEN):
        raise PoolError("池可见性无效")
    if kind == Pool.PUBLIC and not actor.is_superuser:
        raise PoolError("仅管理员可以创建公共池", status=403, code="forbidden")
    if kind == Pool.PUBLIC:
        visibility = Pool.PUBLIC

    config = {**deepcopy(doc.pool_config), "format_version": doc.format_version,
              "rarity_labels": deepcopy(doc.rarity_labels)}
    if pool_id is None:
        try:
            with transaction.atomic():
                actor = _actor(actor, expected_auth_version=expected_auth_version)
                if kind == Pool.PUBLIC and not actor.is_superuser:
                    raise PoolError("仅管理员可以创建公共池", status=403, code="forbidden")
                pool = Pool(
                    id=uuid4(), name=name, name_key=name_key, kind=kind,
                    owner=None if kind == Pool.PUBLIC else actor,
                    visibility=visibility,
                    original_author=doc.original_author or actor.username,
                    rule_name=doc.rule_name, config_json=config, revision=1,
                )
                pool.save(force_insert=True)
                return pool
        except IntegrityError as error:
            raise PoolError("同类型角色池已使用该名称") from error
        except OperationalError as error:
            if "locked" in str(error).lower() or "busy" in str(error).lower():
                raise PoolError("存储暂忙，请稍后重试", status=503, code="storage_busy") from error
            raise

    expected_revision = _revision(expected_revision)
    try:
        with transaction.atomic():
            actor = _actor(actor, expected_auth_version=expected_auth_version)
            pool = Pool.objects.get(pk=pool_id)
            if not _can_edit(actor, pool):
                raise PoolError("角色池不存在或无权修改", status=404, code="not_found")
            if requested_kind is not None and requested_kind != pool.kind:
                raise PoolError("池类型转换必须复制为新池")
            kind = pool.kind
            visibility = (requested_visibility if requested_visibility is not None
                          else pool.visibility)
            changed = Pool.objects.filter(pk=pool.pk, revision=expected_revision).update(
                name=name, name_key=name_key, visibility=(
                    Pool.PUBLIC if pool.kind == Pool.PUBLIC else visibility
                ), rule_name=doc.rule_name, config_json=config,
                revision=expected_revision + 1, updated_at=timezone.now(),
            )
            if not changed:
                raise PoolError("角色池内容已变化，请重新加载后确认", status=409,
                                code="revision_conflict")
            return Pool.objects.get(pk=pool.pk)
    except Pool.DoesNotExist:
        raise PoolError("角色池不存在或无权修改", status=404, code="not_found") from None
    except IntegrityError as error:
        raise PoolError("同类型角色池已使用该名称") from error
    except OperationalError as error:
        if "locked" in str(error).lower() or "busy" in str(error).lower():
            raise PoolError("存储暂忙，请稍后重试", status=503, code="storage_busy") from error
        raise


def copy_pool(actor, pool_id, *, name: str, kind: str) -> Pool:
    """Copy a visible pool to a new, hidden private or public pool."""
    expected_auth_version = getattr(actor, "auth_version", None)
    actor = _actor(actor, expected_auth_version=expected_auth_version)
    if kind not in (Pool.PUBLIC, Pool.PRIVATE):
        raise PoolError("池类型无效")
    if kind == Pool.PUBLIC and not actor.is_superuser:
        raise PoolError("仅管理员可以创建公共池", status=403, code="forbidden")
    name, name_key = _pool_name(name)
    try:
        with transaction.atomic():
            actor = _actor(actor, expected_auth_version=expected_auth_version)
            if kind == Pool.PUBLIC and not actor.is_superuser:
                raise PoolError("仅管理员可以创建公共池", status=403, code="forbidden")
            try:
                source = visible_pools(actor).get(pk=pool_id)
            except (Pool.DoesNotExist, ValueError):
                raise PoolError("角色池不存在或不可访问", status=404, code="not_found") from None
            clone = Pool(
                id=uuid4(), name=name, name_key=name_key, kind=kind,
                owner=None if kind == Pool.PUBLIC else actor,
                visibility=Pool.PUBLIC if kind == Pool.PUBLIC else Pool.HIDDEN,
                original_author=source.original_author, rule_name=source.rule_name,
                config_json=deepcopy(source.config_json), revision=1,
            )
            clone.save(force_insert=True)
    except IntegrityError as error:
        raise PoolError("同类型角色池已使用该名称") from error
    except OperationalError as error:
        if "locked" in str(error).lower() or "busy" in str(error).lower():
            raise PoolError("存储暂忙，请稍后重试", status=503, code="storage_busy") from error
        raise
    return clone


def delete_pool(actor, pool_id, *, expected_revision):
    expected_auth_version = getattr(actor, "auth_version", None)
    actor = _actor(actor, expected_auth_version=expected_auth_version)
    expected_revision = _revision(expected_revision)
    try:
        with transaction.atomic():
            actor = _actor(actor, expected_auth_version=expected_auth_version)
            pool = Pool.objects.get(pk=pool_id)
            if not _can_edit(actor, pool):
                raise PoolError("角色池不存在或无权删除", status=404, code="not_found")
            if pool.revision != expected_revision:
                raise PoolError("角色池内容已变化，请重新加载后确认", status=409,
                                code="revision_conflict")
            ExperimentConfig.objects.filter(pool=pool).update(pool=None, pool_name_hint=pool.name)
            pool.delete()
    except Pool.DoesNotExist:
        raise PoolError("角色池不存在或无权删除", status=404, code="not_found") from None
    except OperationalError as error:
        if "locked" in str(error).lower() or "busy" in str(error).lower():
            raise PoolError("存储暂忙，请稍后重试", status=503, code="storage_busy") from error
        raise


def pool_document(pool):
    return {
        "format_version": pool.config_json.get("format_version", 2),
        "id": str(pool.pk),
        "name": pool.name,
        "original_author": pool.original_author,
        "rule_name": pool.rule_name,
        "rarity_labels": pool.config_json.get("rarity_labels", {}),
        "pool_config": {key: value for key, value in pool.config_json.items()
                        if key not in {"format_version", "rarity_labels"}},
    }


def export_pool(actor, pool_id, *, expected_revision):
    actor = _actor(actor)
    expected_revision = _revision(expected_revision)
    try:
        pool = visible_pools(actor).get(pk=pool_id)
    except (Pool.DoesNotExist, ValueError):
        raise PoolError("角色池不存在或不可访问", status=404, code="not_found") from None
    if pool.revision != expected_revision:
        raise PoolError("角色池内容已变化，请重新加载后确认", status=409,
                        code="revision_conflict")
    return pool_document(pool)
