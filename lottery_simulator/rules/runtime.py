"""Shared, deterministic kernel for simulation and theoretical transitions."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
import math
from types import MappingProxyType

from lottery_simulator.rules.definitions import (
    ExperimentParameters, InitialContext, PoolDefinition, RuleDefinition,
    boolean, count, id_map, object_fields,
)


@dataclass(frozen=True, slots=True)
class DrawState:
    small_pity: tuple[tuple[str, int], ...] = ()
    big_misses: int = 0
    big_active: bool = False

    def __post_init__(self):
        raw = self.small_pity
        if isinstance(raw, (tuple, list)):
            if any(not isinstance(item, (tuple, list)) or len(item) != 2 or
                   not isinstance(item[0], str) for item in raw):
                raise ValueError("小保底状态必须是ID计数对")
            if len(dict(raw)) != len(raw):
                raise ValueError("小保底状态包含重复ID")
            raw = dict(raw)
        values = id_map(raw, lambda value: count(value, "小保底计数"), "小保底状态")
        object.__setattr__(self, "small_pity", tuple(sorted(values.items())))
        count(self.big_misses, "大保底计数")
        boolean(self.big_active, "大保底有效标记")
        if not self.big_active and self.big_misses:
            raise ValueError("关闭的大保底不能携带非零计数")

    def to_dict(self):
        return {"small_pity": dict(self.small_pity), "big_misses": self.big_misses,
                "big_active": self.big_active}

    @classmethod
    def from_dict(cls, raw):
        data = object_fields(raw, {"small_pity", "big_misses", "big_active"}, "抽取状态")
        if not isinstance(data["small_pity"], dict):
            raise ValueError("小保底状态必须是JSON对象")
        return cls(**data)


@dataclass(frozen=True, slots=True)
class CompiledPool:
    rule: RuleDefinition
    pool: PoolDefinition
    targets: Mapping[str, str | None]

    def __post_init__(self):
        object.__setattr__(self, "targets", MappingProxyType(dict(self.targets)))


def compile_pool(rule: RuleDefinition, pool: PoolDefinition) -> CompiledPool:
    if not isinstance(rule, RuleDefinition) or not isinstance(pool, PoolDefinition):
        raise ValueError("需要有效的规则和池定义")
    if pool.rule_ref["id"] != rule.id:
        raise ValueError("池引用的规则ID与当前规则不一致")
    if {r.id for r in rule.rarities} != {p.rarity_id for p in pool.rarity_pools}:
        raise ValueError("池稀有度ID必须与规则完整对应")
    names = [pool.rarity_labels.get(r.id, r.name) for r in rule.rarities]
    if len(names) != len(set(names)):
        raise ValueError("稀有度最终显示名称不能重复")
    rosters = {p.rarity_id: p for p in pool.rarity_pools}
    characters = {c.id: c for p in pool.rarity_pools for c in p.characters}
    first_up = next((c.id for r in sorted(rule.rarities, key=lambda r: r.rank, reverse=True)
                     for c in rosters[r.id].characters if c.is_up), None)
    targets = {"big_pity": None, "periodic_grant": None}
    for key, policy in (("big_pity", rule.big_pity), ("periodic_grant", rule.grant)):
        if not policy.enabled:
            continue
        target = first_up if policy.target == "first_up" else pool.mechanism_targets.get(key)
        if target not in characters:
            raise ValueError(f"{key}缺少有效的目标角色")
        targets[key] = target
    if rule.big_pity.enabled:
        highest = max(rule.rarities, key=lambda r: r.rank).id
        if characters[targets["big_pity"]].rarity_id != highest:
            raise ValueError("大保底目标必须属于最高稀有度")
    return CompiledPool(rule, pool, targets)


def normalize_parameters(compiled: CompiledPool, raw) -> ExperimentParameters:
    parameters = raw if isinstance(raw, ExperimentParameters) else ExperimentParameters.from_dict(raw)
    history = parameters.initial_main_draws
    supplied = parameters.initial_small_pity
    ids = {r.id for r in compiled.rule.rarities}
    if set(supplied) - ids:
        raise ValueError("小保底初始计数引用未知稀有度")
    small = {r.id: supplied.get(r.id, 0) for r in compiled.rule.rarities}
    lowest_rank = min(r.rank for r in compiled.rule.rarities)
    tracked = sorted((r for r in compiled.rule.rarities if r.soft_enabled or r.hard_enabled),
                     key=lambda r: r.rank)
    for r in compiled.rule.rarities:
        misses = small[r.id]
        if not (r.soft_enabled or r.hard_enabled) and misses:
            raise ValueError("关闭的小保底不能携带非零初始计数")
        if misses > history or (r.rank == lowest_rank and misses):
            raise ValueError("小保底初始计数与历史主抽数矛盾")
        if r.hard_enabled and misses >= r.hard_pity:
            raise ValueError("小保底初始计数已达到硬保底阈值")
    if any(small[low.id] > small[high.id] for low, high in zip(tracked, tracked[1:])):
        raise ValueError("高档未满足数不能小于低档未满足数")
    policy = compiled.rule.big_pity
    big = parameters.initial_big_pity
    active = policy.enabled and not big.target_obtained
    if not policy.enabled:
        if big.target_obtained or big.misses:
            raise ValueError("关闭的大保底要求未获得标记及零计数")
        misses = 0
    elif policy.after_obtain == "disable_after_obtain":
        if big.misses:
            raise ValueError("首次模式的大保底计数必须由历史主抽推导")
        misses = history if active else 0
        if big.target_obtained and history == 0:
            raise ValueError("零历史不能已获得主池目标")
    else:
        if big.target_obtained:
            raise ValueError("循环大保底不能设置此前目标已获得标记")
        misses = big.misses
    if active and (misses > history or misses >= policy.hard_pity):
        raise ValueError("大保底初始计数与历史或阈值矛盾")
    highest = max(compiled.rule.rarities, key=lambda r: r.rank)
    if highest in tracked:
        if active and small[highest.id] > misses:
            raise ValueError("大保底进度不能小于最高档未满足数")
        if policy.enabled and big.target_obtained and small[highest.id] >= history:
            raise ValueError("已获得目标与最高档未满足历史矛盾")
    return replace(parameters, initial_small_pity=small)


def initial_context(compiled: CompiledPool) -> InitialContext:
    policy = compiled.rule.big_pity
    return InitialContext(compiled.rule.id,
                          tuple(r.id for r in sorted(compiled.rule.rarities, key=lambda r: r.rank)),
                          policy.after_obtain if policy.enabled else None,
                          compiled.targets["big_pity"])


def initial_state(compiled: CompiledPool, parameters: ExperimentParameters) -> DrawState:
    parameters = normalize_parameters(compiled, parameters)
    big = parameters.initial_big_pity
    policy = compiled.rule.big_pity
    active = policy.enabled and not big.target_obtained
    misses = (parameters.initial_main_draws if policy.after_obtain == "disable_after_obtain"
              else big.misses) if active else 0
    return DrawState({r.id: parameters.initial_small_pity[r.id] for r in compiled.rule.rarities
                      if r.soft_enabled or r.hard_enabled}, misses, active)


def _validate_state(compiled, state):
    if not isinstance(state, DrawState):
        raise ValueError("抽取状态类型无效")
    small = dict(state.small_pity)
    if set(small) - {r.id for r in compiled.rule.rarities}:
        raise ValueError("抽取状态引用未知稀有度")
    lowest_rank = min(r.rank for r in compiled.rule.rarities)
    for r in compiled.rule.rarities:
        misses = small.get(r.id, 0)
        if not (r.soft_enabled or r.hard_enabled) and misses:
            raise ValueError("关闭的小保底不能携带有效计数")
        if r.rank == lowest_rank and misses:
            raise ValueError("最低档不能携带未满足计数")
        if r.hard_enabled and misses >= r.hard_pity:
            raise ValueError("抽取状态超过小保底阈值")
    if state.big_active and (not compiled.rule.big_pity.enabled or
                             state.big_misses >= compiled.rule.big_pity.hard_pity):
        raise ValueError("抽取状态的大保底无效或超过阈值")
    return small


def pity_status(compiled: CompiledPool, state: DrawState) -> dict:
    small = _validate_state(compiled, state)
    ordered = sorted(compiled.rule.rarities, key=lambda r: r.rank)
    return {
        "soft_active": [r.id for r in ordered if r.soft_enabled and small.get(r.id, 0) + 1 >= r.soft_start],
        "hard_active": [r.id for r in ordered if r.hard_enabled and small.get(r.id, 0) + 1 >= r.hard_pity],
        "big_forced": state.big_active and state.big_misses + 1 >= compiled.rule.big_pity.hard_pity,
    }


def _check_distribution(probabilities):
    if any(not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities.values()) or abs(math.fsum(probabilities.values()) - 1) > 1e-12:
        raise ValueError("运行概率必须非负、有限且合计为1")
    return probabilities


def rarity_probabilities(compiled: CompiledPool, state: DrawState) -> dict[str, float]:
    status = pity_status(compiled, state)
    small = dict(state.small_pity)
    ordered = sorted(compiled.rule.rarities, key=lambda r: r.rank)
    p = {r.id: r.base_probability for r in reversed(ordered)}
    for r in reversed(ordered):
        steps = max(0, small.get(r.id, 0) + 1 - r.soft_start + 1)
        candidate = min(1.0, r.base_probability + r.soft_step * steps) if r.soft_enabled else r.base_probability
        remaining = max(0.0, candidate - r.base_probability)
        for lower in ordered:
            if lower.rank >= r.rank:
                break
            taken = min(remaining, p[lower.id])
            p[lower.id] -= taken
            p[r.id] += taken
            remaining -= taken
    if status["hard_active"]:
        floor = max((r for r in ordered if r.id in status["hard_active"]), key=lambda r: r.rank)
        p[floor.id] = math.fsum([p[floor.id], *(p[r.id] for r in ordered if r.rank < floor.rank)])
        for r in ordered:
            if r.rank < floor.rank:
                p[r.id] = 0.0
        if floor.id == ordered[-1].id:
            p[floor.id] = 1.0
    if status["big_forced"]:
        p = {r.id: float(r.id == ordered[-1].id) for r in reversed(ordered)}
    return _check_distribution(p)


def character_probabilities(compiled: CompiledPool, rarity_id: str, state: DrawState) -> dict[str, float]:
    status = pity_status(compiled, state)
    roster = next((p for p in compiled.pool.rarity_pools if p.rarity_id == rarity_id), None)
    if roster is None:
        raise ValueError("未知稀有度")
    if status["big_forced"] and rarity_id == max(compiled.rule.rarities, key=lambda r: r.rank).id:
        return {compiled.targets["big_pity"]: 1.0}
    if not roster.characters:
        return {}
    p = {c.id: 0.0 for c in roster.characters}
    groups = [(roster.characters, 1.0)]
    if roster.up_enabled:
        groups = [(tuple(c for c in roster.characters if c.is_up), roster.up_share),
                  (tuple(c for c in roster.characters if not c.is_up), 1 - roster.up_share)]
    for characters, share in groups:
        if share == 0:
            continue
        maximum = max(c.weight for c in characters)
        weights = {c.id: c.weight / maximum for c in characters}
        total = math.fsum(weights.values())
        p.update({key: share * weight / total for key, weight in weights.items()})
    return _check_distribution(p)


def advance_state(compiled: CompiledPool, state: DrawState, rarity_id: str,
                  character_id: str | None) -> DrawState:
    probabilities = rarity_probabilities(compiled, state)
    if probabilities.get(rarity_id, 0) <= 0:
        raise ValueError("不能推进零概率或未知稀有度结果")
    characters = character_probabilities(compiled, rarity_id, state)
    if (characters and characters.get(character_id, 0) <= 0) or (not characters and character_id is not None):
        raise ValueError("不能推进零概率或不属于当前档的角色结果")
    rank = next(r.rank for r in compiled.rule.rarities if r.id == rarity_id)
    before = dict(state.small_pity)
    small = {r.id: 0 if r.rank <= rank else before.get(r.id, 0) + 1
             for r in compiled.rule.rarities if r.soft_enabled or r.hard_enabled}
    active = state.big_active
    misses = state.big_misses
    if active:
        if character_id == compiled.targets["big_pity"]:
            misses = 0
            active = compiled.rule.big_pity.after_obtain == "reset_after_obtain"
        else:
            misses += 1
    return DrawState(small, misses, active)


def transition_branches(compiled: CompiledPool, state: DrawState) -> tuple:
    branches = []
    for rarity_id, probability in rarity_probabilities(compiled, state).items():
        if probability <= 0:
            continue
        characters = character_probabilities(compiled, rarity_id, state)
        for character_id, conditional in (characters or {None: 1.0}).items():
            joint = probability * conditional
            if joint > 0:
                branches.append((rarity_id, character_id, joint,
                                 advance_state(compiled, state, rarity_id, character_id)))
    return tuple(branches)
