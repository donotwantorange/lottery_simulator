"""Shared fixtures loaded from the single source of default configuration."""

from dataclasses import replace

from lottery_simulator.config_documents import (
    DEFAULT_EXPERIMENT_PATH, DEFAULT_POOL_PATH, DEFAULT_RULE_PATH,
    load_experiment_document, load_pool_document, load_rule_document, read_config_json,
)
from lottery_simulator.rules.runtime import compile_pool
from lottery_simulator.rules.definitions import (
    BigPityPolicy, BonusPolicy, GrantPolicy,
)


def default_rule():
    return load_rule_document(read_config_json(DEFAULT_RULE_PATH))


def default_pool():
    return load_pool_document(read_config_json(DEFAULT_POOL_PATH))


def default_parameters(**overrides):
    parameters = load_experiment_document(read_config_json(DEFAULT_EXPERIMENT_PATH)).parameters
    return replace(parameters, **overrides)


def make_default_compiled():
    return compile_pool(default_rule(), default_pool())


def deterministic_target_compiled(threshold=3, after_obtain="disable_after_obtain"):
    """A two-tier rule whose high-tier draw always selects its UP target."""
    rule, pool = default_rule(), default_pool()
    low, _, high = sorted(rule.rarities, key=lambda item: item.rank)
    rarities = (replace(low, base_probability=1.0, soft_enabled=False, hard_enabled=False),
                replace(high, base_probability=0.0, soft_enabled=False, hard_enabled=False))
    rule = replace(rule, rarities=rarities,
                   big_pity=BigPityPolicy(True, threshold, "first_up", after_obtain),
                   bonus=BonusPolicy(False, 30, 10, ()),
                   grant=GrantPolicy(False, 240, 1, "first_up"))
    rosters = tuple(item for item in pool.rarity_pools if item.rarity_id in {low.id, high.id})
    rewards = tuple(replace(item, amounts={key: value for key, value in item.amounts.items()
                                           if key in {low.id, high.id}})
                    for item in pool.rewards)
    pool = replace(pool, rarity_pools=rosters,
                   rarity_labels={key: value for key, value in pool.rarity_labels.items()
                                  if key in {low.id, high.id}},
                   rewards=rewards, mechanism_targets={})
    return compile_pool(rule, pool)


def character_id(compiled, name):
    matches = [character.id for item in compiled.pool.rarity_pools
               for character in item.characters if character.name == name]
    if len(matches) != 1:
        raise ValueError("夹具角色名称必须唯一")
    return matches[0]
