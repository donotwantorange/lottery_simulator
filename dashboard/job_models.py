"""Legacy task and result payload contracts, independent of Django ORM models."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar
from uuid import UUID

from lottery_simulator.analysis import distribution_stats
from lottery_simulator.formats import (
    JOB_FORMAT_VERSION,
    RESULT_FORMAT_VERSION,
    SAMPLING_VERSION,
    require_version,
    sampling_metadata,
)


@dataclass(frozen=True, slots=True)
class RunParameters:
    rule_name: str
    draws: int
    trials: int
    initial_pity: int
    seed: int | None
    trace: bool
    initial_five_star_pity: int = 0
    pool_config: dict[str, Any] | None = None
    job_format_version: int = JOB_FORMAT_VERSION
    sampling_version: int = SAMPLING_VERSION

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RunParameters":
        if not isinstance(raw, dict):
            raise ValueError("任务参数必须是对象")
        require_version(raw.get("job_format_version"), JOB_FORMAT_VERSION, "任务格式")
        require_version(raw.get("sampling_version"), SAMPLING_VERSION, "抽样")
        try:
            return cls(**raw).validate()
        except TypeError as error:
            raise ValueError("任务参数格式无效") from error

    def validate(self) -> "RunParameters":
        require_version(self.job_format_version, JOB_FORMAT_VERSION, "任务格式")
        require_version(self.sampling_version, SAMPLING_VERSION, "抽样")
        if not isinstance(self.rule_name, str) or not self.rule_name:
            raise ValueError("rule_name must be a non-empty string")
        if isinstance(self.draws, bool) or not isinstance(self.draws, int) or self.draws <= 0:
            raise ValueError("draws must be a positive integer")
        if isinstance(self.trials, bool) or not isinstance(self.trials, int) or self.trials <= 0:
            raise ValueError("trials must be a positive integer")
        if self.draws * self.trials > 2**63 - 1:
            raise ValueError("主抽计数超过存储可表示范围")
        if isinstance(self.initial_pity, bool) or not isinstance(self.initial_pity, int) or self.initial_pity < 0:
            raise ValueError("initial_pity must be a non-negative integer")
        if (isinstance(self.initial_five_star_pity, bool)
                or not isinstance(self.initial_five_star_pity, int)
                or self.initial_five_star_pity < 0):
            raise ValueError("initial_five_star_pity must be a non-negative integer")
        if self.pool_config is not None and not isinstance(self.pool_config, dict):
            raise ValueError("pool_config must be a dictionary or None")
        if self.seed is not None and (isinstance(self.seed, bool) or not isinstance(self.seed, int)):
            raise ValueError("seed must be an integer or None")
        if not isinstance(self.trace, bool):
            raise ValueError("trace must be a boolean")
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class JobState:
    job_id: str
    status: str
    parameters: RunParameters | dict[str, Any]
    completed_units: int
    total_units: int
    pid: int | None = None
    started_at: str | None = None
    updated_at: str | None = None
    duration_seconds: float | None = None
    error: str | None = None
    result_path: str | None = None
    persistence_error: str | None = None
    phase: str | None = None
    history_saved: bool = False
    run_id: str | None = None
    job_format_version: int = JOB_FORMAT_VERSION
    sampling_version: int = SAMPLING_VERSION
    phase_completed: int | None = None
    phase_total: int | None = None
    cancel_requested: bool = False
    cleanup_error: str | None = None
    owner_id: str | None = None
    accepted_at: str | None = None
    pool_source: dict[str, Any] | None = None
    limit_policy: dict[str, Any] | None = None

    _STATUSES: ClassVar[frozenset[str]] = frozenset(
        ("queued", "running", "completed", "cancelled", "failed")
    )

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "JobState":
        if not isinstance(raw, dict):
            raise ValueError("任务状态必须是对象")
        require_version(raw.get("job_format_version"), JOB_FORMAT_VERSION, "任务格式")
        require_version(raw.get("sampling_version"), SAMPLING_VERSION, "抽样")
        try:
            return cls(**raw).validate()
        except TypeError as error:
            raise ValueError("任务状态格式无效") from error

    def validate(self) -> "JobState":
        require_version(self.job_format_version, JOB_FORMAT_VERSION, "任务格式")
        require_version(self.sampling_version, SAMPLING_VERSION, "抽样")
        try:
            if type(self.owner_id) is not str or str(UUID(self.owner_id)) != self.owner_id:
                raise ValueError("任务归属无效")
            accepted = datetime.fromisoformat(self.accepted_at)
            if accepted.tzinfo is None:
                raise ValueError("任务接受时间无效")
            source = self.pool_source
            if (not isinstance(source, dict) or set(source) != {
                    "id", "revision", "name", "original_author"}
                    or str(UUID(source["id"])) != source["id"]
                    or type(source["revision"]) is not int or source["revision"] < 1
                    or not isinstance(source["name"], str) or not source["name"]
                    or not isinstance(source["original_author"], str)):
                raise ValueError("池来源快照无效")
            from dashboard.limits import SimulationLimits
            SimulationLimits.from_dict(self.limit_policy)
        except (TypeError, KeyError, AttributeError) as error:
            raise ValueError("任务接受快照无效") from error
        if self.status not in self._STATUSES:
            raise ValueError("status must be one of queued/running/completed/cancelled/failed")
        if isinstance(self.completed_units, bool) or not isinstance(self.completed_units, int) or self.completed_units < 0:
            raise ValueError("completed_units must be a non-negative integer")
        if isinstance(self.total_units, bool) or not isinstance(self.total_units, int) or self.total_units < 0:
            raise ValueError("total_units must be a non-negative integer")
        if self.completed_units > self.total_units:
            raise ValueError("completed_units cannot exceed total_units")
        if isinstance(self.parameters, RunParameters):
            self.parameters.validate()
        elif isinstance(self.parameters, dict):
            RunParameters.from_dict(self.parameters)
        else:
            raise ValueError("parameters must be serialized run parameters")
        if self.phase not in (
            None, "simulating", "theory", "validating", "saving", "committing"
        ):
            raise ValueError(
                "phase must be simulating, theory, validating, saving, committing or None"
            )
        if (self.phase_completed is None) != (self.phase_total is None):
            raise ValueError("phase_completed and phase_total must be provided together")
        if self.phase_completed is not None:
            if (
                isinstance(self.phase_completed, bool)
                or not isinstance(self.phase_completed, int)
                or self.phase_completed < 0
            ):
                raise ValueError("phase_completed must be a non-negative integer")
            if (
                isinstance(self.phase_total, bool)
                or not isinstance(self.phase_total, int)
                or self.phase_total < 0
            ):
                raise ValueError("phase_total must be a non-negative integer")
            if self.phase_completed > self.phase_total:
                raise ValueError("phase_completed cannot exceed phase_total")
        if type(self.cancel_requested) is not bool:
            raise ValueError("cancel_requested must be a boolean")
        if self.cleanup_error is not None and not isinstance(self.cleanup_error, str):
            raise ValueError("cleanup_error must be a string or None")
        if type(self.history_saved) is not bool:
            raise ValueError("history_saved must be a boolean")
        if self.run_id is not None:
            try:
                valid_run_id = type(self.run_id) is str and str(UUID(self.run_id)) == self.run_id
            except (ValueError, AttributeError):
                valid_run_id = False
            if not valid_run_id:
                raise ValueError("run_id must be a canonical UUID or None")
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def result_payload(result: Any, rule: Any, duration_seconds: float) -> dict[str, Any]:
    payload = json.loads(json.dumps(asdict(result)))
    payload.pop("records")
    payload["result_format_version"] = RESULT_FORMAT_VERSION
    payload.update(sampling_metadata())
    mean_count_error = result.mean_six_stars - result.theoretical_expected_count
    payload["rule_version"] = rule.version
    payload["main_draws"] = result.draws
    payload["theoretical_mean_interval"] = distribution_stats(rule).mean
    payload["mean_count_error"] = mean_count_error
    payload["mean_count_relative_error"] = (
        mean_count_error / result.theoretical_expected_count
        if result.theoretical_expected_count != 0.0
        else None
    )
    payload["duration_seconds"] = duration_seconds
    return payload


def write_json(path: str | os.PathLike[str], value: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent, suffix=".tmp", delete=False
        ) as temporary:
            temporary_name = temporary.name
            json.dump(value, temporary, ensure_ascii=False)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, target)
        temporary_name = None
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def read_json(path: str | os.PathLike[str]) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value
