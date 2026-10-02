"""Versioned task and result payload contracts, independent of Django ORM models."""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar
from uuid import UUID

from lottery_simulator.config_documents import load_pool_document, load_rule_document
from lottery_simulator.rules.definitions import (
    ExperimentParameters, InitialContext, PoolDefinition, RuleDefinition,
)
from lottery_simulator.rules.runtime import compile_pool

from lottery_simulator.formats import JOB_FORMAT_VERSION, SAMPLING_VERSION, require_version
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class RunParameters:
    parameters: ExperimentParameters
    rule_snapshot: RuleDefinition
    pool_snapshot: PoolDefinition
    resolved_targets: Mapping[str, str | None]
    initial_context: InitialContext
    job_format_version: int = JOB_FORMAT_VERSION
    sampling_version: int = SAMPLING_VERSION

    def __post_init__(self):
        if isinstance(self.resolved_targets, Mapping) and not isinstance(self.resolved_targets, MappingProxyType):
            object.__setattr__(self, "resolved_targets", MappingProxyType(dict(self.resolved_targets)))

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RunParameters":
        if not isinstance(raw, dict):
            raise ValueError("任务参数必须是对象")
        require_version(raw.get("job_format_version"), JOB_FORMAT_VERSION, "任务格式")
        require_version(raw.get("sampling_version"), SAMPLING_VERSION, "抽样")
        required = {"job_format_version", "sampling_version", "parameters", "rule_snapshot",
                    "pool_snapshot", "resolved_targets", "initial_context"}
        if set(raw) != required:
            raise ValueError("任务参数字段无效")
        try:
            value = cls(ExperimentParameters.from_dict(raw["parameters"]),
                        load_rule_document(raw["rule_snapshot"]),
                        load_pool_document(raw["pool_snapshot"]), raw["resolved_targets"],
                        InitialContext.from_dict(raw["initial_context"]),
                        raw["job_format_version"], raw["sampling_version"])
            return value.validate()
        except (TypeError, KeyError) as error:
            raise ValueError("任务参数格式无效") from error

    def validate(self) -> "RunParameters":
        require_version(self.job_format_version, JOB_FORMAT_VERSION, "任务格式")
        require_version(self.sampling_version, SAMPLING_VERSION, "抽样")
        if not isinstance(self.parameters, ExperimentParameters):
            raise ValueError("parameters must be ExperimentParameters")
        compiled = compile_pool(self.rule_snapshot, self.pool_snapshot)
        if not isinstance(self.resolved_targets, MappingProxyType) and not isinstance(self.resolved_targets, dict):
            raise ValueError("解析目标格式无效")
        if dict(self.resolved_targets) != dict(compiled.targets):
            raise ValueError("解析目标与冻结规则/池不一致")
        from lottery_simulator.rules.runtime import initial_context, normalize_parameters
        normalized = normalize_parameters(compiled, self.parameters)
        if normalized != self.parameters or self.initial_context != initial_context(compiled):
            raise ValueError("任务参数或初始上下文未规范化")
        return self

    def to_dict(self) -> dict[str, Any]:
        return {"job_format_version": self.job_format_version,
                "sampling_version": self.sampling_version,
                "parameters": self.parameters.to_dict(),
                "rule_snapshot": self.rule_snapshot.to_dict(),
                "pool_snapshot": self.pool_snapshot.to_dict(),
                "resolved_targets": dict(self.resolved_targets),
                "initial_context": self.initial_context.to_dict()}

    @property
    def draws(self): return self.parameters.draws
    @property
    def trials(self): return self.parameters.trials
    @property
    def seed(self): return self.parameters.seed
    @property
    def trace(self): return self.parameters.trace


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
    rule_source: dict[str, Any] | None = None

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
            from dashboard.limits import SimulationLimits
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
            rule = self.rule_source
            if (not isinstance(rule, dict) or set(rule) != {"id", "revision", "name", "author"}
                    or str(UUID(rule["id"])) != rule["id"]
                    or type(rule["revision"]) is not int or rule["revision"] < 1
                    or not isinstance(rule["name"], str) or not rule["name"]
                    or not isinstance(rule["author"], str)):
                raise ValueError("规则来源快照无效")
            limits = SimulationLimits.from_dict(self.limit_policy)
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
            parameters = self.parameters.validate()
        elif isinstance(self.parameters, dict):
            parameters = RunParameters.from_dict(self.parameters)
        else:
            raise ValueError("parameters must be serialized run parameters")
        compiled = compile_pool(parameters.rule_snapshot, parameters.pool_snapshot)
        counts = limits.validate(compiled, parameters.parameters)
        if (parameters.seed is None or parameters.rule_snapshot.id != self.rule_source["id"]
                or parameters.rule_snapshot.name != self.rule_source["name"]
                or parameters.rule_snapshot.original_author != self.rule_source["author"]
                or parameters.pool_snapshot.id != self.pool_source["id"]
                or parameters.pool_snapshot.name != self.pool_source["name"]
                or parameters.pool_snapshot.original_author != self.pool_source["original_author"]
                or parameters.pool_snapshot.rule_ref["id"] != self.rule_source["id"]
                or self.total_units != counts.total_draws + counts.grant_triggers):
            raise ValueError("任务快照或总事件数无效")
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
                or not 0 <= self.phase_completed <= 2**63 - 1
            ):
                raise ValueError("phase_completed must be a non-negative integer")
            if (
                isinstance(self.phase_total, bool)
                or not isinstance(self.phase_total, int)
                or not 0 <= self.phase_total <= 2**63 - 1
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
        if self.history_saved and (self.status != "completed" or self.run_id != self.job_id):
            raise ValueError("已保存历史必须对应本任务")
        if self.run_id is not None:
            try:
                valid_run_id = type(self.run_id) is str and str(UUID(self.run_id)) == self.run_id
            except (ValueError, AttributeError):
                valid_run_id = False
            if not valid_run_id:
                raise ValueError("run_id must be a canonical UUID or None")
        return self

    def to_dict(self) -> dict[str, Any]:
        return {field.name: (getattr(self, field.name).to_dict()
                             if field.name == "parameters" and isinstance(self.parameters, RunParameters)
                             else getattr(self, field.name))
                for field in fields(self)}


def result_payload(result: Any, compiled: Any, duration_seconds: float) -> dict[str, Any]:
    from lottery_simulator.results import simulation_payload
    return simulation_payload(result, compiled, duration_seconds)


def write_json(path: str | os.PathLike[str], value: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent, suffix=".tmp", delete=False
        ) as temporary:
            temporary_name = temporary.name
            json.dump(value, temporary, ensure_ascii=False, allow_nan=False)
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
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("任务JSON包含重复字段")
            result[key] = value
        return result

    def constant(_value):
        raise ValueError("任务JSON不允许非有限数值")

    def floating(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("任务JSON不允许非有限数值")
        return number

    with Path(path).open(encoding="utf-8") as source:
        value = json.load(source, object_pairs_hook=pairs, parse_constant=constant, parse_float=floating)
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value
