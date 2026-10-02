"""Deterministic event counts for a complete experiment."""

from dataclasses import dataclass

from lottery_simulator.rules.definitions import (
    ExperimentParameters, RuleDefinition, count,
)


@dataclass(frozen=True, slots=True)
class EventCounts:
    main_draws: int
    bonus_draws: int
    total_draws: int
    grant_triggers: int
    granted_characters: int
    trace_events: int


def event_counts(rule: RuleDefinition, parameters: ExperimentParameters) -> EventCounts:
    if not isinstance(rule, RuleDefinition) or not isinstance(parameters, ExperimentParameters):
        raise ValueError("需要有效的规则和实验参数")
    start = parameters.initial_main_draws
    end = start + parameters.draws
    bonus = (rule.bonus.draws if rule.bonus.enabled and
             start < rule.bonus.at_main_draw <= end else 0) * parameters.trials
    triggers = ((end // rule.grant.period - start // rule.grant.period)
                if rule.grant.enabled else 0) * parameters.trials
    main = parameters.draws * parameters.trials
    bonus_draws = bonus
    grant_triggers = triggers
    total = main + bonus_draws
    granted = grant_triggers * rule.grant.quantity
    count(total + granted, "获得合计数量上限")
    processed_events = count(total + grant_triggers, "实际处理事件数")
    trace_events = processed_events if parameters.trace else 0
    return EventCounts(
        count(main, "主抽总数"), count(bonus_draws, "赠送抽总数"),
        count(total, "总抽数"), count(grant_triggers, "直接赠送事件数"),
        count(granted, "直接赠送角色数"), count(trace_events, "Trace事件数"),
    )
