import platform


# Legacy names remain only until their callers migrate; new contracts do not use them.
CONFIG_FORMAT_VERSION = 2
RULE_FORMAT_VERSION = 1
POOL_FORMAT_VERSION = 3
EXPERIMENT_FORMAT_VERSION = 2
RESULT_FORMAT_VERSION = 4
EVENT_FORMAT_VERSION = 3
RECORD_FORMAT_VERSION = 2
SAMPLING_VERSION = 3
JOB_FORMAT_VERSION = 4
DATABASE_SCHEMA_VERSION = 6
TRACE_STORE_FORMAT_VERSION = 2
TRACE_EXPORT_FORMAT_VERSION = 2
RULE_VERSION = "3.0"


def require_version(value: object, expected: int, label: str) -> None:
    if type(value) is not int or value != expected:
        raise ValueError(f"{label}版本不支持")


def require_readable_sampling_version(value: object) -> None:
    """Accept saved v6 result/Trace snapshots from the two supported samplers."""
    if type(value) is not int or value not in (2, 3):
        raise ValueError("抽样版本不支持")


def sampling_metadata() -> dict[str, int | str]:
    return {
        "sampling_version": SAMPLING_VERSION,
        "rng_algorithm": "python.random.Random",
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
    }
