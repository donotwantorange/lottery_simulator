from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, ClassVar

from lottery_simulator.analysis import distribution_stats


@dataclass(frozen=True, slots=True)
class RunParameters:
    rule_name: str
    draws: int
    trials: int
    initial_pity: int
    seed: int | None
    trace: bool

    def validate(self) -> "RunParameters":
        if not isinstance(self.rule_name, str) or not self.rule_name:
            raise ValueError("rule_name must be a non-empty string")
        if isinstance(self.draws, bool) or not isinstance(self.draws, int) or self.draws <= 0:
            raise ValueError("draws must be a positive integer")
        if self.draws > 10_000_000:
            raise ValueError("draws 超过上限")
        if isinstance(self.trials, bool) or not isinstance(self.trials, int) or self.trials <= 0:
            raise ValueError("trials must be a positive integer")
        if self.trials > 1_000_000:
            raise ValueError("trials 超过上限")
        if self.draws * self.trials > 100_000_000:
            raise ValueError("draws * trials 超过上限")
        if isinstance(self.initial_pity, bool) or not isinstance(self.initial_pity, int) or self.initial_pity < 0:
            raise ValueError("initial_pity must be a non-negative integer")
        if self.seed is not None and (isinstance(self.seed, bool) or not isinstance(self.seed, int)):
            raise ValueError("seed must be an integer or None")
        if not isinstance(self.trace, bool):
            raise ValueError("trace must be a boolean")
        if self.trace and self.trials != 1:
            raise ValueError("Trace runs require trials=1")
        if self.trace and self.draws > 100_000:
            raise ValueError("Trace draws 超过上限")
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

    _STATUSES: ClassVar[frozenset[str]] = frozenset(
        ("queued", "running", "completed", "cancelled", "failed")
    )

    def validate(self) -> "JobState":
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
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def result_payload(result: Any, rule: Any, duration_seconds: float) -> dict[str, Any]:
    payload = json.loads(json.dumps(asdict(result)))
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
