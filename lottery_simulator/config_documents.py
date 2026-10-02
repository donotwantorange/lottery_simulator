"""Strict file loading, independent of Django and runtime rule execution."""

import math
import json
from collections.abc import Mapping
from pathlib import Path
import sys

from lottery_simulator.formats import EXPERIMENT_FORMAT_VERSION
from lottery_simulator.rules.definitions import (
    ExperimentDocument, ExperimentParameters, PoolDefinition, RuleDefinition,
    normalize_name, uuid_text,
)

MAX_CONFIG_BYTES = 5 * 1024 * 1024
CONFIG_DIRECTORY = Path(__file__).resolve().parents[1] / "configs"
DEFAULT_RULE_DIRECTORY = CONFIG_DIRECTORY / "rules"
DEFAULT_RULE_PATH = DEFAULT_RULE_DIRECTORY / "zmd.json"
DEFAULT_POOL_DIRECTORY = CONFIG_DIRECTORY / "pools"
DEFAULT_POOL_PATH = DEFAULT_POOL_DIRECTORY / "default.json"
DEFAULT_EXPERIMENT_PATH = CONFIG_DIRECTORY / "experiments/default.json"

def parse_config_json(data: bytes, max_bytes: int = MAX_CONFIG_BYTES) -> dict:
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("JSON大小上限必须是正整数")
    if not isinstance(data, bytes) or len(data) > max_bytes:
        raise ValueError("配置文件超过JSON大小上限")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"JSON包含重复键：{key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("JSON不允许非有限数值")

    def floating(value):
        number = float(value)
        if not math.isfinite(number):
            constant(value)
        return number

    try:
        raw = json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                         parse_constant=constant, parse_float=floating)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("配置文件必须是有效的UTF-8 JSON") from error
    except ValueError as error:
        if str(error).startswith("JSON"):
            raise
        raise ValueError("配置文件JSON数值无效") from error
    if not isinstance(raw, dict):
        raise ValueError("配置文件JSON根节点必须是对象")
    return raw


def read_config_json(path: str | Path, max_bytes: int = MAX_CONFIG_BYTES) -> dict:
    try:
        with Path(path).open("rb") as source:
            return parse_config_json(source.read(max_bytes + 1), max_bytes)
    except OSError as error:
        raise ValueError("配置文件不存在或不可读取") from error


def load_rule_document(raw: dict) -> RuleDefinition:
    return RuleDefinition.from_dict(raw)


def load_pool_document(raw: dict) -> PoolDefinition:
    return PoolDefinition.from_dict(raw)


def load_experiment_document(raw: dict) -> ExperimentDocument:
    return ExperimentDocument.from_dict(raw)


def validate_experiment_parameters(raw: dict, pool: PoolDefinition | None = None) -> dict:
    """Type/count validation; enabled-mechanism semantics belong to task-2 runtime."""
    parameters = ExperimentParameters.from_dict(raw)
    if pool is not None:
        if not isinstance(pool, PoolDefinition):
            raise ValueError("池定义类型无效")
        ids = {item.rarity_id for item in pool.rarity_pools}
        if set(parameters.initial_small_pity) - ids:
            raise ValueError("初始小保底包含未知稀有度ID")
    return parameters.to_dict()


def resolve_pool_reference(ref: dict, directory: str | Path = DEFAULT_POOL_DIRECTORY,
                           *, interactive: bool = False, input_fn=input) -> PoolDefinition:
    """仅扫描指定目录中的JSON文件，引用ID绝不拼接为路径。"""
    if not isinstance(ref, Mapping) or set(ref) != {"id", "name"}:
        raise ValueError("池引用格式无效")
    documents = []
    wanted = uuid_text(ref["id"])
    wanted_name = normalize_name(ref["name"], "池引用名称")
    bad_id_file = False
    for path in sorted(Path(directory).glob("*.json")):
        try:
            raw = read_config_json(path)
        except ValueError:
            try:
                bad_id_file |= uuid_text(path.stem) == wanted
            except ValueError:
                pass
            continue
        try:
            raw_id = uuid_text(raw.get("id"))
        except ValueError:
            raw_id = None
        if raw_id == wanted:
            try:
                documents.append(load_pool_document(raw))
            except ValueError:
                bad_id_file = True
        else:
            try:
                documents.append(load_pool_document(raw))
            except ValueError:
                continue
    if bad_id_file:
        raise ValueError("池ID对应文件格式无效，不能按名称替换")
    matches = [document for document in documents if document.id == wanted]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError("池ID对应多个文件，请显式指定--pool-config")
    if not interactive:
        raise ValueError("无法按ID找到池；非交互执行请显式指定--pool-config")
    matches = [document for document in documents if document.name == wanted_name]
    if not matches:
        raise ValueError("未找到名称候选，请显式指定--pool-config")
    for index, document in enumerate(matches, 1):
        print(f"{index}：{document.name}（ID：{document.id}，作者：{document.original_author or '未署名'}）", file=sys.stderr)
    try:
        print("ID未找到。请输入候选编号确认使用该池，直接回车取消：", end="", file=sys.stderr, flush=True)
        selected = input_fn("").strip()
        index = int(selected) - 1
        if not 0 <= index < len(matches):
            raise ValueError
    except (EOFError, ValueError):
        raise ValueError("未确认名称候选，请显式指定--pool-config") from None
    return matches[index]


def resolve_rule_reference(ref: dict, directory: str | Path = DEFAULT_RULE_DIRECTORY,
                           confirm=None) -> RuleDefinition:
    """Resolve an ID first; a name fallback is usable only after caller confirmation."""
    if not isinstance(ref, Mapping) or set(ref) != {"id", "name"}:
        raise ValueError("规则引用格式无效")
    rule_id = uuid_text(ref["id"])
    rule_name = normalize_name(ref["name"], "规则引用名称")
    candidates = []
    bad_id_file = False
    for path in sorted(Path(directory).glob("*.json")):
        try:
            raw = read_config_json(path)
        except ValueError:
            try:
                bad_id_file |= uuid_text(path.stem) == rule_id
            except ValueError:
                pass
            continue
        try:
            raw_id = uuid_text(raw.get("id"))
        except ValueError:
            raw_id = None
        if raw_id == rule_id:
            try:
                candidates.append(load_rule_document(raw))
            except ValueError:
                bad_id_file = True
            continue
        try:
            candidates.append(load_rule_document(raw))
        except ValueError:
            continue
    if bad_id_file:
        raise ValueError("规则ID对应文件格式无效，不能按名称替换")
    matches = [rule for rule in candidates if rule.id == rule_id]
    if len(matches) > 1:
        raise ValueError("规则ID对应多个文件")
    if matches:
        return matches[0]
    named = [rule for rule in candidates if rule.name == rule_name]
    if not named:
        raise ValueError("未找到规则ID或名称候选")
    if len(named) != 1:
        raise ValueError("规则名称对应多个文件，无法自动选择")
    if not callable(confirm) or not confirm(named[0]):
        raise ValueError("名称候选未获确认")
    return named[0]
