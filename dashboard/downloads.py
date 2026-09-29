"""Authenticated, bounded-memory exports with per-batch revocation checks."""

import json
import fcntl
import logging
import os
import re
import stat
import time
from pathlib import Path
import tempfile
from threading import BoundedSemaphore, Lock
from uuid import UUID

from django.conf import settings
from django.contrib.sessions.models import Session
from django.http import StreamingHttpResponse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.csrf import csrf_protect

from dashboard.api.errors import APIError, error_response
from dashboard.api.pools import _json_body
from dashboard.limits import TraceLimits
from dashboard.models import User
from dashboard.trace_store import TraceFilter
from lottery_simulator.formats import TRACE_EXPORT_FORMAT_VERSION


# ponytail: slots are per WSGI process, as specified; cross-process/global
# export scheduling would require a different deployment policy.
_slots = BoundedSemaphore(int(os.environ.get("LOTTERY_DOWNLOAD_SLOTS", "1")))
_paths_lock = Lock()
_active_paths = set()


class SessionGate:
    """Reload database session and account; never extend session activity."""

    def __init__(self, request):
        self.key = request.session.session_key
        self.user_id = request.session.get("_auth_user_id")

    def actor(self):
        now = timezone.now()
        session = Session.objects.filter(session_key=self.key, expire_date__gt=now).first()
        data = session.get_decoded() if session is not None else {}
        try:
            created = timezone.datetime.fromisoformat(data["created_at"])
            active = timezone.datetime.fromisoformat(data["last_activity_at"])
            user = User.objects.get(pk=self.user_id)
            valid = (
                data.get("_auth_user_id") == self.user_id
                and user.is_active and not user.deleting and not user.must_change_password
                and data.get("auth_version") == user.auth_version
                and constant_time_compare(data.get("_auth_user_hash", ""), user.get_session_auth_hash())
                and 0 <= (now - created).total_seconds() < settings.LOTTERY_ABSOLUTE_SECONDS
                and 0 <= (now - active).total_seconds() < settings.LOTTERY_IDLE_SECONDS
            )
        except (KeyError, TypeError, ValueError, User.DoesNotExist):
            valid = False
        if not valid:
            raise APIError("unauthenticated", "会话已失效，请重新登录后下载", 401)
        return user


def _run(gate, run_id):
    from dashboard.services.runs import get_run_for_actor
    return get_run_for_actor(gate.actor(), run_id)


def _cleanup(path):
    try:
        path.unlink(missing_ok=True)
    except OSError:
        # A retryable orphan must not consume the only download slot or mask
        # the original generation error. Account/maintenance cleanup can retry.
        logging.getLogger(__name__).exception("导出临时文件清理失败")
    finally:
        with _paths_lock:
            _active_paths.discard(path)


class DownloadStream:
    """An explicitly closeable iterator, including before its first next()."""

    def __init__(self, path, check):
        self.path, self.check = path, check
        self.handle = path.open("rb")
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.closed:
            raise StopIteration
        try:
            self.check()
            data = self.handle.read(64 * 1024)
            if not data:
                self.close()
                raise StopIteration
            return data
        except BaseException:
            self.close()
            raise

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self.handle.close()
                _cleanup(self.path)
            finally:
                _slots.release()


def cleanup_account_exports(user_id):
    """Delete only this account's inactive server-generated export files."""
    prefix = f"user_{UUID(str(user_id)).hex}_"
    _cleanup_matching_exports(prefix + "*.jsonl", require_stopped=True)


def cleanup_run_exports(run_id):
    """Active streams observe deleted resources and clean themselves on close."""
    _cleanup_matching_exports(f"user_*_run_{UUID(str(run_id)).hex}_*.jsonl", require_stopped=False)


def _cleanup_matching_exports(pattern, *, require_stopped):
    directory = Path(settings.EXPORTS_DIR)
    if directory.is_symlink():
        raise ValueError("导出目录不安全")
    if not directory.exists():
        return
    for path in directory.glob(pattern):
        with _paths_lock:
            if path in _active_paths:
                if require_stopped:
                    raise ValueError("该账号的下载尚未停止，请重试")
                continue
            if path.is_symlink() or path.resolve().parent != directory.resolve():
                raise ValueError("导出文件路径不安全")
            try:
                with path.open("rb") as handle:
                    # Protect exports in other WSGI processes as well.
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    path.unlink(missing_ok=True)
            except BlockingIOError:
                if require_stopped:
                    raise ValueError("该账号的下载尚未停止，请重试") from None
            except FileNotFoundError:
                pass


def cleanup_stale_exports(*, older_than_seconds=86400, limit=100):
    """Bounded orphan cleanup: age alone never authorizes deletion."""
    directory = Path(settings.EXPORTS_DIR)
    pattern = re.compile(r"user_[0-9a-f]{32}_run_[0-9a-f]{32}_[a-z0-9_]+\.jsonl\Z")
    cutoff = time.time() - older_than_seconds
    examined = 0
    if not directory.exists() or directory.is_symlink():
        return
    for path in directory.iterdir():
        if not pattern.fullmatch(path.name):
            continue
        examined += 1
        if examined > limit:
            break
        try:
            with _paths_lock:
                if path in _active_paths or path.is_symlink() or path.stat().st_mtime >= cutoff:
                    continue
                with path.open("rb") as handle:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    if os.fstat(handle.fileno()).st_mtime < cutoff:
                        path.unlink(missing_ok=True)
        except (OSError, ValueError):
            # Busy files and unexpected paths are never force-cleaned.
            continue


def _filters(raw):
    if not isinstance(raw, dict):
        raise ValueError("明细筛选必须是对象")
    fields = set(TraceFilter.__dataclass_fields__)
    if raw.keys() - fields:
        raise ValueError("明细筛选包含不支持字段")
    values = dict(raw)
    for key in {"trial_from", "trial_to", "source_from", "source_to", "rarity"} & values.keys():
        if isinstance(values[key], str):
            if not values[key].isascii() or not values[key].isdecimal():
                raise ValueError("明细筛选抽次必须是正整数")
            values[key] = int(values[key])
    if values.get("unnamed_character") in ("true", "false"):
        values["unnamed_character"] = values["unnamed_character"] == "true"
    return TraceFilter(**values)


def _download_data(request):
    # Native form downloads carry CSRF as a form field. JSON is supported for
    # API clients, but the SPA must use a native form rather than a large Blob.
    if request.content_type == "application/json":
        data = _json_body(request)
    else:
        raw = request.POST.get("filters", "{}")
        if len(raw.encode("utf-8")) > 16 * 1024:
            raise ValueError("下载筛选内容过大")
        from lottery_simulator.config_documents import parse_config_json
        data = {"filters": parse_config_json(raw.encode("utf-8"), 16 * 1024)}
    if data.keys() - {"filters"}:
        raise ValueError("下载请求包含不支持字段")
    return _filters(data.get("filters", {}))


def _error(error):
    from dashboard.services.accounts import AccountError
    if isinstance(error, APIError):
        return error_response(error.code, error.message, error.status, error.fields)
    if isinstance(error, AccountError):
        from dashboard.api.pools import _error_response
        return _error_response(error)
    if hasattr(error, "code") and hasattr(error, "status"):
        return error_response(error.code, str(error), error.status)
    if isinstance(error, (ValueError, TypeError)):
        return error_response("validation_error", "下载参数无效，请检查筛选范围", 400)
    if isinstance(error, OSError):
        return error_response("storage_busy", "导出文件写入失败，请检查磁盘空间后重试", 503)
    from dashboard.api.pools import _error_response
    return _error_response(error)


@csrf_protect
def download_trace(request, run_id):
    if request.method != "POST":
        return error_response("validation_error", "明细下载需要POST请求", 405)
    path = None
    admitted = False
    reader_iterator = None
    try:
        from dashboard.services.runs import get_trace_reader_for_actor
        gate = SessionGate(request)
        run = _run(gate, run_id)
        filters = _download_data(request)
        actor = gate.actor()
        reader = get_trace_reader_for_actor(actor, run_id)
        _, count = reader.query_records(filters, limit=50)
        maximum = None if actor.is_superuser else TraceLimits.from_env().max_download_records
        if maximum is not None and count > maximum:
            raise APIError("validation_error", f"下载明细超过普通用户上限{maximum}条，请缩小筛选范围", 400)
        if not _slots.acquire(blocking=False):
            raise APIError("system_busy", "已有下载正在生成或传输，请稍后重试", 409)
        admitted = True
        directory = Path(settings.EXPORTS_DIR)
        if directory.is_symlink():
            raise APIError("storage_busy", "导出目录不安全", 503)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if stat.S_IMODE(directory.stat().st_mode) & 0o077:
            raise APIError("storage_busy", "导出目录权限过宽，请设为仅服务账号可访问", 503)
        cleanup_stale_exports()
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                prefix=f"user_{actor.pk.hex}_run_{UUID(str(run_id)).hex}_", suffix=".jsonl",
                delete=False) as destination:
            fcntl.flock(destination, fcntl.LOCK_EX)
            path = Path(destination.name)
            with _paths_lock:
                _active_paths.add(path)
            metadata = dict(run.result_json)
            destination.write(json.dumps({"type": "metadata", "export_format_version":
                TRACE_EXPORT_FORMAT_VERSION, "run": metadata, "filters": filters.__dict__,
                "matched_record_count": count}, ensure_ascii=False) + "\n")
            reader_iterator = reader.iter_records(filters, batch_size=1000)
            for index, record in enumerate(reader_iterator):
                if index % 1000 == 0:
                    _run(gate, run_id)
                    current_actor = gate.actor()
                    current_max = None if current_actor.is_superuser else TraceLimits.from_env().max_download_records
                    if current_max is not None and count > current_max:
                        raise APIError("forbidden", "当前账号下载限额已变化，请缩小筛选范围", 403)
                destination.write(json.dumps({"type": "record", "record": record}, ensure_ascii=False) + "\n")
            _run(gate, run_id)
            destination.flush()
            os.fsync(destination.fileno())
        reader_iterator.close()
        reader_iterator = None

        def check():
            _run(gate, run_id)
            current = gate.actor()
            maximum = None if current.is_superuser else TraceLimits.from_env().max_download_records
            if maximum is not None and count > maximum:
                raise APIError("forbidden", "账号下载权限已变化", 403)

        stream = DownloadStream(path, check)
        response = StreamingHttpResponse(stream, content_type="application/x-ndjson; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="trace-{UUID(str(run_id)).hex}.jsonl"'
        response["Cache-Control"] = "no-store"
        response["Referrer-Policy"] = "no-referrer"
        admitted = False  # ownership of slot/file transferred to response.close
        path = None
        return response
    except Exception as error:
        return _error(error)
    finally:
        try:
            if reader_iterator is not None:
                reader_iterator.close()
            if path is not None:
                _cleanup(path)
        finally:
            if admitted:
                _slots.release()
