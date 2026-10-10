"""Shared seed parsing and JSON serialization limits for web workflows."""

import re
import sys


MAX_WEB_SEED_DIGITS = 4300
_SEED_TEXT = re.compile(r"-?(0|[1-9][0-9]*)\Z")


def effective_seed_digit_limit() -> int:
    """Use the stricter of the web contract and Python's integer conversion limit."""
    python_limit = sys.get_int_max_str_digits()
    return min(MAX_WEB_SEED_DIGITS, python_limit) if python_limit else MAX_WEB_SEED_DIGITS


def _limit_error() -> ValueError:
    limit = effective_seed_digit_limit()
    return ValueError(
        f"随机种子最多允许{limit}位十进制数字（负号不计入）"
    )


def legacy_seed_limit_message(error: ValueError) -> str | None:
    """Describe an older stored integer rejected while a JSONField is decoded."""
    if "Exceeds the limit (" not in str(error) or "integer string conversion" not in str(error):
        return None
    limit = effective_seed_digit_limit()
    return f"随机种子最多允许{limit}位十进制数字（负号不计入）"


def parse_seed_text(text: str) -> int:
    """Parse a canonical signed decimal seed after checking its digit count."""
    if not isinstance(text, str) or not _SEED_TEXT.fullmatch(text):
        raise ValueError("随机种子必须是规范十进制整数或null")
    digits = text[1:] if text.startswith("-") else text
    if len(digits) > effective_seed_digit_limit():
        raise _limit_error()
    try:
        return int(text)
    except ValueError as error:
        # The effective limit normally prevents this; retain a Chinese API error
        # if the interpreter limit changes between checking and conversion.
        raise _limit_error() from error


def validate_web_seed(value: int | None) -> int | None:
    """Validate a parsed seed without converting the integer to decimal text."""
    if value is None:
        return None
    if type(value) is not int:
        raise ValueError("随机种子必须是整数或null")
    if abs(value) >= 10 ** effective_seed_digit_limit():
        raise _limit_error()
    return value
