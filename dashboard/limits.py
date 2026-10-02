import os
import re
from dataclasses import asdict, dataclass


_POSITIVE_INTEGER = re.compile(r"0*[1-9][0-9]*\Z")


def _validate_limits(policy):
    for name in policy.__dataclass_fields__:
        value = getattr(policy, name)
        if value is None and name != "batch_size":
            continue
        if type(value) is not int or value <= 0:
            raise ValueError("限额必须是正整数或null，批大小必须是正整数")


def _read_positive_integer(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    if not isinstance(value, str) or _POSITIVE_INTEGER.fullmatch(value) is None:
        raise ValueError(f"{name} must be a positive integer string")
    return int(value)


@dataclass(frozen=True)
class TraceLimits:
    max_records: int | None = 1_000_000
    max_download_records: int | None = 10_000
    batch_size: int = 1000

    def __post_init__(self):
        _validate_limits(self)

    @classmethod
    def from_env(cls) -> "TraceLimits":
        return cls(
            max_records=_read_positive_integer(
                "LOTTERY_MAX_TRACE_RECORDS", cls.max_records
            ),
            max_download_records=_read_positive_integer(
                "LOTTERY_MAX_TRACE_DOWNLOAD_RECORDS", cls.max_download_records
            ),
        )

    @classmethod
    def for_actor(cls, actor):
        return cls(max_records=None, max_download_records=None) if actor.is_superuser else cls.from_env()


@dataclass(frozen=True)
class SimulationLimits:
    max_draws: int | None = 10_000_000
    max_trials: int | None = 1_000_000
    max_main_draws: int | None = 100_000_000
    max_records: int | None = 1_000_000
    max_download_records: int | None = 10_000
    batch_size: int = 1000

    def __post_init__(self):
        _validate_limits(self)

    @classmethod
    def for_actor(cls, actor):
        trace = TraceLimits.for_actor(actor)
        return cls(None, None, None, None, None) if actor.is_superuser else cls(
            max_records=trace.max_records, max_download_records=trace.max_download_records,
        )

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("接受时限额快照无效")
        return cls(**value)

    def to_dict(self):
        return asdict(self)

    def trace_limits(self):
        return TraceLimits(self.max_records, self.max_download_records, self.batch_size)

    def validate(self, compiled, parameters):
        """Bound accepted work and stored events using the frozen rule."""
        from lottery_simulator.events import event_counts
        from lottery_simulator.rules.runtime import normalize_parameters
        parameters = normalize_parameters(compiled, parameters)
        counts = event_counts(compiled.rule, parameters)
        for value, upper, label in (
            (parameters.draws, self.max_draws, "每轮主抽"),
            (parameters.trials, self.max_trials, "轮数"),
            (counts.main_draws, self.max_main_draws, "主抽总数"),
            (counts.trace_events, self.max_records if parameters.trace else None, "Trace事件数"),
        ):
            if upper is not None and value > upper:
                raise ValueError(f"{label}超过上限")
        return counts
