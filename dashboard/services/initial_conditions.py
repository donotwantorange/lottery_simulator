"""Initial-condition context checks shared by experiment and run services."""

from lottery_simulator.rules.definitions import ExperimentParameters, InitialContext
from lottery_simulator.rules.runtime import initial_context, normalize_parameters


def build_initial_context(compiled):
    return initial_context(compiled).to_dict()


def _is_zero(parameters):
    value = parameters if isinstance(parameters, ExperimentParameters) else ExperimentParameters.from_dict(parameters)
    return (value.initial_main_draws == 0 and not any(value.initial_small_pity.values())
            and not value.initial_big_pity.target_obtained and value.initial_big_pity.misses == 0)


def require_initial_context(compiled, parameters, context):
    normalized = normalize_parameters(compiled, parameters)
    current = initial_context(compiled)
    if _is_zero(normalized):
        if context is not None and (context if isinstance(context, InitialContext)
                                    else InitialContext.from_dict(context)) != current:
            raise ValueError("规则、稀有度顺序或大保底目标已变化，请重新确认初始条件")
        return normalized
    if context is None:
        raise ValueError("非零初始条件需要确认当前规则上下文")
    supplied = context if isinstance(context, InitialContext) else InitialContext.from_dict(context)
    if supplied != current:
        raise ValueError("规则、稀有度顺序或大保底目标已变化，请重新确认初始条件")
    return normalized
