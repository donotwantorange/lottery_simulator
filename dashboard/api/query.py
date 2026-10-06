"""Small helpers for untrusted URL query values."""

from dashboard.api.errors import APIError


def query_integer(value, label):
    if not isinstance(value, str) or not value or len(value) > 1024 or not value.isdecimal():
        raise APIError("validation_error", f"{label}必须是正整数", 400)
    try:
        return int(value)
    except ValueError as error:
        raise APIError("validation_error", f"{label}必须是正整数", 400) from error
