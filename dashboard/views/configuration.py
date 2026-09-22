"""Pool configuration editing helpers for the Streamlit dashboard."""

import json
from collections.abc import Sequence

import pandas as pd

from lottery_simulator.rules.pool_config import (
    PoolConfig,
    WeightedCharacter,
    load_pool_config,
)
from lottery_simulator.formats import CONFIG_FORMAT_VERSION


_REWARD_COLUMNS = ("奖励名称", "四星", "五星", "六星")


def config_to_editor_rows(config: PoolConfig):
    characters = [
        {
            "角色名称": character.name,
            "是否UP": character.is_up,
            "是否限定": character.is_limited,
            "UP权重": character.up_weight,
        }
        for character in config.six_star_characters
    ]
    rewards = [
        {
            "奖励名称": reward.name,
            "四星": reward.four_star,
            "五星": reward.five_star,
            "六星": reward.six_star,
        }
        for reward in config.rewards
    ]
    return characters, rewards


def editor_rows_to_config(
    *,
    up_share,
    five_star_probability,
    five_star_pity_enabled,
    five_star_hard_pity,
    character_rows,
    reward_rows,
    four_star_characters: Sequence[WeightedCharacter] = (),
    five_star_characters: Sequence[WeightedCharacter] = (),
):
    return PoolConfig.from_dict({
        "format_version": CONFIG_FORMAT_VERSION,
        "up_share": up_share,
        "five_star": {
            "base_probability": five_star_probability,
            "pity_enabled": five_star_pity_enabled,
            "hard_pity": five_star_hard_pity,
        },
        "six_star_characters": [
            {
                "name": row["角色名称"],
                "is_up": row["是否UP"],
                "is_limited": row["是否限定"],
                "up_weight": row["UP权重"] if row["是否UP"] else None,
            }
            for row in character_rows
        ],
        "four_star_characters": [
            {"name": character.name, "weight": character.weight}
            for character in four_star_characters
        ],
        "five_star_characters": [
            {"name": character.name, "weight": character.weight}
            for character in five_star_characters
        ],
        "rewards": [
            {
                "name": row["奖励名称"],
                "four_star": row["四星"],
                "five_star": row["五星"],
                "six_star": row["六星"],
            }
            for row in reward_rows
        ],
    })


def pool_config_from_json(payload: bytes | str) -> PoolConfig:
    try:
        text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        return PoolConfig.from_dict(json.loads(text))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        raise ValueError("配置 JSON 无效：请检查 UTF-8 编码、格式与内容") from None


def pool_config_to_json(config: PoolConfig) -> bytes:
    return (json.dumps(config.to_dict(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def set_pool_config_editor_state(st, config: PoolConfig) -> None:
    characters, rewards = config_to_editor_rows(config)
    # ``new_experiment_draft`` is deliberately independent from Streamlit's
    # widget state.  Keep an explicit import/default/history reset visible to
    # the page draft before a rerun removes the temporary editor widgets.
    draft = st.session_state.get("new_experiment_draft")
    if isinstance(draft, dict):
        draft["pool_config"] = config.to_dict()
    st.session_state.update(
        pool_up_share=config.up_share,
        pool_five_star_probability=config.five_star.base_probability,
        pool_five_star_pity_enabled=config.five_star.pity_enabled,
        pool_five_star_hard_pity=config.five_star.hard_pity,
        pool_character_rows=characters,
        pool_four_star_characters=config.four_star_characters,
        pool_five_star_characters=config.five_star_characters,
        pool_reward_rows=rewards,
    )
    st.session_state.pop("pool_character_editor", None)
    st.session_state.pop("pool_reward_editor", None)


def render_pool_config_editor(st) -> PoolConfig:
    if "pool_character_rows" not in st.session_state:
        set_pool_config_editor_state(st, load_pool_config())

    with st.expander("奖池与奖励设置"):
        uploaded = st.file_uploader("导入配置 JSON", type=("json",), key="pool_config_upload")
        if st.button("恢复默认配置"):
            set_pool_config_editor_state(st, load_pool_config())
            st.session_state["pool_config_imported_file_id"] = (
                uploaded.file_id if uploaded is not None else None
            )
            st.rerun()
        if (
            uploaded is not None
            and uploaded.file_id != st.session_state.get("pool_config_imported_file_id")
        ):
            imported = pool_config_from_json(uploaded.getvalue())
            set_pool_config_editor_state(st, imported)
            st.session_state["pool_config_imported_file_id"] = uploaded.file_id
            st.rerun()

        up_share = st.number_input(
            "UP占比", min_value=0.0, max_value=1.0, step=0.01, key="pool_up_share"
        )
        five_star_probability = st.number_input(
            "五星概率", min_value=0.0, max_value=1.0, step=0.01,
            key="pool_five_star_probability",
        )
        five_star_pity_enabled = st.toggle(
            "启用五星保底", key="pool_five_star_pity_enabled"
        )
        five_star_hard_pity = st.number_input(
            "五星硬保底", min_value=1, step=1, key="pool_five_star_hard_pity"
        )
        st.caption(
            "四星名单：{}人；五星名单：{}人（通过JSON编辑）".format(
                len(st.session_state["pool_four_star_characters"]),
                len(st.session_state["pool_five_star_characters"]),
            )
        )
        character_rows = st.data_editor(
            st.session_state["pool_character_rows"], num_rows="dynamic",
            key="pool_character_editor",
        )
        reward_editor_data = st.session_state["pool_reward_rows"] or pd.DataFrame({
            "奖励名称": pd.Series(dtype="string"),
            "四星": pd.Series(dtype="float64"),
            "五星": pd.Series(dtype="float64"),
            "六星": pd.Series(dtype="float64"),
        })
        reward_rows = st.data_editor(
            reward_editor_data, num_rows="dynamic",
            key="pool_reward_editor",
            column_config={
                "奖励名称": st.column_config.TextColumn(),
                "四星": st.column_config.NumberColumn(min_value=0),
                "五星": st.column_config.NumberColumn(min_value=0),
                "六星": st.column_config.NumberColumn(min_value=0),
            },
        )
        if isinstance(reward_rows, pd.DataFrame):
            reward_rows = reward_rows.to_dict("records")
        elif isinstance(reward_rows, dict):
            reward_rows = [
                dict(zip(_REWARD_COLUMNS, values))
                for values in zip(*(reward_rows[column] for column in _REWARD_COLUMNS))
            ]
        # Dynamic editor identity includes input data: keep its baseline stable.
        # Only explicit import/default/history resets replace that baseline.
        try:
            config = editor_rows_to_config(
                up_share=up_share,
                five_star_probability=five_star_probability,
                five_star_pity_enabled=five_star_pity_enabled,
                five_star_hard_pity=five_star_hard_pity,
                character_rows=character_rows,
                reward_rows=reward_rows,
                four_star_characters=st.session_state["pool_four_star_characters"],
                five_star_characters=st.session_state["pool_five_star_characters"],
            )
        except (KeyError, TypeError, ValueError):
            raise ValueError("奖池配置无效：请检查概率、角色、权重、奖励和保底设置") from None
        st.download_button(
            "导出配置 JSON", data=pool_config_to_json(config),
            file_name="rule1-pool-config.json", mime="application/json",
        )
        return config
