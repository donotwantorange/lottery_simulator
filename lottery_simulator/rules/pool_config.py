"""Immutable, validated lottery pool configuration."""

from dataclasses import dataclass
import json
import math
from numbers import Real
from pathlib import Path
from typing import Any, Mapping


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


def _probability(value: Any, field: str) -> float:
    number = _finite_number(value, field)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{field} must be between 0 and 1")
    return number


def _non_empty_name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class FiveStarPolicy:
    base_probability: float
    pity_enabled: bool
    hard_pity: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_probability",
                           _probability(self.base_probability, "base_probability"))
        if not isinstance(self.pity_enabled, bool):
            raise ValueError("pity_enabled must be a boolean")
        if isinstance(self.hard_pity, bool) or not isinstance(self.hard_pity, int):
            raise ValueError("hard_pity must be a positive integer")
        if self.hard_pity <= 0:
            raise ValueError("hard_pity must be a positive integer")


@dataclass(frozen=True, slots=True)
class SixStarCharacter:
    name: str
    is_up: bool
    is_limited: bool
    up_weight: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _non_empty_name(self.name, "character name"))
        if not isinstance(self.is_up, bool) or not isinstance(self.is_limited, bool):
            raise ValueError("character flags must be booleans")
        if self.up_weight is not None:
            weight = _finite_number(self.up_weight, "up_weight")
            if weight <= 0:
                raise ValueError("up_weight must be positive")
            object.__setattr__(self, "up_weight", weight)
        if self.is_up:
            if not self.is_limited:
                raise ValueError("UP characters must be limited")
            if self.up_weight is None:
                raise ValueError("UP characters require up_weight")


@dataclass(frozen=True, slots=True)
class RewardRule:
    name: str
    four_star: float
    five_star: float
    six_star: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _non_empty_name(self.name, "reward name"))
        for field in ("four_star", "five_star", "six_star"):
            value = _finite_number(getattr(self, field), field)
            if value < 0:
                raise ValueError(f"{field} must be non-negative")
            object.__setattr__(self, field, value)


@dataclass(frozen=True, slots=True)
class PoolConfig:
    up_share: float
    five_star: FiveStarPolicy
    six_star_characters: tuple[SixStarCharacter, ...]
    rewards: tuple[RewardRule, ...]

    def __post_init__(self) -> None:
        up_share = _probability(self.up_share, "up_share")
        if up_share <= 0:
            raise ValueError("up_share must be greater than 0")
        object.__setattr__(self, "up_share", up_share)
        if not isinstance(self.five_star, FiveStarPolicy):
            raise ValueError("five_star must be a FiveStarPolicy")
        if not isinstance(self.six_star_characters, tuple) or not all(
            isinstance(character, SixStarCharacter)
            for character in self.six_star_characters
        ):
            raise ValueError("six_star_characters must be a tuple of characters")
        if not self.six_star_characters:
            raise ValueError("at least one six-star character is required")
        character_names = [character.name for character in self.six_star_characters]
        if len(character_names) != len(set(character_names)):
            raise ValueError("six-star character names must be unique")
        ups = tuple(character for character in self.six_star_characters if character.is_up)
        if not ups:
            raise ValueError("at least one UP character is required")
        if up_share < 1.0 and len(ups) == len(self.six_star_characters):
            raise ValueError("up_share below 1 requires a non-UP character")
        if not isinstance(self.rewards, tuple) or not all(
            isinstance(reward, RewardRule) for reward in self.rewards
        ):
            raise ValueError("rewards must be a tuple of reward rules")
        reward_names = [reward.name for reward in self.rewards]
        if len(reward_names) != len(set(reward_names)):
            raise ValueError("reward names must be unique")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "PoolConfig":
        if not isinstance(raw, Mapping):
            raise ValueError("pool config must be an object")
        try:
            up_share = raw["up_share"]
            five_star_raw = raw["five_star"]
            characters_raw = raw["six_star_characters"]
            rewards_raw = raw["rewards"]
        except KeyError as error:
            raise ValueError(f"missing pool config field: {error.args[0]}") from error
        if not isinstance(five_star_raw, Mapping):
            raise ValueError("five_star must be an object")
        try:
            five_star = FiveStarPolicy(
                base_probability=five_star_raw["base_probability"],
                pity_enabled=five_star_raw["pity_enabled"],
                hard_pity=five_star_raw["hard_pity"],
            )
        except KeyError as error:
            raise ValueError(f"missing five_star field: {error.args[0]}") from error

        if not isinstance(characters_raw, (list, tuple)):
            raise ValueError("six_star_characters must be a list")
        characters: list[SixStarCharacter] = []
        for index, character_raw in enumerate(characters_raw):
            if not isinstance(character_raw, Mapping):
                raise ValueError(f"six_star_characters[{index}] must be an object")
            try:
                characters.append(SixStarCharacter(
                    name=character_raw["name"],
                    is_up=character_raw["is_up"],
                    is_limited=character_raw["is_limited"],
                    up_weight=character_raw.get("up_weight"),
                ))
            except KeyError as error:
                raise ValueError(
                    f"missing six_star_characters[{index}] field: {error.args[0]}"
                ) from error

        if not isinstance(rewards_raw, (list, tuple)):
            raise ValueError("rewards must be a list")
        rewards: list[RewardRule] = []
        for index, reward_raw in enumerate(rewards_raw):
            if not isinstance(reward_raw, Mapping):
                raise ValueError(f"rewards[{index}] must be an object")
            try:
                rewards.append(RewardRule(
                    name=reward_raw["name"],
                    four_star=reward_raw["four_star"],
                    five_star=reward_raw["five_star"],
                    six_star=reward_raw["six_star"],
                ))
            except KeyError as error:
                raise ValueError(
                    f"missing rewards[{index}] field: {error.args[0]}"
                ) from error
        return cls(up_share, five_star, tuple(characters), tuple(rewards))

    def to_dict(self) -> dict[str, Any]:
        return {
            "up_share": self.up_share,
            "five_star": {
                "base_probability": self.five_star.base_probability,
                "pity_enabled": self.five_star.pity_enabled,
                "hard_pity": self.five_star.hard_pity,
            },
            "six_star_characters": [
                {
                    "name": character.name,
                    "is_up": character.is_up,
                    "is_limited": character.is_limited,
                    "up_weight": character.up_weight,
                }
                for character in self.six_star_characters
            ],
            "rewards": [
                {
                    "name": reward.name,
                    "four_star": reward.four_star,
                    "five_star": reward.five_star,
                    "six_star": reward.six_star,
                }
                for reward in self.rewards
            ],
        }

    def six_star_character_probabilities(self) -> dict[str, float]:
        ups = tuple(character for character in self.six_star_characters if character.is_up)
        non_ups = tuple(character for character in self.six_star_characters if not character.is_up)
        total_up_weight = sum(character.up_weight for character in ups)
        result = {
            character.name: self.up_share * character.up_weight / total_up_weight
            for character in ups
        }
        if non_ups:
            share = (1.0 - self.up_share) / len(non_ups)
            result.update({character.name: share for character in non_ups})
        return result

    def rewards_for(self, rarity: int) -> dict[str, float]:
        field = {4: "four_star", 5: "five_star", 6: "six_star"}[rarity]
        return {reward.name: float(getattr(reward, field)) for reward in self.rewards}


def load_pool_config(path: str | Path | None = None) -> PoolConfig:
    if path is None:
        path = Path(__file__).resolve().parents[2] / "configs" / "rule1_default.json"
    with Path(path).open(encoding="utf-8") as config_file:
        return PoolConfig.from_dict(json.load(config_file))
