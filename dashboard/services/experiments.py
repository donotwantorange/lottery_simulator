"""User-owned experiment configuration access and pool-reference matching."""

from copy import deepcopy
import re
from uuid import UUID

from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Q
from django.utils import timezone

from dashboard.models import ExperimentConfig, Pool, User
from dashboard.services.accounts import AccountError
from dashboard.services.pools import _actor, _pool_name, pool_document
from lottery_simulator.config_documents import (
    EXPERIMENT_FORMAT_VERSION, load_experiment_document, load_pool_document,
    normalize_name, validate_experiment_parameters,
)


class ExperimentError(ValueError):
    """An experiment operation failed for a user-correctable reason."""

    def __init__(self, message, *, status=400, code="validation_error"):
        super().__init__(message)
        self.status = status
        self.code = code


def _experiment_actor(actor):
    expected_version = getattr(actor, "auth_version", None)
    return _actor(actor, expected_auth_version=expected_version), expected_version


def _name(value):
    try:
        name = normalize_name(value, "实验名称")
    except (TypeError, ValueError) as error:
        raise ExperimentError(str(error)) from error
    if len(name) > 255:
        raise ExperimentError("实验名称最长255字符")
    return name, name


def _revision(value):
    if type(value) is not int or value < 1:
        raise ExperimentError("expected_revision必须是正整数")
    return value


def _pool_ref(value):
    if not isinstance(value, dict) or value.keys() != {"id", "name"}:
        raise ExperimentError("角色池引用必须包含id和name")
    try:
        pool_id = str(UUID(value["id"]))
        pool_name, _ = _pool_name(value["name"])
    except (TypeError, ValueError) as error:
        raise ExperimentError("角色池引用无效") from error
    return {"id": pool_id, "name": pool_name}


def _pool_candidate(pool):
    return {
        "id": str(pool.pk),
        "name": pool.name,
        "revision": pool.revision,
        "kind": pool.kind,
        "visibility": pool.visibility,
        "owner_id": str(pool.owner_id) if pool.owner_id else None,
        "owner_name": pool.owner.username if pool.owner_id else None,
        "original_author": pool.original_author,
    }


def _owner_pool_query(owner):
    """Compute pool rights for a data owner without requiring an active session."""
    try:
        current_owner = User.objects.get(pk=owner.pk)
    except User.DoesNotExist:
        return Pool.objects.none()
    if current_owner.is_superuser:
        return Pool.objects.all()
    return Pool.objects.filter(
        Q(kind=Pool.PUBLIC) | Q(kind=Pool.PRIVATE, visibility=Pool.PUBLIC) |
        Q(kind=Pool.PRIVATE, owner_id=current_owner.pk)
    ).distinct()


def resolve_pool_reference(actor, pool_ref, *, owner=None):
    """Resolve a reference for the supplied data owner after validating requester."""
    actor, expected_version = _experiment_actor(actor)
    owner = actor if owner is None else owner
    ref = _pool_ref(pool_ref)
    try:
        exact = Pool.objects.filter(pk=ref["id"]).select_related("owner").first()
    except (TypeError, ValueError):
        exact = None
    permitted = _owner_pool_query(owner).select_related("owner")
    if exact is not None:
        if permitted.filter(pk=exact.pk).exists():
            actor = _actor(actor, expected_auth_version=expected_version)
            return {"status": "matched", "candidates": [_pool_candidate(exact)]}
        # Do not disclose the name, type, or existence of an inaccessible pool.
        actor = _actor(actor, expected_auth_version=expected_version)
        return {"status": "unavailable", "candidates": []}

    candidates = list(permitted.filter(name=ref["name"]).order_by("name", "id"))
    actor = _actor(actor, expected_auth_version=expected_version)
    if len(candidates) == 1:
        status = "confirm"
    elif candidates:
        status = "select"
    else:
        status = "unavailable"
    return {"status": status, "candidates": [_pool_candidate(pool) for pool in candidates]}


def visible_experiments(actor):
    """Return the current user's experiments, or all for an administrator."""
    actor, _ = _experiment_actor(actor)
    query = ExperimentConfig.objects.all()
    if not actor.is_superuser:
        query = query.filter(owner_id=actor.pk)
    return query.select_related("owner", "pool").order_by("name", "id")


def _target_owner(actor, *, config=None, owner_id=None):
    if config is not None:
        return config.owner
    if owner_id is None:
        return actor
    if not actor.is_superuser:
        raise ExperimentError("实验配置不存在或无权管理", status=404, code="not_found")
    try:
        return User.objects.get(pk=owner_id)
    except (User.DoesNotExist, ValueError, TypeError):
        raise ExperimentError("实验配置所属用户不存在或不可用", status=404,
                              code="not_found") from None


def _validated_document(payload):
    if not isinstance(payload, dict) or payload.keys() != {"name", "pool_ref", "parameters"}:
        raise ExperimentError("实验配置必须包含name、pool_ref和parameters")
    try:
        return load_experiment_document({"format_version": EXPERIMENT_FORMAT_VERSION, **payload})
    except (TypeError, ValueError) as error:
        raise ExperimentError(str(error)) from error


def _authorized_pool(owner, pool_ref):
    ref = _pool_ref(pool_ref)
    try:
        pool = _owner_pool_query(owner).select_related("owner").get(pk=ref["id"])
    except (Pool.DoesNotExist, ValueError):
        raise ExperimentError("角色池不存在或当前配置所有者不可使用", status=400,
                              code="validation_error") from None
    try:
        pool_doc = load_pool_document(pool_document(pool))
    except (TypeError, ValueError) as error:
        raise ExperimentError("角色池配置无效，无法用于实验") from error
    return pool, pool_doc


def _save(actor, payload, *, config_id=None, expected_revision=None,
          owner_id=None, expected_pool_revision=None):
    expected_actor_version = getattr(actor, "auth_version", None)
    actor = _actor(actor, expected_auth_version=expected_actor_version)
    document = _validated_document(payload)
    name, name_key = _name(document.name)
    ref = _pool_ref(document.pool_ref)
    if owner_id is not None and config_id is not None:
        raise ExperimentError("编辑现有配置时不能修改所属用户")
    if config_id is not None:
        expected_revision = _revision(expected_revision)
    elif expected_revision is not None:
        raise ExperimentError("新建配置不接受expected_revision")
    if expected_pool_revision is not None:
        expected_pool_revision = _revision(expected_pool_revision)

    try:
        with transaction.atomic():
            actor = _actor(actor, expected_auth_version=expected_actor_version)
            config = None
            if config_id is not None:
                configs = ExperimentConfig.objects.select_related("owner").filter(pk=config_id)
                if not actor.is_superuser:
                    configs = configs.filter(owner_id=actor.pk)
                config = configs.first()
                if config is None:
                    raise ExperimentError("实验配置不存在或无权管理", status=404, code="not_found")
                owner = config.owner
            else:
                owner = _target_owner(actor, owner_id=owner_id)
            pool, pool_doc = _authorized_pool(owner, ref)
            if expected_pool_revision is not None and pool.revision != expected_pool_revision:
                raise ExperimentError("确认导入期间角色池已变化，请重新预览", status=409,
                                      code="revision_conflict")
            try:
                parameters = validate_experiment_parameters(document.parameters, pool_doc)
            except (TypeError, ValueError) as error:
                raise ExperimentError(str(error)) from error
            values = {
                "name": name,
                "name_key": name_key,
                "pool": pool,
                "pool_name_hint": pool.name,
                "parameters_json": deepcopy(parameters),
            }
            if config is None:
                result = ExperimentConfig.objects.create(owner=owner, revision=1, **values)
            else:
                changed = ExperimentConfig.objects.filter(
                    pk=config.pk, owner_id=owner.pk, revision=expected_revision
                ).update(**values, revision=expected_revision + 1,
                         updated_at=timezone.now())
                if not changed:
                    raise ExperimentError("实验配置已变化，请重新加载后确认", status=409,
                                          code="revision_conflict")
                result = ExperimentConfig.objects.select_related("owner", "pool").get(pk=config.pk)
            return result
    except IntegrityError as error:
        raise ExperimentError("该用户已有同名实验配置") from error
    except OperationalError as error:
        if "locked" in str(error).lower() or "busy" in str(error).lower():
            raise ExperimentError("存储暂忙，请稍后重试", status=503, code="storage_busy") from error
        raise


def save_experiment(actor, payload: dict, *, config_id=None, expected_revision=None,
                    owner_id=None) -> ExperimentConfig:
    """Create a configuration or revision-guarded edit an authorized one."""
    return _save(actor, payload, config_id=config_id,
                 expected_revision=expected_revision, owner_id=owner_id)


def delete_experiment(actor, config_id, *, expected_revision):
    expected_actor_version = getattr(actor, "auth_version", None)
    actor = _actor(actor, expected_auth_version=expected_actor_version)
    expected_revision = _revision(expected_revision)
    try:
        with transaction.atomic():
            actor = _actor(actor, expected_auth_version=expected_actor_version)
            configs = ExperimentConfig.objects.filter(pk=config_id)
            if not actor.is_superuser:
                configs = configs.filter(owner_id=actor.pk)
            config = configs.first()
            if config is None:
                raise ExperimentError("实验配置不存在或无权管理", status=404, code="not_found")
            if config.revision != expected_revision:
                raise ExperimentError("实验配置已变化，请重新加载后确认", status=409,
                                      code="revision_conflict")
            config.delete()
    except OperationalError as error:
        if "locked" in str(error).lower() or "busy" in str(error).lower():
            raise ExperimentError("存储暂忙，请稍后重试", status=503, code="storage_busy") from error
        raise


def experiment_document(config):
    if config.pool_id is None:
        raise ExperimentError("引用角色池已失效，请重新选择可用角色池后再导出")
    return {
        "format_version": EXPERIMENT_FORMAT_VERSION,
        "name": config.name,
        "pool_ref": {"id": str(config.pool_id), "name": config.pool.name},
        "parameters": deepcopy(config.parameters_json),
    }


def export_experiment(actor, config_id, *, expected_revision):
    expected_actor_version = getattr(actor, "auth_version", None)
    actor = _actor(actor, expected_auth_version=expected_actor_version)
    expected_revision = _revision(expected_revision)
    configs = ExperimentConfig.objects.select_related("owner", "pool").filter(pk=config_id)
    if not actor.is_superuser:
        configs = configs.filter(owner_id=actor.pk)
    config = configs.first()
    if config is None:
        raise ExperimentError("实验配置不存在或无权管理", status=404, code="not_found")
    if config.revision != expected_revision:
        raise ExperimentError("实验配置已变化，请重新导出", status=409, code="revision_conflict")
    if config.pool_id is None or not _owner_pool_query(config.owner).filter(pk=config.pool_id).exists():
        raise ExperimentError("引用角色池已失效或不可用，无法导出")
    _actor(actor, expected_auth_version=expected_actor_version)
    document = experiment_document(config)
    seed = document["parameters"].get("seed")
    if seed is not None:
        document["parameters"]["seed"] = int(seed)
    return document


def import_preview(actor, raw_document, *, owner_id=None):
    """Validate a portable file and return the current owner-scoped match options."""
    try:
        document = load_experiment_document(raw_document)
    except (TypeError, ValueError) as error:
        raise ExperimentError(str(error)) from error
    actor, expected_actor_version = _experiment_actor(actor)
    owner = _target_owner(actor, owner_id=owner_id)
    resolution = resolve_pool_reference(actor, document.pool_ref, owner=owner)
    _actor(actor, expected_auth_version=expected_actor_version)
    payload = document.to_dict()
    for field in ("draws", "trials", "initial_pity", "initial_five_star_pity", "seed"):
        value = payload["parameters"].get(field)
        if value is not None:
            payload["parameters"][field] = str(value)
    return {"document": payload, "resolution": resolution}


def confirm_experiment_import(actor, raw_document, *, pool_id, pool_revision, owner_id=None):
    """Recheck selected pool access and revision in the same write transaction as save."""
    try:
        document = load_experiment_document(raw_document)
    except (TypeError, ValueError) as error:
        # API round-trips large seeds as decimal strings; file format itself uses integers.
        if not isinstance(raw_document, dict):
            raise ExperimentError(str(error)) from error
        imported = deepcopy(raw_document)
        parameters = imported.get("parameters")
        integer_fields = {"draws", "trials", "initial_pity", "initial_five_star_pity"}
        if not isinstance(parameters, dict):
            raise ExperimentError(str(error)) from error
        for field in integer_fields:
            value = parameters.get(field)
            if isinstance(value, str):
                if not re.fullmatch(r"(0|[1-9][0-9]*)", value):
                    raise ExperimentError(f"{field}必须是十进制整数字符串") from error
                try:
                    parameters[field] = int(value)
                except ValueError as conversion_error:
                    raise ExperimentError("实验数量超过当前Python整数解析范围") from conversion_error
        seed = parameters.get("seed")
        if isinstance(seed, str):
            if not re.fullmatch(r"-?(0|[1-9][0-9]*)", seed):
                raise ExperimentError("随机种子必须是十进制整数字符串") from error
            try:
                parameters["seed"] = int(seed)
            except ValueError as conversion_error:
                raise ExperimentError("随机种子超出当前Python整数解析范围") from conversion_error
        try:
            document = load_experiment_document(imported)
        except (TypeError, ValueError) as nested_error:
            raise ExperimentError(str(nested_error)) from nested_error

    expected_actor_version = getattr(actor, "auth_version", None)
    actor = _actor(actor, expected_auth_version=expected_actor_version)
    pool_revision = _revision(pool_revision)
    try:
        selected_id = str(UUID(str(pool_id)))
    except (TypeError, ValueError, AttributeError):
        raise ExperimentError("请选择一个当前可用的角色池") from None
    payload = {
        "name": document.name,
        "pool_ref": {"id": selected_id, "name": "待确认角色池"},
        "parameters": document.parameters,
    }
    # _save repeats actor, owner, visibility, and revision checks under the write transaction.
    return _save(actor, payload, owner_id=owner_id, expected_pool_revision=pool_revision)
