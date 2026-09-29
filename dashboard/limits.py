import os
import re
from dataclasses import asdict, dataclass


_POSITIVE_INTEGER = re.compile(r"0*[1-9][0-9]*\Z")


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
        policy = cls(**value)
        for name, limit in value.items():
            if limit is None and name != "batch_size":
                continue
            if type(limit) is not int or limit <= 0:
                raise ValueError("接受时限额快照无效")
        return policy

    def to_dict(self):
        return asdict(self)

    def trace_limits(self):
        return TraceLimits(self.max_records, self.max_download_records, self.batch_size)
