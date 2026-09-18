import platform


CONFIG_FORMAT_VERSION = 1
RESULT_FORMAT_VERSION = 1
RECORD_FORMAT_VERSION = 1
SAMPLING_VERSION = 1
JOB_FORMAT_VERSION = 1
DATABASE_SCHEMA_VERSION = 3


def require_version(value: object, expected: int, label: str) -> None:
    if type(value) is not int or value != expected:
        raise ValueError(f"{label}版本不支持")


def sampling_metadata() -> dict[str, int | str]:
    return {
        "sampling_version": SAMPLING_VERSION,
        "rng_algorithm": "python.random.Random",
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
    }
