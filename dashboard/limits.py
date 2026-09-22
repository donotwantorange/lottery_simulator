import os
import re
from dataclasses import dataclass


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
    max_records: int = 1_000_000
    max_download_records: int = 10_000
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
