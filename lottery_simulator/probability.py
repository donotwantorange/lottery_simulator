import math
from collections.abc import Sequence
from numbers import Real
from typing import TypeVar


T = TypeVar("T")


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label}必须是有限数值")
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{label}必须是有限数值") from error
    if not math.isfinite(converted):
        raise ValueError(f"{label}必须是有限数值")
    return converted


def normalize_probabilities(probabilities: Sequence[float]) -> tuple[float, ...]:
    """Validate and close a tolerated rounding tail on an existing positive entry."""
    values = [_finite_number(value, "概率") for value in probabilities]
    if not values:
        raise ValueError("分布不能为空")
    if any(not 0.0 <= value <= 1.0 for value in values):
        raise ValueError("概率必须在[0, 1]内")
    total = math.fsum(values)
    if abs(total - 1.0) > 1e-12:
        raise ValueError("概率总和必须为1")
    if total == 1.0:
        return tuple(values)

    # Prefer the last positive option, matching the old sampling tail. If it
    # cannot absorb an excess, move left without making a tiny option negative.
    for index in range(len(values) - 1, -1, -1):
        if values[index] <= 0.0:
            continue
        adjusted = 1.0 - math.fsum(value for offset, value in enumerate(values)
                                   if offset != index)
        if adjusted > 0.0 and adjusted <= 1.0:
            values[index] = adjusted
            if math.fsum(values) == 1.0:
                return tuple(values)
    raise ValueError("概率尾差无法归一化")


def sample_distribution(
    distribution: Sequence[tuple[T, float]], roll: float,
) -> T:
    try:
        entries = list(distribution)
    except (TypeError, ValueError) as error:
        raise ValueError("分布必须是非空序列") from error
    if not entries:
        raise ValueError("分布不能为空")

    validated: list[tuple[T, float]] = []
    seen: set[T] = set()
    for entry in entries:
        try:
            item, raw_probability = entry
        except (TypeError, ValueError) as error:
            raise ValueError("分布选项必须是二元组") from error
        if type(item) not in (int, str):
            raise ValueError("分布选项必须是整数或字符串")
        if item in seen:
            raise ValueError("分布选项不能重复")
        seen.add(item)
        probability = _finite_number(raw_probability, "概率")
        if not 0.0 <= probability <= 1.0:
            raise ValueError("概率必须在[0, 1]内")
        validated.append((item, probability))

    normalized = normalize_probabilities([probability for _, probability in validated])
    validated = [(item, probability) for (item, _), probability in zip(validated, normalized)]

    converted_roll = _finite_number(roll, "roll")
    if not 0.0 <= converted_roll < 1.0:
        raise ValueError("roll必须是[0, 1)内的有限数值")

    cumulative = 0.0
    last_positive: T | None = None
    for item, probability in validated:
        if probability == 0.0:
            continue
        last_positive = item
        cumulative += probability
        if converted_roll < cumulative:
            return item
    if last_positive is None:
        raise ValueError("分布必须包含正概率选项")
    return last_positive
