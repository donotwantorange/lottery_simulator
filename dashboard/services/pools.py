"""Pool access, mutation, rule binding, and portable pool references."""

from copy import deepcopy
from uuid import uuid4

from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Q
from django.utils import timezone

from dashboard.models import ExperimentConfig, Pool, Rule, User
from dashboard.services.accounts import AccountError
from dashboard.services.rules import (
    RuleError, resolve_rule_reference, rule_document, validate_rule_pool_reference,
    visible_rules,
)
from lottery_simulator.config_documents import load_pool_document, normalize_name, parse_config_json
from lottery_simulator.rules.runtime import compile_pool


class PoolError(ValueError):
    def __init__(self, message, *, status=400, code="validation_error"):
        super().__init__(message)
        self.status = status
        self.code = code


def _actor(actor, *, expected_auth_version=None):
    if not actor or not getattr(actor, "is_authenticated", False):
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
    try:
        name = normalize_name(value, "池名称")
    except (TypeError, ValueError) as error:
        raise PoolError(str(error)) from error
    if len(name) > 255:
        raise PoolError("池名称最长255字符")
    return name, name


def _revision(value):
    if type(value) is not int or value < 1:
        raise PoolError("修订号必须是正整数")
    return value


def _can_edit(actor, pool):
    return actor.is_superuser or (pool.kind == Pool.PRIVATE and pool.owner_id == actor.pk)


def visible_pools(actor):
    actor = _actor(actor)
    pools = Pool.objects.all()
    if actor.is_superuser:
        return pools
    return pools.filter(Q(kind=Pool.PUBLIC) | Q(kind=Pool.PRIVATE, visibility=Pool.PUBLIC) |
                        Q(kind=Pool.PRIVATE, owner_id=actor.pk)).distinct()


def _pool_document(pool):
    raw = deepcopy(pool.config_json)
    raw.update(id=str(pool.pk), name=pool.name,
               original_author=pool.original_author or None,
               rule_ref={"id": str(pool.rule_id), "name": pool.rule.name})
    return load_pool_document(raw)


def pool_document(pool):
    return _pool_document(pool).to_dict()


def _definition(payload):
    if not isinstance(payload, dict):
        raise PoolError("池配置必须是对象")
    controls = {"kind", "visibility", "expected_revision", "expected_rule_revision",
                "rarity_mapping", "clear_unmapped"}
    if "config" in payload:
        if payload.keys() - (controls | {"config"}):
            raise PoolError("池服务对象包含不支持字段")
        raw = deepcopy(payload["config"])
    else:
        raw = {key: value for key, value in payload.items() if key not in controls}
    try:
        doc = load_pool_document(raw)
    except (TypeError, ValueError) as error:
        raise PoolError(str(error)) from error
    if doc.original_author is not None and len(doc.original_author) > 255:
        raise PoolError("最初作者署名最长255字符")
    return doc


def _rule_for_pool(actor, owner, kind, visibility, ref, expected_revision):
    try:
        resolved = resolve_rule_reference(actor, ref, owner=owner)
        if resolved["status"] != "matched":
            raise PoolError("规则不可访问，请先在当前规则列表中明确选择", status=404,
                            code="not_found")
        rule = resolved["rule"]
    except RuleError as error:
        raise PoolError(str(error), status=error.status, code=error.code) from error
    if expected_revision is None:
        raise PoolError("缺少expected_rule_revision")
    if _revision(expected_revision) != rule.revision:
        raise PoolError("规则内容已变化，请重新加载后确认", status=409, code="revision_conflict")
    try:
        validate_rule_pool_reference(actor, rule, pool_owner=owner,
                                     pool_kind=kind, pool_visibility=visibility)
    except RuleError as error:
        raise PoolError(str(error), status=error.status, code=error.code) from error
    return rule


def _validate_mapping(previous, current, old_rule, new_rule, rarity_mapping, clear_unmapped):
    if type(clear_unmapped) is not bool:
        raise PoolError("清空旧稀有度数据确认必须是布尔值")
    old_ids = {item.id for item in old_rule.rarities}
    new_ids = {item.id for item in new_rule.rarities}
    mapping = rarity_mapping or {}
    if not isinstance(mapping, dict) or set(mapping) - old_ids:
        raise PoolError("稀有度ID映射无效")
    if any(value is not None and value not in new_ids for value in mapping.values()):
        raise PoolError("稀有度ID映射目标无效")
    removed = old_ids - new_ids
    unresolved = removed - set(mapping)
    if unresolved and not clear_unmapped:
        raise PoolError("稀有度结构已变化；请逐项映射或明确确认清空旧档数据")
    if any(mapping.get(rarity_id) is None for rarity_id in removed) and not clear_unmapped:
        raise PoolError("清空未映射稀有度数据需要明确确认")
    old_pools = {item.rarity_id: item for item in previous.rarity_pools}
    new_pools = {item.rarity_id: item for item in current.rarity_pools}
    old_labels = previous.rarity_labels
    new_labels = current.rarity_labels
    new_rewards = {item.id: item for item in current.rewards}
    for old_id in removed:
        target_id = mapping.get(old_id)
        if target_id is None:
            continue
        source = old_pools[old_id]
        target = new_pools.get(target_id)
        if target is None:
            raise PoolError("稀有度映射目标不存在")
        expected_characters = []
        for character in source.characters:
            item = character.to_dict()
            item["rarity_id"] = target_id
            expected_characters.append(item)
        if [c.to_dict() for c in target.characters] != expected_characters:
            raise PoolError("稀有度角色映射未按角色ID和名单顺序应用")
        if source.up_enabled != target.up_enabled or source.up_share != target.up_share:
            raise PoolError("稀有度UP配置映射不一致")
        if old_id in old_labels and new_labels.get(target_id) != old_labels[old_id]:
            raise PoolError("稀有度显示名映射不一致")
        for reward in previous.rewards:
            if old_id in reward.amounts:
                target_reward = new_rewards.get(reward.id)
                if target_reward is None or target_reward.amounts.get(target_id) != reward.amounts[old_id]:
                    raise PoolError("稀有度奖励映射不一致")


def _remap_pool_data(raw, old_rule, new_rule, rarity_mapping, clear_unmapped):
    """Apply an explicit rarity-ID map to roster, labels, and reward drafts."""
    data = deepcopy(raw)
    old_ids = {r.id for r in old_rule.rarities}
    new_ids = {r.id for r in new_rule.rarities}
    mapping = rarity_mapping or {}
    if not isinstance(mapping, dict):
        raise PoolError("稀有度ID映射无效")
    if type(clear_unmapped) is not bool:
        raise PoolError("清空旧稀有度数据确认必须是布尔值")
    removed = old_ids - new_ids
    if removed - set(mapping) and not clear_unmapped:
        raise PoolError("稀有度结构已变化；请逐项映射或明确确认清空旧档数据")
    for key, value in mapping.items():
        if key not in old_ids or (value is not None and value not in new_ids):
            raise PoolError("稀有度ID映射无效")
    mapping = {key: mapping.get(key, key if key in new_ids else None) for key in old_ids}
    rosters = []
    for item in data["rarity_pools"]:
        rarity_id = item["rarity_id"]
        target = mapping.get(rarity_id, rarity_id if rarity_id in new_ids else None)
        if target is None:
            continue
        item["rarity_id"] = target
        for character in item["characters"]:
            character["rarity_id"] = target
        if any(existing["rarity_id"] == target for existing in rosters):
            raise PoolError("多个旧稀有度映射到同一档，无法自动合并角色名单")
        rosters.append(item)
    present = {item["rarity_id"] for item in rosters}
    for rarity in new_rule.rarities:
        if rarity.id not in present:
            rosters.append({"rarity_id": rarity.id, "characters": [],
                            "up_enabled": False, "up_share": 0})
    data["rarity_pools"] = rosters
    labels = {}
    for rarity_id, label in data["rarity_labels"].items():
        target = mapping.get(rarity_id, rarity_id if rarity_id in new_ids else None)
        if target is not None:
            if target in labels:
                raise PoolError("稀有度显示名映射发生冲突")
            labels[target] = label
    data["rarity_labels"] = labels
    for reward in data["rewards"]:
        amounts = {}
        for rarity_id, amount in reward["amounts"].items():
            target = mapping.get(rarity_id, rarity_id if rarity_id in new_ids else None)
            if target is None:
                continue
            if target in amounts and amounts[target] != amount:
                raise PoolError("多个旧奖励金额映射到同一档且数值不同")
            amounts[target] = amount
        reward["amounts"] = amounts
    return data


def save_pool(actor, payload: dict, *, pool_id=None, expected_revision=None,
              expected_rule_revision=None, rarity_mapping=None, clear_unmapped=False):
    """Save a complete pool against a visible current rule revision."""
    expected_auth_version = getattr(actor, "auth_version", None)
    actor = _actor(actor, expected_auth_version=expected_auth_version)
    doc = _definition(payload)
    name, name_key = _pool_name(doc.name)
    kind = payload.get("kind", Pool.PRIVATE)
    visibility = payload.get("visibility", Pool.HIDDEN)
    if kind not in (Pool.PUBLIC, Pool.PRIVATE) or visibility not in (Pool.PUBLIC, Pool.HIDDEN):
        raise PoolError("池类型或可见性无效")
    if kind == Pool.PUBLIC and not actor.is_superuser:
        raise PoolError("仅管理员可以创建公共池", status=403, code="forbidden")
    if kind == Pool.PUBLIC:
        visibility = Pool.PUBLIC
    expected_revision = _revision(expected_revision) if pool_id is not None else None
    try:
        with transaction.atomic():
            actor = _actor(actor, expected_auth_version=expected_auth_version)
            old = None
            if pool_id is not None:
                try:
                    old = Pool.objects.select_related("owner", "rule").get(pk=pool_id)
                except (Pool.DoesNotExist, ValueError):
                    raise PoolError("角色池不存在或无权修改", status=404, code="not_found") from None
                if not _can_edit(actor, old):
                    raise PoolError("角色池不存在或无权修改", status=404, code="not_found")
                if old.revision != expected_revision:
                    raise PoolError("角色池内容已变化，请重新加载后确认", status=409,
                                    code="revision_conflict")
                if "kind" in payload and kind != old.kind:
                    raise PoolError("池类型转换必须复制为新池")
                kind = old.kind
                visibility = (Pool.PUBLIC if kind == Pool.PUBLIC else payload.get("visibility", old.visibility))
            owner = None if kind == Pool.PUBLIC else (old.owner if old else actor)
            rule = _rule_for_pool(actor, owner, kind, visibility, doc.rule_ref,
                                  expected_rule_revision)
            raw = doc.to_dict()
            current_rule = load_rule_definition(rule)
            if old is not None:
                previous = _pool_document(old)
                old_rule = load_rule_definition(old.rule)
                raw = _remap_pool_data(raw, old_rule, current_rule,
                                       rarity_mapping, clear_unmapped)
            raw.update(id=str(old.pk) if old else str(uuid4()),
                       original_author=old.original_author if old else
                       (doc.original_author or actor.username))
            definition = load_pool_document(raw)
            try:
                compile_pool(current_rule, definition)
            except (TypeError, ValueError) as error:
                raise PoolError(str(error)) from error
            if old is not None:
                _validate_mapping(previous, definition, old_rule, current_rule,
                                  rarity_mapping, clear_unmapped)
            config = definition.to_dict()
            config["rule_ref"] = {"id": str(rule.pk), "name": rule.name}
            if old is None:
                saved = Pool(id=definition.id, name=name, name_key=name_key, kind=kind,
                             owner=owner, rule=rule, visibility=visibility,
                             original_author=definition.original_author or actor.username,
                             config_json=config, revision=1)
                saved.save(force_insert=True)
                return saved
            changed = Pool.objects.filter(pk=old.pk, revision=expected_revision).update(
                name=name, name_key=name_key, visibility=visibility, rule=rule,
                config_json=config, revision=expected_revision + 1, updated_at=timezone.now())
            if not changed:
                raise PoolError("角色池内容已变化，请重新加载后确认", status=409,
                                code="revision_conflict")
            return Pool.objects.select_related("owner", "rule").get(pk=old.pk)
    except IntegrityError as error:
        raise PoolError("同类型角色池已使用该名称") from error
    except OperationalError as error:
        if "locked" in str(error).lower() or "busy" in str(error).lower():
            raise PoolError("存储暂忙，请稍后重试", status=503, code="storage_busy") from error
        raise


def load_rule_definition(rule):
    from lottery_simulator.config_documents import load_rule_document
    return load_rule_document(rule_document(rule))


def copy_pool(actor, pool_id, *, name: str, kind: str, expected_revision,
              expected_source_rule_revision, rule_ref=None, expected_rule_revision=None, rarity_mapping=None,
              clear_unmapped=False):
    expected_auth_version = getattr(actor, "auth_version", None)
    actor = _actor(actor, expected_auth_version=expected_auth_version)
    name, name_key = _pool_name(name)
    if kind not in (Pool.PUBLIC, Pool.PRIVATE):
        raise PoolError("池类型无效")
    if kind == Pool.PUBLIC and not actor.is_superuser:
        raise PoolError("仅管理员可以创建公共池", status=403, code="forbidden")
    expected_revision = _revision(expected_revision)
    try:
        with transaction.atomic():
            actor = _actor(actor, expected_auth_version=expected_auth_version)
            try:
                source = visible_pools(actor).select_related("owner", "rule").get(pk=pool_id)
            except (Pool.DoesNotExist, ValueError):
                raise PoolError("角色池不存在或不可访问", status=404, code="not_found") from None
            if source.revision != expected_revision:
                raise PoolError("角色池内容已变化，请重新加载后确认", status=409,
                                code="revision_conflict")
            if source.rule.revision != _revision(expected_source_rule_revision):
                raise PoolError("源规则内容已变化，请重新加载后确认", status=409,
                                code="revision_conflict")
            owner = None if kind == Pool.PUBLIC else actor
            if kind == Pool.PUBLIC and rule_ref is None:
                raise PoolError("复制为公共池前必须明确选择公共规则")
            ref = rule_ref or {"id": str(source.rule_id), "name": source.rule.name}
            rule = _rule_for_pool(actor, owner, kind,
                                  Pool.PUBLIC if kind == Pool.PUBLIC else Pool.HIDDEN,
                                  ref, expected_rule_revision)
            source_document = pool_document(source)
            source_rule = load_rule_definition(source.rule)
            target_rule = load_rule_definition(rule)
            raw = _remap_pool_data(source_document, source_rule, target_rule,
                                   rarity_mapping, clear_unmapped)
            raw.update(id=str(uuid4()), name=name, original_author=source.original_author,
                       rule_ref={"id": str(rule.pk), "name": rule.name})
            copied = load_pool_document(raw)
            try:
                compile_pool(target_rule, copied)
                _validate_mapping(load_pool_document(source_document), copied,
                                  source_rule, target_rule,
                                  rarity_mapping, clear_unmapped)
            except (TypeError, ValueError) as error:
                raise PoolError(str(error)) from error
            clone = Pool(id=copied.id, name=name, name_key=name_key, kind=kind,
                         owner=owner, rule=rule,
                         visibility=Pool.PUBLIC if kind == Pool.PUBLIC else Pool.HIDDEN,
                         original_author=source.original_author, config_json=copied.to_dict(), revision=1)
            clone.save(force_insert=True)
            return clone
    except IntegrityError as error:
        raise PoolError("同类型角色池已使用该名称") from error
    except OperationalError as error:
        if "locked" in str(error).lower() or "busy" in str(error).lower():
            raise PoolError("存储暂忙，请稍后重试", status=503, code="storage_busy") from error
        raise


def delete_pool(actor, pool_id, *, expected_revision):
    expected_auth_version = getattr(actor, "auth_version", None)
    actor = _actor(actor, expected_auth_version=expected_auth_version)
    expected_revision = _revision(expected_revision)
    try:
        with transaction.atomic():
            actor = _actor(actor, expected_auth_version=expected_auth_version)
            try:
                pool = Pool.objects.get(pk=pool_id)
            except (Pool.DoesNotExist, ValueError):
                raise PoolError("角色池不存在或无权删除", status=404, code="not_found") from None
            if not _can_edit(actor, pool):
                raise PoolError("角色池不存在或无权删除", status=404, code="not_found")
            if pool.revision != expected_revision:
                raise PoolError("角色池内容已变化，请重新加载后确认", status=409,
                                code="revision_conflict")
            ExperimentConfig.objects.filter(pool=pool).update(pool=None, pool_name_hint=pool.name)
            pool.delete()
    except OperationalError as error:
        if "locked" in str(error).lower() or "busy" in str(error).lower():
            raise PoolError("存储暂忙，请稍后重试", status=503, code="storage_busy") from error
        raise


def export_pool(actor, pool_id, *, expected_revision):
    actor = _actor(actor)
    expected_revision = _revision(expected_revision)
    try:
        pool = visible_pools(actor).select_related("rule").get(pk=pool_id)
    except (Pool.DoesNotExist, ValueError):
        raise PoolError("角色池不存在或不可访问", status=404, code="not_found") from None
    if pool.revision != expected_revision:
        raise PoolError("角色池内容已变化，请重新加载后确认", status=409,
                        code="revision_conflict")
    return pool_document(pool)


def preview_pool_import(actor, raw):
    """Strictly parse a v3 pool file and resolve its rule without replacing its ID by name."""
    if isinstance(raw, bytes):
        try:
            raw = parse_config_json(raw)
        except ValueError as error:
            raise PoolError(str(error)) from error
    try:
        document = load_pool_document(raw)
    except (TypeError, ValueError) as error:
        raise PoolError(str(error)) from error
    actor = _actor(actor)
    try:
        resolution = resolve_rule_reference(actor, document.rule_ref, owner=actor)
    except RuleError as error:
        raise PoolError(str(error), status=error.status, code=error.code) from error
    if resolution["status"] == "matched":
        rule = resolution["rule"]
        try:
            compile_pool(load_rule_definition(rule), document)
        except (TypeError, ValueError) as error:
            raise PoolError(str(error)) from error
        resolution = {"status": "matched", "rule": {
            "id": str(rule.pk), "name": rule.name, "revision": rule.revision}}
    else:
        resolution = {"status": resolution["status"],
                      "candidates": resolution.get("candidates", [])}
    return {"document": document.to_dict(), "resolution": resolution}


def confirm_pool_import(actor, raw, *, rule_id, rule_revision):
    expected_auth_version = getattr(actor, "auth_version", None)
    with transaction.atomic():
        actor = _actor(actor, expected_auth_version=expected_auth_version)
        preview = preview_pool_import(actor, raw)
        document = load_pool_document(preview["document"])
        try:
            rule = visible_rules(actor).get(pk=rule_id)
        except (Rule.DoesNotExist, ValueError, TypeError):
            raise PoolError("请选择一个当前可用的规则") from None
        resolution = preview["resolution"]
        allowed = ([resolution["rule"]["id"]] if resolution["status"] == "matched" else
                   [candidate["id"] for candidate in resolution.get("candidates", [])]
                   if resolution["status"] in {"confirm", "select"} else [])
        if str(rule.pk) not in allowed:
            raise PoolError("所选规则不属于文件ID匹配或名称候选，请重新预览")
        raw_document = document.to_dict()
        raw_document.update(id=str(uuid4()),
                            rule_ref={"id": str(rule.pk), "name": rule.name})
        return save_pool(actor, raw_document, expected_rule_revision=rule_revision)
