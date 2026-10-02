"""Pure configuration contracts; runtime probabilities and permissions live elsewhere."""

from collections.abc import Mapping
from dataclasses import dataclass, fields
import math
import unicodedata
from typing import ClassVar
from types import MappingProxyType
from uuid import UUID

from lottery_simulator.formats import (
    EXPERIMENT_FORMAT_VERSION, POOL_FORMAT_VERSION, RULE_FORMAT_VERSION, require_version,
)

MAX_COUNT = 2**63 - 1
ALGORITHM = "dynamic_probability"
BIG_MODES = {"disable_after_obtain", "reset_after_obtain"}
TARGET_MODES = {"first_up", "pool_selected"}


def normalize_name(value, field="名称"):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}必须是非空文本")
    return unicodedata.normalize("NFC", value.strip())


def uuid_text(value):
    try:
        if not isinstance(value, str):
            raise ValueError
        return str(UUID(value))
    except (ValueError, AttributeError):
        raise ValueError("ID必须是UUID字符串") from None


def count(value, label, minimum=0):
    if type(value) is not int or not minimum <= value <= MAX_COUNT:
        raise ValueError(f"{label}必须是可表示的{'正' if minimum else '非负'}整数")
    return value


def number(value, label, minimum=0, maximum=None):
    if type(value) not in (int, float):
        raise ValueError(f"{label}必须是有限数值")
    try:
        value = float(value)
    except OverflowError:
        raise ValueError(f"{label}必须是有限数值") from None
    if not math.isfinite(value) or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{label}数值超出范围或不有限")
    return value


def boolean(value, label):
    if type(value) is not bool:
        raise ValueError(f"{label}必须是布尔值")


def choice(value, choices, label):
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"{label}不支持")


def object_fields(raw, required, label):
    if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
        raise ValueError(f"{label}必须是对象")
    if set(raw) != set(required):
        raise ValueError(f"{label}包含未知字段或缺少必需字段")
    return dict(raw)


def reference(raw):
    if not isinstance(raw, Mapping):
        raise ValueError("资源引用必须是对象")
    raw = object_fields(dict(raw), {"id", "name"}, "资源引用")
    return MappingProxyType({"id": uuid_text(raw["id"]), "name": normalize_name(raw["name"], "引用名称")})


def id_map(raw, convert, label):
    if not isinstance(raw, Mapping):
        raise ValueError(f"{label}必须是ID映射")
    result = {}
    for key, value in raw.items():
        key = uuid_text(key)
        if key in result:
            raise ValueError(f"{label}包含重复ID")
        result[key] = convert(value)
    return MappingProxyType(result)


def unique(items, key, label):
    values = [getattr(item, key) for item in items]
    if len(values) != len(set(values)):
        raise ValueError(f"{label}不能重复")


def typed_items(raw, cls, label):
    if not isinstance(raw, (tuple, list)) or any(not isinstance(item, cls) for item in raw):
        raise ValueError(f"{label}类型无效")
    return tuple(raw)


def decode_items(raw, cls):
    if not isinstance(raw, list):
        raise ValueError("配置列表必须是JSON数组")
    return tuple(cls.from_dict(item) for item in raw)


def rarity_vector(items):
    if not items:
        raise ValueError("规则至少需要一个稀有度")
    for field in ("id", "rank", "name"):
        unique(items, field, f"稀有度{field}")
    if abs(math.fsum(item.base_probability for item in items) - 1) > 1e-12:
        raise ValueError("基础概率合计必须为1")


def _json_lists(value):
    if isinstance(value, ConfigValue):
        return value.to_dict()
    if isinstance(value, (list, tuple)):
        return [_json_lists(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _json_lists(item) for key, item in value.items()}
    return value


def _load(cls, raw, **decoders):
    names = {field.name for field in fields(cls)}
    version = getattr(cls, "format_version", None)
    data = object_fields(raw, names | ({"format_version"} if version is not None else set()), cls.__name__)
    if version is not None:
        require_version(data.pop("format_version"), version, cls.__name__)
    for name, decode in decoders.items():
        data[name] = decode(data[name])
    return cls(**data)


class ConfigValue:
    __slots__ = ()

    @classmethod
    def from_dict(cls, raw):
        return _load(cls, raw)

    def to_dict(self):
        data = {field.name: _json_lists(getattr(self, field.name)) for field in fields(self)}
        version = getattr(self, "format_version", None)
        return {"format_version": version, **data} if version is not None else data


@dataclass(frozen=True, slots=True)
class RarityDefinition(ConfigValue):
    id: str
    name: str
    rank: int
    base_probability: float
    soft_enabled: bool
    soft_start: int
    soft_step: float
    hard_enabled: bool
    hard_pity: int

    def __post_init__(self):
        object.__setattr__(self, "id", uuid_text(self.id))
        object.__setattr__(self, "name", normalize_name(self.name, "稀有度名称"))
        count(self.rank, "稀有度顺序")
        object.__setattr__(self, "base_probability", number(self.base_probability, "基础概率", maximum=1))
        boolean(self.soft_enabled, "软保底开关")
        boolean(self.hard_enabled, "硬保底开关")
        count(self.soft_start, "软保底起点", 1)
        count(self.hard_pity, "硬保底抽数", 1)
        step = number(self.soft_step, "软保底增幅")
        if self.soft_enabled and step == 0:
            raise ValueError("开启软保底时增幅必须为正")
        object.__setattr__(self, "soft_step", step)


@dataclass(frozen=True, slots=True)
class BigPityPolicy(ConfigValue):
    enabled: bool
    hard_pity: int
    target: str
    after_obtain: str

    def __post_init__(self):
        boolean(self.enabled, "大保底开关")
        count(self.hard_pity, "大保底抽数", 1)
        choice(self.target, {"first_up"}, "大保底目标方式")
        choice(self.after_obtain, BIG_MODES, "大保底获得后模式")


@dataclass(frozen=True, slots=True)
class BonusPolicy(ConfigValue):
    enabled: bool
    at_main_draw: int
    draws: int
    rarities: tuple[RarityDefinition, ...]

    def __post_init__(self):
        boolean(self.enabled, "首次赠送开关")
        count(self.at_main_draw, "首次赠送位置", 1)
        count(self.draws, "赠送抽数", 1)
        items = typed_items(self.rarities, RarityDefinition, "赠送稀有度")
        object.__setattr__(self, "rarities", items)
        for field in ("id", "rank", "name"):
            unique(items, field, f"赠送稀有度{field}")
        if self.enabled:
            rarity_vector(items)

    @classmethod
    def from_dict(cls, raw):
        return _load(cls, raw, rarities=lambda values: decode_items(values, RarityDefinition))


@dataclass(frozen=True, slots=True)
class GrantPolicy(ConfigValue):
    enabled: bool
    period: int
    quantity: int
    target: str

    def __post_init__(self):
        boolean(self.enabled, "周期赠送开关")
        count(self.period, "赠送周期", 1)
        count(self.quantity, "赠送数量", 1)
        choice(self.target, TARGET_MODES, "角色赠送目标方式")


@dataclass(frozen=True, slots=True)
class RuleDefinition(ConfigValue):
    format_version: ClassVar[int] = RULE_FORMAT_VERSION
    id: str
    name: str
    original_author: str | None
    algorithm: str
    rarities: tuple[RarityDefinition, ...]
    big_pity: BigPityPolicy
    bonus: BonusPolicy
    grant: GrantPolicy

    def __post_init__(self):
        object.__setattr__(self, "id", uuid_text(self.id))
        object.__setattr__(self, "name", normalize_name(self.name, "规则名称"))
        if self.original_author is not None:
            object.__setattr__(self, "original_author", normalize_name(self.original_author, "作者"))
        choice(self.algorithm, {ALGORITHM}, "算法")
        items = typed_items(self.rarities, RarityDefinition, "主池稀有度")
        object.__setattr__(self, "rarities", items)
        rarity_vector(items)
        for value, cls in ((self.big_pity, BigPityPolicy), (self.bonus, BonusPolicy), (self.grant, GrantPolicy)):
            if not isinstance(value, cls):
                raise ValueError("规则机制类型无效")
        if self.bonus.enabled and {(r.id, r.rank) for r in items} != {(r.id, r.rank) for r in self.bonus.rarities}:
            raise ValueError("赠送稀有度ID及高低顺序必须与主规则一致")

    @classmethod
    def from_dict(cls, raw):
        return _load(cls, raw, rarities=lambda values: decode_items(values, RarityDefinition),
                     big_pity=BigPityPolicy.from_dict, bonus=BonusPolicy.from_dict, grant=GrantPolicy.from_dict)


@dataclass(frozen=True, slots=True)
class CharacterDefinition(ConfigValue):
    id: str
    rarity_id: str
    name: str
    weight: float
    is_up: bool
    is_limited: bool

    def __post_init__(self):
        object.__setattr__(self, "id", uuid_text(self.id))
        object.__setattr__(self, "rarity_id", uuid_text(self.rarity_id))
        object.__setattr__(self, "name", normalize_name(self.name, "角色名称"))
        weight = number(self.weight, "角色权重")
        if weight <= 0:
            raise ValueError("角色权重必须为正")
        object.__setattr__(self, "weight", weight)
        boolean(self.is_up, "UP标记")
        boolean(self.is_limited, "限定标记")
        if self.is_up and not self.is_limited:
            raise ValueError("UP角色必须为限定角色")


@dataclass(frozen=True, slots=True)
class RarityPool(ConfigValue):
    rarity_id: str
    characters: tuple[CharacterDefinition, ...]
    up_enabled: bool
    up_share: float

    def __post_init__(self):
        object.__setattr__(self, "rarity_id", uuid_text(self.rarity_id))
        items = typed_items(self.characters, CharacterDefinition, "角色名单")
        object.__setattr__(self, "characters", items)
        for field in ("id", "name"):
            unique(items, field, f"同档角色{field}")
        if any(item.rarity_id != self.rarity_id for item in items):
            raise ValueError("角色稀有度与所属名单不一致")
        boolean(self.up_enabled, "UP分组开关")
        share = number(self.up_share, "UP占比", maximum=1)
        object.__setattr__(self, "up_share", share)
        if self.up_enabled:
            if not items or (share > 0 and not any(c.is_up for c in items)) or (share < 1 and not any(not c.is_up for c in items)):
                raise ValueError("不能将正概率分配给空角色组")

    @classmethod
    def from_dict(cls, raw):
        return _load(cls, raw, characters=lambda values: decode_items(values, CharacterDefinition))


@dataclass(frozen=True, slots=True)
class RewardDefinition(ConfigValue):
    id: str
    name: str
    amounts: Mapping[str, float]

    def __post_init__(self):
        object.__setattr__(self, "id", uuid_text(self.id))
        object.__setattr__(self, "name", normalize_name(self.name, "奖励名称"))
        object.__setattr__(self, "amounts", id_map(self.amounts, lambda value: number(value, "奖励金额"), "奖励"))


@dataclass(frozen=True, slots=True)
class PoolDefinition(ConfigValue):
    format_version: ClassVar[int] = POOL_FORMAT_VERSION
    id: str
    name: str
    original_author: str | None
    rule_ref: Mapping[str, str]
    rarity_pools: tuple[RarityPool, ...]
    rarity_labels: Mapping[str, str]
    rewards: tuple[RewardDefinition, ...]
    mechanism_targets: Mapping[str, str]

    def __post_init__(self):
        object.__setattr__(self, "id", uuid_text(self.id))
        object.__setattr__(self, "name", normalize_name(self.name, "池名称"))
        if self.original_author is not None:
            object.__setattr__(self, "original_author", normalize_name(self.original_author, "作者"))
        object.__setattr__(self, "rule_ref", reference(self.rule_ref))
        items = typed_items(self.rarity_pools, RarityPool, "池稀有度")
        if not items:
            raise ValueError("池至少需要一个稀有度")
        object.__setattr__(self, "rarity_pools", items)
        unique(items, "rarity_id", "池稀有度ID")
        unique([c for item in items for c in item.characters], "id", "角色ID")
        ids = {item.rarity_id for item in items}
        labels = id_map(self.rarity_labels, lambda value: normalize_name(value, "显示名称"), "稀有度显示名")
        if set(labels) - ids or len(set(labels.values())) != len(labels):
            raise ValueError("稀有度显示名包含未知ID或重复名称")
        object.__setattr__(self, "rarity_labels", labels)
        rewards = typed_items(self.rewards, RewardDefinition, "奖励列表")
        for field in ("id", "name"):
            unique(rewards, field, f"奖励{field}")
        if any(set(reward.amounts) - ids for reward in rewards):
            raise ValueError("奖励引用未知稀有度")
        object.__setattr__(self, "rewards", rewards)
        if not isinstance(self.mechanism_targets, Mapping) or set(self.mechanism_targets) - {"big_pity", "periodic_grant"}:
            raise ValueError("机制目标绑定无效")
        object.__setattr__(self, "mechanism_targets", MappingProxyType({key: uuid_text(value) for key, value in self.mechanism_targets.items()}))

    @classmethod
    def from_dict(cls, raw):
        return _load(cls, raw, rarity_pools=lambda values: decode_items(values, RarityPool),
                     rewards=lambda values: decode_items(values, RewardDefinition))


@dataclass(frozen=True, slots=True)
class BigInitial(ConfigValue):
    target_obtained: bool
    misses: int

    def __post_init__(self):
        boolean(self.target_obtained, "目标已获得标记")
        count(self.misses, "大保底初始计数")


@dataclass(frozen=True, slots=True)
class ExperimentParameters(ConfigValue):
    draws: int
    trials: int
    seed: int | None
    trace: bool
    initial_main_draws: int
    initial_small_pity: Mapping[str, int]
    initial_big_pity: BigInitial

    def __post_init__(self):
        count(self.draws, "每轮主抽数", 1)
        count(self.trials, "轮数", 1)
        count(self.initial_main_draws, "历史主抽数")
        if self.draws * self.trials > MAX_COUNT or self.draws + self.initial_main_draws > MAX_COUNT:
            raise ValueError("总数超过存储可表示范围")
        if self.seed is not None and type(self.seed) is not int:
            raise ValueError("随机种子必须是整数或null")
        boolean(self.trace, "Trace开关")
        object.__setattr__(self, "initial_small_pity", id_map(self.initial_small_pity, lambda value: count(value, "小保底初始计数"), "小保底"))
        if not isinstance(self.initial_big_pity, BigInitial):
            raise ValueError("大保底初始状态类型无效")

    @classmethod
    def from_dict(cls, raw):
        return _load(cls, raw, initial_big_pity=BigInitial.from_dict)


@dataclass(frozen=True, slots=True)
class InitialContext(ConfigValue):
    rule_id: str
    rarity_ids: tuple[str, ...]
    big_mode: str | None
    big_target_id: str | None

    def __post_init__(self):
        object.__setattr__(self, "rule_id", uuid_text(self.rule_id))
        if not isinstance(self.rarity_ids, (list, tuple)) or not self.rarity_ids:
            raise ValueError("初始上下文必须包含稀有度顺序")
        ids = tuple(uuid_text(value) for value in self.rarity_ids)
        if len(ids) != len(set(ids)):
            raise ValueError("初始上下文稀有度ID不能重复")
        object.__setattr__(self, "rarity_ids", ids)
        if self.big_mode is not None:
            choice(self.big_mode, BIG_MODES, "初始大保底模式")
            object.__setattr__(self, "big_target_id", uuid_text(self.big_target_id))
        elif self.big_target_id is not None:
            raise ValueError("关闭大保底的上下文不能携带目标")


@dataclass(frozen=True, slots=True)
class ExperimentDocument(ConfigValue):
    format_version: ClassVar[int] = EXPERIMENT_FORMAT_VERSION
    name: str
    pool_ref: Mapping[str, str]
    parameters: ExperimentParameters
    initial_context: InitialContext | None

    def __post_init__(self):
        object.__setattr__(self, "name", normalize_name(self.name, "实验名称"))
        object.__setattr__(self, "pool_ref", reference(self.pool_ref))
        if not isinstance(self.parameters, ExperimentParameters):
            raise ValueError("实验参数类型无效")
        if self.initial_context is not None and not isinstance(self.initial_context, InitialContext):
            raise ValueError("初始上下文类型无效")

    @classmethod
    def from_dict(cls, raw):
        return _load(cls, raw, parameters=ExperimentParameters.from_dict,
                     initial_context=lambda value: None if value is None else InitialContext.from_dict(value))
