"""Account invariants shared by API and maintenance commands."""

from datetime import timedelta
from ipaddress import ip_address
import unicodedata

from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.hashers import make_password
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from dashboard.models import LoginLimit, User


class AccountError(ValueError):
    pass


class DeleteIncomplete(AccountError):
    """The account remains blocked until an administrator retries cleanup."""


def _admin_actor(actor):
    from dashboard.services.pools import _actor
    fresh = _actor(actor)
    if not fresh.is_superuser:
        raise AccountError("无权管理账号")
    return fresh


def delete_account(actor, target_id):
    """Stop owned processes before removing files and relational data.

    Lock order is always admission lock then a short database transaction.
    No database write transaction is held while waiting for a worker.
    """
    import shutil
    import time
    from uuid import UUID
    from django.contrib.sessions.models import Session
    from dashboard.models import AppMeta
    from dashboard.models import ExperimentConfig, Pool, Rule
    from dashboard.jobs import ACTIVE_STATUSES
    from dashboard.services.pools import _actor
    from dashboard.services.runs import get_manager

    expected_version = getattr(actor, "auth_version", None)
    try:
        target_id = UUID(str(target_id))
    except (ValueError, TypeError, AttributeError):
        raise AccountError("账号不存在") from None
    manager = get_manager()
    manifest_key = f"account_deletion:{target_id}"

    def authorize():
        fresh = _actor(actor, expected_auth_version=expected_version)
        if not fresh.is_superuser:
            raise AccountError("无权管理账号")
        if fresh.pk == target_id:
            raise AccountError("不能删除当前账号")
        return fresh

    def owned_states():
        return [state for state in manager.states()
                if state.owner_id == str(target_id)]

    with manager._locked():
        authorize()
        states = owned_states()
        with transaction.atomic():
            authorize()
            try:
                target = User.objects.get(pk=target_id)
            except User.DoesNotExist:
                raise AccountError("账号不存在") from None
            if target.is_superuser and target.is_active and not target.deleting:
                if User.objects.filter(is_superuser=True, is_active=True, deleting=False).count() <= 1:
                    raise AccountError("不能删除最后一个可用管理员")
            if Pool.objects.filter(rule__owner=target).exclude(owner=target).exists():
                raise AccountError("该账号的私有规则仍被其他用户角色池引用，请先处理引用")
            if not target.deleting:
                target.deleting = True
                target.auth_version += 1
                target.save(update_fields=["deleting", "auth_version"])
            manifest, _ = AppMeta.objects.get_or_create(key=manifest_key, defaults={"value": []})
            job_ids = sorted(set(manifest.value) | {state.job_id for state in states})
            manifest.value = job_ids
            manifest.save(update_fields=["value"])
        try:
            for state in states:
                if state.status in ACTIVE_STATUSES:
                    (manager._job_dir(state.job_id) / "cancel.request").touch()
        except OSError as error:
            raise DeleteIncomplete("账号删除未完成：无法请求停止任务，可重试") from error

    # Cooperative cancellation first. Forced stop is restricted to the exact
    # command line and job directory checked by JobManager.
    deadline = time.monotonic() + 3
    try:
        for state in states:
            directory = manager._job_dir(state.job_id)
            while manager._is_worker(state.pid, directory) and time.monotonic() < deadline:
                time.sleep(0.05)
            if manager._is_worker(state.pid, directory) and not manager._stop_worker(state.pid, directory):
                raise DeleteIncomplete("账号删除未完成：任务尚未停止，可重试")
    except OSError as error:
        raise DeleteIncomplete("账号删除未完成：无法确认任务停止，可重试") from error

    with manager._locked():
        authorize()
        states = owned_states()
        if any(manager._is_worker(state.pid, manager._job_dir(state.job_id)) for state in states):
            raise DeleteIncomplete("账号删除未完成：任务尚未停止，可重试")
        try:
            from dashboard.downloads import cleanup_account_exports
            cleanup_account_exports(target_id)
            # The durable list survives partial rmtree, including removal of
            # state.json. Never infer successful cleanup from a missing state.
            for job_id in job_ids:
                directory = manager._job_dir(job_id)
                # Never follow a symlink or remove the root itself.
                if (directory is None or directory.is_symlink()
                        or directory.resolve().parent != manager.root):
                    raise DeleteIncomplete("账号删除未完成：任务目录不安全")
                if directory.exists():
                    shutil.rmtree(directory)
        except (OSError, ValueError) as error:
            raise DeleteIncomplete("账号删除未完成：文件清理失败，可重试") from error
        try:
            with transaction.atomic():
                authorize()
                target = User.objects.get(pk=target_id, deleting=True)
                if Pool.objects.filter(rule__owner=target).exclude(owner=target).exists():
                    raise AccountError("该账号的私有规则仍被其他用户角色池引用，请先处理引用")
                # Sessions do not have a user FK; remove only decoded sessions
                # belonging to this exact UUID, leaving other accounts untouched.
                for session in Session.objects.iterator(chunk_size=1000):
                    if session.get_decoded().get("_auth_user_id") == str(target_id):
                        session.delete()
                # Remove references owned by this account before its private rules;
                # external consumers were checked above and are never cascaded.
                for pool in Pool.objects.filter(owner=target).iterator():
                    ExperimentConfig.objects.filter(pool=pool).update(
                        pool=None, pool_name_hint=pool.name)
                    pool.delete()
                Rule.objects.filter(owner=target).delete()
                target.delete()
                AppMeta.objects.filter(key=manifest_key).delete()
        except DatabaseError as error:
            raise DeleteIncomplete("账号删除未完成：数据库清理失败，可重试") from error


def normalize_username(value):
    if not isinstance(value, str):
        raise AccountError("用户名必须是文本")
    name = unicodedata.normalize("NFC", value.strip())
    if (not 1 <= len(name) <= 64 or len(name.casefold()) > 64
            or any(unicodedata.category(c) == "Cc" for c in name)):
        raise AccountError("用户名须为1至64字符且不能包含控制字符")
    return name, name.casefold()


def validate_password(value):
    if not isinstance(value, str) or not 6 <= len(value) <= 1024 or len(value.encode("utf-8")) > 4096:
        raise AccountError("密码须为6至1024字符，且不超过4096字节")
    return value


def create_account(actor, username, password, *, admin=False, must_change_password=True):
    name, key = normalize_username(username)
    validate_password(password)
    if actor is not None and (not actor.is_superuser or not actor.is_active or actor.deleting):
        raise AccountError("无权管理账号")
    encoded = make_password(password)
    with transaction.atomic():
        if actor is None and User.objects.exists():
            raise AccountError("首个管理员已经创建")
        if actor is not None:
            _admin_actor(actor)
        user = User(username=name, username_key=key, password=encoded,
                    is_superuser=admin, is_staff=admin,
                    must_change_password=must_change_password)
        try:
            user.save(force_insert=True)
        except IntegrityError as error:
            raise AccountError("用户名已存在") from error
    return user


def update_account(actor, target_id, payload):
    if not actor.is_superuser or not actor.is_active or actor.deleting:
        raise AccountError("无权管理账号")
    allowed = {"username", "role", "enabled"}
    if not isinstance(payload, dict) or payload.keys() - allowed:
        raise AccountError("账号修改字段无效")
    normalized = normalize_username(payload["username"]) if "username" in payload else None
    role = payload.get("role")
    if "role" in payload and role not in ("admin", "user"):
        raise AccountError("角色无效")
    if "enabled" in payload and type(payload["enabled"]) is not bool:
        raise AccountError("启用状态无效")
    with transaction.atomic():
        _admin_actor(actor)
        target = User.objects.get(pk=target_id)
        if target.is_superuser and target.is_active and not target.deleting:
            if (role == "user" or payload.get("enabled") is False) and (
                User.objects.filter(is_superuser=True, is_active=True, deleting=False).count() <= 1
            ):
                raise AccountError("不能禁用或降级最后一个可用管理员")
        changed = False
        if normalized and (target.username, target.username_key) != normalized:
            target.username, target.username_key = normalized
            changed = True
        if role is not None and target.is_superuser != (role == "admin"):
            target.is_superuser = target.is_staff = role == "admin"
            changed = True
        if "enabled" in payload and target.is_active != payload["enabled"]:
            target.is_active = payload["enabled"]
            changed = True
        if changed:
            target.auth_version += 1
            try:
                target.save()
            except IntegrityError as error:
                raise AccountError("用户名已存在") from error
    return target


def change_password(actor, current, new):
    validate_password(new)
    if not actor.check_password(current):
        raise AccountError("当前密码错误")
    encoded = make_password(new)
    with transaction.atomic():
        user = User.objects.get(pk=actor.pk)
        if not user.is_active or user.deleting or user.auth_version != actor.auth_version:
            raise AccountError("账号不可用")
        user.password = encoded
        user.must_change_password = False
        user.auth_version += 1
        user.save(update_fields=["password", "must_change_password", "auth_version"])


def reset_password(actor, target_id, password):
    validate_password(password)
    if actor is not None and (not actor.is_superuser or not actor.is_active or actor.deleting):
        raise AccountError("无权重置密码")
    encoded = make_password(password)
    with transaction.atomic():
        if actor is not None:
            _admin_actor(actor)
        user = User.objects.get(pk=target_id)
        if actor is None and not user.is_superuser:
            raise AccountError("本机恢复仅支持管理员")
        user.password = encoded
        user.must_change_password = True
        user.auth_version += 1
        user.save(update_fields=["password", "must_change_password", "auth_version"])
    return user


def unlock_login(actor, username):
    _, key = normalize_username(username)
    with transaction.atomic():
        if actor is not None:
            _admin_actor(actor)
        LoginLimit.objects.filter(scope="account", key=key).delete()


class UsernameBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        try:
            _, key = normalize_username(username)
            user = User.objects.get(username_key=key)
        except (AccountError, User.DoesNotExist):
            User().set_password(password or "")
            return None
        if user.check_password(password) and self.user_can_authenticate(user) and not user.deleting:
            return user
        return None


def login_source(request):
    remote = request.META.get("REMOTE_ADDR")
    if remote in settings.LOTTERY_TRUSTED_PROXIES:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            try:
                return str(ip_address(forwarded.split(",")[-1].strip()))
            except ValueError:
                return "unknown"
    try:
        return str(ip_address(remote))
    except (ValueError, TypeError):
        return "unknown"


def login_blocked(username_key, source):
    now = timezone.now()
    return (LoginLimit.objects.filter(scope="account", key=username_key,
                                      blocked_until__gt=now).exists() or
            LoginLimit.objects.filter(scope="source", key=source,
                                      blocked_until__gt=now).exists())


def record_login_failure(username_key, source):
    now = timezone.now()
    policies = (("account", username_key, settings.LOTTERY_ACCOUNT_FAILURES),
                ("source", source, settings.LOTTERY_SOURCE_FAILURES))
    with transaction.atomic():
        for scope, key, threshold in policies:
            bucket, _ = LoginLimit.objects.get_or_create(scope=scope, key=key)
            if bucket.blocked_until and bucket.blocked_until > now:
                continue
            if not bucket.window_start or bucket.window_start <= now - timedelta(minutes=15):
                bucket.failure_count = 0
                bucket.window_start = now
                bucket.blocked_until = None
            bucket.failure_count += 1
            if bucket.failure_count >= threshold:
                bucket.blocked_until = now + timedelta(minutes=15)
            bucket.save()


def clear_account_failures(username_key):
    LoginLimit.objects.filter(scope="account", key=username_key).delete()
