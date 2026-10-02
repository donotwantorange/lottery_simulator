"""Pure result and process-event contracts for the dynamic simulator."""

from collections.abc import Mapping
from dataclasses import dataclass
import math

from lottery_simulator.events import EventCounts
from lottery_simulator.formats import (
    EVENT_FORMAT_VERSION, RESULT_FORMAT_VERSION, RULE_VERSION, require_version,
    sampling_metadata,
)
from lottery_simulator.rules.definitions import (
    ExperimentParameters, boolean, count, normalize_name, number, uuid_text,
)
from lottery_simulator.rules.runtime import DrawState, initial_context


def _json_value(value):
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("结果不能包含非有限数值")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("结果对象的键必须是文本")
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise ValueError(f"结果包含不可序列化类型：{type(value).__name__}")


@dataclass(frozen=True, slots=True)
class DrawOutcome:
    rarity_id: str
    character_id: str | None
    character_name: str | None
    is_up: bool
    is_limited: bool
    rewards: Mapping[str, float]
    pity_status: Mapping

    def to_dict(self):
        return _json_value({name: getattr(self, name) for name in self.__dataclass_fields__})


@dataclass(frozen=True, slots=True)
class DrawResult:
    outcome: DrawOutcome
    probabilities: Mapping[str, float]
    character_probability: float | None
    state_before: DrawState
    state_after: DrawState

    def to_dict(self):
        return _json_value({
            "outcome": self.outcome.to_dict(),
            "probabilities": self.probabilities,
            "character_probability": self.character_probability,
            "state_before": self.state_before.to_dict(),
            "state_after": self.state_after.to_dict(),
        })


@dataclass(frozen=True, slots=True)
class ProcessEvent:
    event_format_version: int
    trial_index: int
    event_index: int
    event_type: str
    main_draws_completed: int
    mechanism_id: str | None
    draw_index: int | None = None
    source: str | None = None
    source_index: int | None = None
    draw_result: DrawResult | None = None
    main_state_before: DrawState | None = None
    main_state_after: DrawState | None = None
    grant: Mapping | None = None

    def to_dict(self):
        require_version(self.event_format_version, EVENT_FORMAT_VERSION, "事件")
        for label, value in (("轮次", self.trial_index), ("事件序号", self.event_index)):
            if type(value) is not int or value < 1:
                raise ValueError(f"{label}必须是正整数")
        if type(self.main_draws_completed) is not int or self.main_draws_completed < 0:
            raise ValueError("主抽累计数必须是非负整数")
        common = {
            "event_format_version": self.event_format_version,
            "trial_index": self.trial_index,
            "event_index": self.event_index,
            "event_type": self.event_type,
            "main_draws_completed": self.main_draws_completed,
            "mechanism_id": self.mechanism_id,
        }
        if self.event_type == "draw":
            if (self.draw_result is None or self.grant is not None or
                    self.source not in ("main", "bonus") or self.draw_index is None or
                    self.source_index is None or self.main_state_before is None or
                    self.main_state_after is None):
                raise ValueError("抽取事件字段不完整或混入赠送字段")
            if (type(self.draw_index) is not int or self.draw_index < 1 or
                    type(self.source_index) is not int or self.source_index < 1):
                raise ValueError("抽取序号必须是正整数")
            common.update({
                "draw_index": self.draw_index,
                "source": self.source,
                "source_index": self.source_index,
                "draw_result": self.draw_result.to_dict(),
                "main_state_before": self.main_state_before.to_dict(),
                "main_state_after": self.main_state_after.to_dict(),
            })
            return _json_value(common)
        if self.event_type == "character_grant":
            if (self.grant is None or self.draw_result is not None or
                    self.source is not None or self.draw_index is not None or
                    self.source_index is not None or self.main_state_before is not None or
                    self.main_state_after is not None):
                raise ValueError("角色赠送事件字段不完整或混入抽取字段")
            grant = _json_value(self.grant)
            required = {"character_id", "rarity_id", "character_name", "is_up",
                        "is_limited", "quantity", "trigger_main_draw"}
            if set(grant) != required:
                raise ValueError("角色赠送事件字段不符合格式")
            grant["character_id"] = uuid_text(grant["character_id"])
            grant["rarity_id"] = uuid_text(grant["rarity_id"])
            grant["character_name"] = normalize_name(grant["character_name"], "角色名称")
            boolean(grant["is_up"], "UP标记")
            boolean(grant["is_limited"], "限定标记")
            count(grant["quantity"], "赠送数量", 1)
            count(grant["trigger_main_draw"], "赠送触发主抽", 1)
            if grant["trigger_main_draw"] != self.main_draws_completed:
                raise ValueError("赠送触发位置与事件主抽累计数不一致")
            common.update({"draw_index": None, "source": None, "source_index": None,
                           "grant": grant})
            return _json_value(common)
        raise ValueError("事件类型无效")


@dataclass(frozen=True, slots=True)
class SimulationResult:
    seed: int
    parameters: ExperimentParameters
    counts: EventCounts
    simulation: Mapping
    theoretical: Mapping | None
    trace_enabled: bool
    event_count: int
    records: tuple[ProcessEvent, ...]


def simulation_payload(result: SimulationResult, compiled, duration_seconds: float,
                       include_events: bool = False) -> dict:
    if not isinstance(result, SimulationResult) or result.theoretical is None:
        raise ValueError("完整结果必须包含理论计算")
    if not all(hasattr(compiled, name) for name in ("rule", "pool", "targets")):
        raise ValueError("编译池快照无效")
    duration_seconds = number(duration_seconds, "运行时长")
    if type(include_events) is not bool:
        raise ValueError("事件包含选项必须是布尔值")
    if include_events and not result.trace_enabled:
        raise ValueError("未开启Trace时不能包含事件")
    if (type(result.seed) is not int or result.parameters.seed != result.seed or
            type(result.event_count) is not int or result.event_count < 0 or
            result.event_count != result.counts.trace_events or
            result.trace_enabled is not result.parameters.trace):
        raise ValueError("实际种子或事件数量无效")
    if not result.trace_enabled and (result.event_count or result.records):
        raise ValueError("未开启Trace的结果不能包含事件")
    if include_events and result.event_count != len(result.records):
        raise ValueError("内存事件数与结果事件数不一致")
    payload = {
        "result_format_version": RESULT_FORMAT_VERSION,
        "event_format_version": EVENT_FORMAT_VERSION,
        "rule_version": RULE_VERSION,
        **sampling_metadata(),
        "duration_seconds": float(duration_seconds),
        "seed": result.seed,
        "parameters": result.parameters.to_dict(),
        "counts": {name: getattr(result.counts, name) for name in result.counts.__dataclass_fields__},
        "trace_enabled": result.trace_enabled,
        "event_count": result.event_count,
        "rule_snapshot": compiled.rule.to_dict(),
        "pool_snapshot": compiled.pool.to_dict(),
        "initial_context": initial_context(compiled).to_dict(),
        "targets": dict(compiled.targets),
        "simulation": _json_value(result.simulation),
        "theoretical": _json_value(result.theoretical),
    }
    if include_events:
        payload["events"] = [record.to_dict() for record in result.records]
    return _json_value(payload)
