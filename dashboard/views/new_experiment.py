"""The persistent new-experiment draft and its Streamlit view."""

from copy import deepcopy

from dashboard.jobs import JobAlreadyRunning, validate_parameters_for_active_rule
from dashboard.limits import TraceLimits
from dashboard.models import RunParameters
from dashboard.views.configuration import render_pool_config_editor, set_pool_config_editor_state
from dashboard.charts import probability_rows
from lottery_simulator.cli import RULES
from lottery_simulator.rules.base import expected_bonus_draws
from lottery_simulator.rules.pool_config import PoolConfig, load_pool_config


DRAFT_KEY = "new_experiment_draft"
_WIDGET_PREFIX = "_new_experiment_"
_PITY_LABEL = "假设主池已累计多少抽仍未出6星"
_FIVE_STAR_PITY_LABEL = "假设主池已连续多少抽未出5星及以上"


def _default_draft() -> dict:
    return {
        "rule_name": next(iter(RULES)),
        "draws": 100,
        "trials": 1,
        "initial_pity": 0,
        "seed_text": "",
        "trace": False,
        "initial_five_star_pity": 0,
        "pool_config": load_pool_config().to_dict(),
    }


def get_draft(st) -> dict:
    draft = st.session_state.get(DRAFT_KEY)
    if not isinstance(draft, dict):
        draft = _default_draft()
        st.session_state[DRAFT_KEY] = draft
    defaults = _default_draft()
    for key, value in defaults.items():
        draft.setdefault(key, deepcopy(value))
    return draft


def update_draft_from_history(st, run: dict) -> None:
    """Copy a saved snapshot into the page draft without starting it."""
    pool_config = PoolConfig.from_dict(run["pool_config"])
    draft = get_draft(st)
    draft.update(
        rule_name=run["rule_name"],
        draws=run["main_draws"],
        trials=run["trials"],
        initial_pity=run["initial_pity"],
        seed_text=str(run["seed"]),
        trace=run["trace_enabled"],
        initial_five_star_pity=run["initial_five_star_pity"],
        pool_config=pool_config.to_dict(),
    )
    set_pool_config_editor_state(st, pool_config)
    for key in _parameter_keys():
        st.session_state.pop(_widget_key(key), None)


def _parameter_keys():
    return (
        "rule_name", "draws", "trials", "initial_pity", "seed_text", "trace",
        "initial_five_star_pity",
    )


def _widget_key(field: str) -> str:
    return _WIDGET_PREFIX + field


def _sync_widget(st, field: str) -> None:
    draft = get_draft(st)
    draft[field] = st.session_state[_widget_key(field)]


def _prepare_parameter_widgets(st, draft: dict) -> None:
    for field in _parameter_keys():
        key = _widget_key(field)
        if key not in st.session_state:
            st.session_state[key] = draft[field]


def _prepare_config_widgets(st, draft: dict) -> None:
    required = (
        "pool_up_share", "pool_five_star_probability", "pool_five_star_pity_enabled",
        "pool_five_star_hard_pity", "pool_character_rows", "pool_reward_rows",
    )
    # Streamlit may discard widgets which were not rendered on the previous
    # page.  Rehydrate those widgets from the independent draft before asking
    # the editor to render; its data-editor baselines remain stable otherwise.
    if any(key not in st.session_state for key in required):
        set_pool_config_editor_state(st, PoolConfig.from_dict(draft["pool_config"]))


def _preview(st, draft: dict, config: PoolConfig | None) -> None:
    draws, trials, initial_pity = draft["draws"], draft["trials"], draft["initial_pity"]
    bonus = 0
    preview_error = None
    if config is not None:
        try:
            rule = RULES[draft["rule_name"]](config=config)
            bonus = expected_bonus_draws(rule, initial_pity, draws)
        except (KeyError, TypeError, ValueError) as error:
            preview_error = str(error)
    total_per_trial = draws + bonus
    total_main = draws * trials
    total_bonus = bonus * trials
    total_draws = total_main + total_bonus
    trace_count = total_draws if draft["trace"] else 0
    st.subheader("启动预览")
    st.caption(
        f"实验轮数：{trials:,}；每轮主抽：{draws:,}；每轮赠送：{bonus:,}；"
        f"每轮总抽：{total_per_trial:,}"
    )
    st.caption(
        f"实验总主抽：{total_main:,}；实验总赠送：{total_bonus:,}；"
        f"实验总实际抽数：{total_draws:,}"
    )
    st.caption(f"Trace预计记录数：{trace_count:,}（{'启用' if draft['trace'] else '未启用'}）")
    if preview_error:
        st.warning(f"规则预览暂不可用：{preview_error}")
    elif draft["trace"]:
        try:
            over_limit = trace_count > TraceLimits.from_env().max_records
        except ValueError:
            over_limit = True
        if over_limit:
            st.warning("Trace记录数超过上限，启动前会拒绝")


def _validated_parameters(draft: dict, config: PoolConfig | None) -> RunParameters:
    """Build parameters only from the configuration rendered in this run."""
    if config is None:
        raise ValueError("奖池配置无效，请修正后重试")
    seed_text = draft["seed_text"]
    if not isinstance(seed_text, str):
        raise ValueError("随机种子必须为整数")
    try:
        seed = int(seed_text) if seed_text.strip() else None
    except ValueError:
        raise ValueError("随机种子必须为整数") from None
    return validate_parameters_for_active_rule(
        RunParameters(
            draft["rule_name"], draft["draws"], draft["trials"],
            draft["initial_pity"], seed, draft["trace"],
            draft["initial_five_star_pity"], config.to_dict(),
        )
    )


def _render_rule_preview(st, draft: dict, config: PoolConfig | None) -> None:
    if config is None:
        return
    try:
        rule = RULES[draft["rule_name"]](config=config)
        with st.expander("主池规则预览"):
            st.line_chart(
                probability_rows(rule),
                x="抽次",
                y=("条件六星概率", "首次六星累计概率"),
                width="stretch",
            )
            st.caption("横轴为连续未出六星后的下一抽位置；第65/66/80抽为保底边界。")
    except (KeyError, TypeError, ValueError):
        return


def render_new_experiment(st, manager, *, live: bool = False, synchronous: bool = False) -> None:
    """Render the new-experiment page and admit a job when requested."""
    draft = get_draft(st)
    _prepare_parameter_widgets(st, draft)

    st.header("新建实验")
    parameters_column, summary_column = st.columns((2, 1))
    with parameters_column:
        st.selectbox(
            "规则", tuple(RULES), key=_widget_key("rule_name"),
            on_change=_sync_widget, args=(st, "rule_name"),
        )
        draws_column, trials_column = st.columns(2)
        draws_column.number_input(
            "主池抽数", min_value=1, step=1, key=_widget_key("draws"),
            on_change=_sync_widget, args=(st, "draws"),
        )
        trials_column.number_input(
            "实验轮数", min_value=1, step=1, key=_widget_key("trials"),
            on_change=_sync_widget, args=(st, "trials"),
        )
        st.number_input(
            _PITY_LABEL, min_value=0, step=1, key=_widget_key("initial_pity"),
            help="该值同时初始化主池保底位置与累计主池抽数；累计抽数决定首次30抽赠送是已领取还是会在本次模拟中触发。",
            on_change=_sync_widget, args=(st, "initial_pity"),
        )
        st.text_input(
            "随机种子（留空自动生成）", key=_widget_key("seed_text"),
            on_change=_sync_widget, args=(st, "seed_text"),
        )
        st.toggle(
            "保存逐抽明细（Trace）", key=_widget_key("trace"),
            help="按每轮主抽和赠送抽写入逐抽记录；多轮实验可用。",
            on_change=_sync_widget, args=(st, "trace"),
        )
    config = None
    try:
        _prepare_config_widgets(st, draft)
        config = render_pool_config_editor(st)
        draft["pool_config"] = config.to_dict()
    except (KeyError, TypeError, ValueError) as error:
        st.error(str(error))
    with st.expander("高级设置"):
        if not st.session_state.get("pool_five_star_pity_enabled", True):
            draft["initial_five_star_pity"] = 0
            st.session_state[_widget_key("initial_five_star_pity")] = 0
        if _widget_key("initial_five_star_pity") not in st.session_state:
            st.session_state[_widget_key("initial_five_star_pity")] = draft["initial_five_star_pity"]
        st.number_input(
            _FIVE_STAR_PITY_LABEL, min_value=0, step=1,
            disabled=not st.session_state.get("pool_five_star_pity_enabled", True),
            key=_widget_key("initial_five_star_pity"),
            on_change=_sync_widget, args=(st, "initial_five_star_pity"),
        )
    # Callback state is authoritative after each rerun; this also handles
    # AppTest and custom Streamlit hosts which alter several cells together.
    for field in _parameter_keys():
        draft[field] = st.session_state[_widget_key(field)]
    try:
        parameters = _validated_parameters(draft, config)
        start_error = None
    except (AttributeError, TypeError, ValueError) as error:
        parameters = None
        start_error = str(error)
    with summary_column:
        _preview(st, draft, config)
        if start_error:
            st.error(start_error)
        start_requested = st.button("开始模拟", disabled=live or start_error is not None)
    _render_rule_preview(st, draft, config)

    if start_requested and parameters is not None:
        try:
            state = manager.start(parameters, synchronous=synchronous)
        except JobAlreadyRunning:
            st.error("已有模拟任务正在运行")
        except Exception:
            st.error("模拟任务启动失败")
        else:
            st.session_state["current_job_id"] = state.job_id
            st.session_state["selected_result"] = ("job", state.job_id)
            # The navigation radio is already instantiated in this run; defer
            # its value change until the next script start.
            st.session_state["_pending_page"] = "实验结果"
            st.rerun()
