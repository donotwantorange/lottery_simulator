"""Rule access and mutation, including the pool-reference boundary."""

from collections.abc import Mapping
from copy import deepcopy
from uuid import uuid4

from django.db import IntegrityError, OperationalError, transaction
from django.db.models.deletion import ProtectedError
from django.db.models import Q
from django.utils import timezone

from dashboard.models import Pool, Rule, User
from lottery_simulator.config_documents import load_pool_document, load_rule_document, normalize_name
from lottery_simulator.rules.runtime import compile_pool


class RuleError(ValueError):
    def __init__(self, message, *, status=400, code="validation_error"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def _actor(actor, *, expected_auth_version=None):
    from dashboard.services.pools import _actor as current_actor
    try:
        return current_actor(actor, expected_auth_version=expected_auth_version)
    except ValueError as error:
        raise RuleError(str(error), status=401, code="unauthenticated") from error


def _editable(actor, rule):
    return actor.is_superuser if rule.kind == Rule.PUBLIC else (
        actor.is_superuser or rule.owner_id == actor.pk
    )


def _can_use(owner, rule):
    if rule.kind == Rule.PUBLIC:
        return True
    return bool(owner and not owner.deleting and (owner.is_superuser or
        rule.owner_id == owner.pk or rule.visibility == Rule.PUBLIC
    ))


def _fresh_owner(owner):
    if owner is None:
        return None
    try:
        return User.objects.get(pk=owner.pk)
    except (AttributeError, User.DoesNotExist):
        return None


def validate_rule_pool_reference(actor, rule, *, pool_owner, pool_kind, pool_visibility,
                                 proposed_visibility=None):
    """Check relationship policy using the pool owner's rights, not the operator's."""
    actor = _actor(actor)
    if pool_kind not in (Pool.PUBLIC, Pool.PRIVATE) or pool_visibility not in (
            Pool.PUBLIC, Pool.HIDDEN):
        raise RuleError("规则不可用于此角色池")
    if (pool_kind == Pool.PUBLIC and (pool_owner is not None or pool_visibility != Pool.PUBLIC)
            or pool_kind == Pool.PRIVATE and pool_owner is None):
        raise RuleError("规则不可用于此角色池")
    pool_owner = _fresh_owner(pool_owner)
    if (pool_kind == Pool.PRIVATE and pool_owner is None
            or pool_owner is not None and pool_owner.deleting):
        raise RuleError("规则不可用于此角色池")
    try:
        rule = Rule.objects.get(pk=rule.pk)
    except (AttributeError, Rule.DoesNotExist):
        raise RuleError("规则不可用于此角色池") from None
    if proposed_visibility is not None:
        if proposed_visibility not in (Rule.PUBLIC, Rule.HIDDEN):
            raise RuleError("规则可见性无效")
        rule.visibility = proposed_visibility
    if rule.kind == Rule.PRIVATE and Rule.objects.filter(
            pk=rule.pk, owner__deleting=True).exists():
        raise RuleError("规则不可用于此角色池")
    allowed = (
        rule.kind == Rule.PUBLIC if pool_kind == Pool.PUBLIC else
        rule.kind == Rule.PUBLIC or (rule.kind == Rule.PRIVATE and
            pool_visibility == Pool.PUBLIC and rule.visibility == Rule.PUBLIC and
            _can_use(pool_owner, rule)) or
        (pool_visibility == Pool.HIDDEN and _can_use(pool_owner, rule))
    )
    if not allowed:
        raise RuleError("规则不可用于此角色池")
    return rule


def visible_rules(actor):
    actor = _actor(actor)
    if actor.is_superuser:
        return Rule.objects.all()
    return Rule.objects.filter(
        Q(kind=Rule.PUBLIC) | Q(kind=Rule.PRIVATE, visibility=Rule.PUBLIC) |
        Q(kind=Rule.PRIVATE, owner_id=actor.pk)
    ).distinct()


def rule_document(rule):
    """Serialize the editable definition without trusting stale JSON metadata."""
    document = load_rule_document(rule.config_json).to_dict()
    document.update(id=str(rule.pk), name=rule.name,
                    original_author=rule.original_author, algorithm=rule.algorithm)
    return document


def _raw_definition(payload):
    if not isinstance(payload, dict):
        raise RuleError("规则配置必须是对象")
    controls = {"kind", "visibility", "revision", "expected_revision", "config"}
    if "config" in payload:
        if set(payload) - (controls | {"name"}):
            raise RuleError("规则修改字段无效")
        raw = payload["config"]
    else:
        raw = {key: value for key, value in payload.items() if key not in controls}
    if not isinstance(raw, dict):
        raise RuleError("规则配置必须是对象")
    raw = deepcopy(raw)
    try:
        doc = load_rule_document(raw)
    except (TypeError, ValueError) as error:
        raise RuleError(str(error)) from error
    try:
        name = normalize_name(payload.get("name", doc.name), "规则名称")
    except (TypeError, ValueError) as error:
        raise RuleError(str(error)) from error
    if len(name) > 255 or (doc.original_author is not None and len(doc.original_author) > 255):
        raise RuleError("规则名称或作者署名过长")
    return doc, name


def _revision(value):
    if type(value) is not int or value < 1:
        raise RuleError("expected_revision必须是正整数")
    return value


def _pool_document(pool):
    raw = deepcopy(pool.config_json)
    raw.setdefault("id", str(pool.pk))
    raw.setdefault("name", pool.name)
    raw.setdefault("original_author", pool.original_author or None)
    return load_pool_document(raw)


def save_rule(actor, payload, rule_id=None, expected_revision=None):
    expected_auth_version = getattr(actor, "auth_version", None)
    actor = _actor(actor, expected_auth_version=expected_auth_version)
    doc, name = _raw_definition(payload)
    requested_kind = payload.get("kind")
    visibility = payload.get("visibility")
    if requested_kind is not None and requested_kind not in (Rule.PUBLIC, Rule.PRIVATE):
        raise RuleError("规则类型无效")
    if visibility is not None and visibility not in (Rule.PUBLIC, Rule.HIDDEN):
        raise RuleError("规则可见性无效")
    if rule_id is None:
        requested_kind = requested_kind or Rule.PRIVATE
    if requested_kind == Rule.PUBLIC:
        if not actor.is_superuser:
            raise RuleError("仅管理员可以创建公共规则", status=403, code="forbidden")
        visibility = Rule.PUBLIC
    raw = doc.to_dict()
    raw.update(id=str(doc.id), name=name)
    if rule_id is None:
        try:
            with transaction.atomic():
                actor = _actor(actor, expected_auth_version=expected_auth_version)
                if requested_kind == Rule.PUBLIC and not actor.is_superuser:
                    raise RuleError("仅管理员可以创建公共规则", status=403, code="forbidden")
                visibility = visibility or Rule.HIDDEN
                rule_id = uuid4()
                author = doc.original_author or actor.username
                raw.update(id=str(rule_id), original_author=author)
                rule = Rule(id=rule_id, name=name, name_key=name, kind=requested_kind,
                            owner=None if requested_kind == Rule.PUBLIC else actor,
                            visibility=visibility, original_author=author,
                            algorithm=doc.algorithm, config_json=raw,
                            revision=1)
                rule.save(force_insert=True)
                return rule
        except IntegrityError as error:
            raise RuleError("同类型规则已使用该名称") from error
        except OperationalError as error:
            if "locked" in str(error).lower() or "busy" in str(error).lower():
                raise RuleError("存储暂忙，请稍后重试", status=503,
                                code="storage_busy") from error
            raise
    expected_revision = _revision(expected_revision)
    try:
        with transaction.atomic():
            actor = _actor(actor, expected_auth_version=expected_auth_version)
            rule = Rule.objects.get(pk=rule_id)
            if not _editable(actor, rule):
                raise RuleError("规则不存在或无权修改", status=404, code="not_found")
            if rule.revision != expected_revision:
                raise RuleError("规则内容已变化，请重新加载后确认", status=409, code="revision_conflict")
            if requested_kind is not None and requested_kind != rule.kind:
                raise RuleError("规则类型转换必须复制为新规则")
            visibility = visibility or rule.visibility
            if rule.kind == Rule.PUBLIC:
                visibility = Rule.PUBLIC
            new_ids = {item.id for item in doc.rarities}
            old_doc = load_rule_document(rule.config_json)
            structural = new_ids != {item.id for item in old_doc.rarities} or {
                item.id: item.rank for item in doc.rarities
            } != {item.id: item.rank for item in old_doc.rarities}
            if structural and Pool.objects.filter(rule=rule).exists():
                raise RuleError("规则结构已被角色池引用，请复制为新规则后切换")
            raw.update(id=str(rule.pk), original_author=rule.original_author)
            for pool in Pool.objects.filter(rule=rule).select_related("owner"):
                validate_rule_pool_reference(actor, rule, pool_owner=pool.owner,
                    pool_kind=pool.kind, pool_visibility=pool.visibility,
                    proposed_visibility=visibility)
                try:
                    compile_pool(load_rule_document(raw), _pool_document(pool))
                except (TypeError, ValueError) as error:
                    raise RuleError("规则修改与一个或多个引用池不兼容") from error
            Rule.objects.filter(pk=rule.pk, revision=expected_revision).update(
                name=name, name_key=name, visibility=visibility, algorithm=doc.algorithm,
                config_json=raw, revision=expected_revision + 1, updated_at=timezone.now())
            return Rule.objects.get(pk=rule.pk)
    except Rule.DoesNotExist:
        raise RuleError("规则不存在或无权修改", status=404, code="not_found") from None
    except IntegrityError as error:
        raise RuleError("同类型规则已使用该名称") from error
    except OperationalError as error:
        if "locked" in str(error).lower() or "busy" in str(error).lower():
            raise RuleError("存储暂忙，请稍后重试", status=503, code="storage_busy") from error
        raise


def copy_rule(actor, rule_id, name, kind):
    expected_auth_version = getattr(actor, "auth_version", None)
    actor = _actor(actor, expected_auth_version=expected_auth_version)
    try:
        name = normalize_name(name, "规则名称")
    except (TypeError, ValueError) as error:
        raise RuleError(str(error)) from error
    if len(name) > 255 or kind not in (Rule.PRIVATE, Rule.PUBLIC):
        raise RuleError("规则名称或类型无效")
    if kind == Rule.PUBLIC and not actor.is_superuser:
        raise RuleError("仅管理员可以创建公共规则", status=403, code="forbidden")
    try:
        with transaction.atomic():
            actor = _actor(actor, expected_auth_version=expected_auth_version)
            source = visible_rules(actor).get(pk=rule_id)
            if source.kind == Rule.PRIVATE and (
                    source.owner and source.owner.deleting):
                raise RuleError("规则不可访问")
            clone_id = uuid4()
            raw = deepcopy(source.config_json)
            raw.update(id=str(clone_id), name=name, original_author=source.original_author)
            clone = Rule(id=clone_id, name=name, name_key=name, kind=kind,
                         owner=None if kind == Rule.PUBLIC else actor,
                         visibility=Rule.PUBLIC if kind == Rule.PUBLIC else Rule.HIDDEN,
                         original_author=source.original_author, algorithm=source.algorithm,
                         config_json=raw, revision=1)
            clone.save(force_insert=True)
            return clone
    except Rule.DoesNotExist:
        raise RuleError("规则不存在或不可访问", status=404, code="not_found") from None
    except IntegrityError as error:
        raise RuleError("同类型规则已使用该名称") from error
    except OperationalError as error:
        if "locked" in str(error).lower() or "busy" in str(error).lower():
            raise RuleError("存储暂忙，请稍后重试", status=503, code="storage_busy") from error
        raise


def delete_rule(actor, rule_id, expected_revision):
    expected_auth_version = getattr(actor, "auth_version", None)
    actor = _actor(actor, expected_auth_version=expected_auth_version)
    expected_revision = _revision(expected_revision)
    with transaction.atomic():
        actor = _actor(actor, expected_auth_version=expected_auth_version)
        try:
            rule = Rule.objects.get(pk=rule_id)
        except Rule.DoesNotExist:
            raise RuleError("规则不存在或无权删除", status=404, code="not_found") from None
        if not _editable(actor, rule):
            raise RuleError("规则不存在或无权删除", status=404, code="not_found")
        if rule.revision != expected_revision:
            raise RuleError("规则内容已变化，请重新加载后确认", status=409, code="revision_conflict")
        if Pool.objects.filter(rule=rule).exists():
            raise RuleError("规则仍被角色池引用，请先切换或删除这些池")
        try:
            rule.delete()
        except ProtectedError as error:
            raise RuleError("规则仍被角色池引用，请先切换或删除这些池") from error


def export_rule(actor, rule_id, *, expected_revision):
    actor = _actor(actor)
    expected_auth_version = actor.auth_version
    expected_revision = _revision(expected_revision)
    try:
        rule = visible_rules(actor).get(pk=rule_id)
    except (Rule.DoesNotExist, ValueError):
        raise RuleError("规则不存在或不可访问", status=404, code="not_found") from None
    if rule.revision != expected_revision:
        raise RuleError("规则内容已变化，请重新加载后确认", status=409,
                        code="revision_conflict")
    if rule.kind == Rule.PRIVATE and Rule.objects.filter(
            pk=rule.pk, owner__deleting=True).exists():
        raise RuleError("规则不存在或不可访问", status=404, code="not_found")
    _actor(actor, expected_auth_version=expected_auth_version)
    return rule_document(rule)


def resolve_rule_reference(actor, ref, owner=None):
    """Resolve UUID first; an unavailable UUID never falls back to its name."""
    actor = _actor(actor)
    owner_provided = owner is not None
    owner = _fresh_owner(owner)
    if owner_provided and (owner is None or owner.deleting):
        return {"status": "unavailable"}
    if not isinstance(ref, Mapping) or set(ref) != {"id", "name"}:
        raise RuleError("规则引用格式无效")
    try:
        from lottery_simulator.rules.definitions import uuid_text
        rule_id = uuid_text(ref["id"])
        name = normalize_name(ref["name"], "规则引用名称")
    except (ValueError, KeyError, TypeError):
        return {"status": "unavailable"}
    try:
        rule = Rule.objects.get(pk=rule_id)
    except Rule.DoesNotExist:
        candidates = [candidate for candidate in visible_rules(actor).filter(name_key=name)
                      if not Rule.objects.filter(pk=candidate.pk, kind=Rule.PRIVATE,
                          owner__deleting=True).exists() and
                      (not owner_provided or _can_use(owner, candidate))]
        if not candidates:
            return {"status": "unavailable"}
        return {"status": "confirm" if len(candidates) == 1 else "select",
                "candidates": [{"id": str(item.pk), "name": item.name,
                    "original_author": item.original_author, "kind": item.kind,
                    "visibility": item.visibility, "revision": item.revision}
                    for item in candidates]}
    if not visible_rules(actor).filter(pk=rule.pk).exists():
        return {"status": "unavailable"}
    if rule.kind == Rule.PRIVATE and Rule.objects.filter(
            pk=rule.pk, owner__deleting=True).exists():
        return {"status": "unavailable"}
    if owner_provided and not _can_use(owner, rule):
        return {"status": "unavailable"}
    return {"status": "matched", "rule": rule}
