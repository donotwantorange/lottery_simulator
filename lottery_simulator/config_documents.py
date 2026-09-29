"""与网页权限无关的新版配置文件契约。"""

from dataclasses import dataclass, asdict
import json
import math
from pathlib import Path
import sys
import unicodedata
from uuid import UUID

from lottery_simulator.formats import CONFIG_FORMAT_VERSION, EXPERIMENT_FORMAT_VERSION, require_version
from lottery_simulator.rules.pool_config import PoolConfig

MAX_CONFIG_BYTES = 5 * 1024 * 1024
DEFAULT_POOL_DIRECTORY = Path(__file__).resolve().parents[1] / "configs" / "pools"
DEFAULT_POOL_PATH = DEFAULT_POOL_DIRECTORY / "default.json"
DEFAULT_RARITY_LABELS = {"4": "四星", "5": "五星", "6": "六星"}


def normalize_name(value: object, field: str = "名称") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}必须是非空文本")
    return unicodedata.normalize("NFC", value.strip())


def normalize_rarity_labels(raw: object = None) -> dict[str, str]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict) or set(raw) - set(DEFAULT_RARITY_LABELS):
        raise ValueError("稀有度名称仅允许4、5、6三个键")
    labels = dict(DEFAULT_RARITY_LABELS)
    for key, value in raw.items():
        labels[key] = normalize_name(value, "稀有度名称")
        if len(labels[key]) > 32:
            raise ValueError("稀有度名称最长32字符")
    if len(set(labels.values())) != 3:
        raise ValueError("三档稀有度名称不得相同")
    return labels


def rarity_label(rarity: int | str, labels: dict | None = None) -> str:
    return (labels or DEFAULT_RARITY_LABELS).get(str(rarity), DEFAULT_RARITY_LABELS[str(rarity)])


def _uuid(value: object) -> str:
    try:
        if not isinstance(value, str):
            raise ValueError
        return str(UUID(value))
    except (ValueError, AttributeError):
        raise ValueError("池ID必须是UUID，不能是文件路径") from None


def _object(raw: object, fields: set[str], label: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"{label}必须是对象")
    if set(raw) - fields:
        raise ValueError(f"{label}包含不支持字段：{'、'.join(sorted(set(raw) - fields))}")
    return raw


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


@dataclass(frozen=True, slots=True)
class PoolDocument:
    format_version: int
    id: str
    name: str
    original_author: str | None
    rule_name: str
    rarity_labels: dict[str, str]
    pool_config: dict

    def to_dict(self) -> dict:
        return asdict(self)

    def to_pool_config(self) -> PoolConfig:
        """文件内层无版本；核心快照独立带版本及名称映射。"""
        return PoolConfig.from_dict({**self.pool_config, "format_version": self.format_version,
                                     "rarity_labels": self.rarity_labels})

    def make_rule(self):
        from lottery_simulator.rules.rule_1 import Rule1
        return {"rule1": Rule1}[self.rule_name](config=self.to_pool_config())


@dataclass(frozen=True, slots=True)
class ExperimentDocument:
    format_version: int
    name: str
    pool_ref: dict[str, str]
    parameters: dict

    def to_dict(self) -> dict:
        return asdict(self)


def load_pool_document(raw: dict) -> PoolDocument:
    raw = _object(raw, {"format_version", "id", "name", "original_author", "rule_name",
                        "rarity_labels", "pool_config"}, "池文件")
    require_version(raw.get("format_version"), CONFIG_FORMAT_VERSION, "池配置格式（仅支持新版2）")
    labels = normalize_rarity_labels(raw.get("rarity_labels", {}))
    if "rarity_labels" in raw and raw["rarity_labels"] is None:
        raise ValueError("稀有度名称必须是对象")
    author = raw.get("original_author")
    if author is not None:
        author = normalize_name(author, "最初作者署名")
    if raw.get("rule_name") != "rule1":
        raise ValueError("池绑定规则不支持：当前仅支持rule1")
    config = raw.get("pool_config")
    if not isinstance(config, dict) or "format_version" in config or "rarity_labels" in config:
        raise ValueError("pool_config必须是对象，版本和稀有度名称只能放在外层")
    _object(config, {"up_share", "five_star", "six_star_characters", "four_star_characters",
                     "five_star_characters", "rewards"}, "池参数")
    _object(config.get("five_star"), {"base_probability", "pity_enabled", "hard_pity"}, "五星保底参数")
    for field, fields in (
        ("six_star_characters", {"name", "is_up", "is_limited", "up_weight"}),
        ("four_star_characters", {"name", "weight"}),
        ("five_star_characters", {"name", "weight"}),
        ("rewards", {"name", "four_star", "five_star", "six_star"}),
    ):
        items = config.get(field, [])
        if not isinstance(items, list):
            raise ValueError(f"{field}必须是列表")
        for item in items:
            _object(item, fields, field)
    document = PoolDocument(CONFIG_FORMAT_VERSION, _uuid(raw.get("id")),
                            normalize_name(raw.get("name"), "池名称"), author,
                            raw["rule_name"], labels, config)
    try:
        document.make_rule()
    except (TypeError, ValueError) as error:
        message = str(error)
        if message.startswith(("主池配置无效", "赠送池配置无效")):
            source = "赠送池" if message.startswith("赠送池") else "主池"
            raise ValueError(f"{source}配置无效：普通抽取的{rarity_label(5, labels)}基础概率与{rarity_label(6, labels)}概率之和不能超过 1") from error
        raise ValueError("配置文件内容无效：请检查角色、概率、权重、奖励和保底，以及绑定规则") from error
    # Serialize the validated values; omit the core-only snapshot metadata.
    config = document.to_pool_config().to_dict()
    config.pop("format_version")
    config.pop("rarity_labels")
    return PoolDocument(document.format_version, document.id, document.name, author,
                        document.rule_name, labels, config)


def validate_experiment_parameters(raw: dict, pool: PoolDocument | None = None) -> dict:
    fields = {"draws", "trials", "initial_pity", "initial_five_star_pity", "seed", "trace"}
    raw = _object(raw, fields, "实验参数")
    if set(raw) != fields:
        raise ValueError("实验参数缺少字段：" + "、".join(sorted(fields - set(raw))))
    for field in ("draws", "trials", "initial_pity", "initial_five_star_pity"):
        minimum = 1 if field in ("draws", "trials") else 0
        if type(raw[field]) is not int or raw[field] < minimum:
            names = {"draws": "每轮主抽数", "trials": "实验轮数", "initial_pity": "初始六星保底进度",
                     "initial_five_star_pity": "初始五星保底进度"}
            raise ValueError(f"模拟参数无效：{names[field]}必须是{'正' if minimum else '非负'}整数")
    if raw["seed"] is not None and type(raw["seed"]) is not int:
        raise ValueError("随机种子必须是整数或null")
    if type(raw["trace"]) is not bool:
        raise ValueError("Trace开关必须是布尔值，不能是null")
    if pool is not None:
        from lottery_simulator.rules.base import DrawState
        try:
            pool.make_rule().rarity_probabilities(DrawState(raw["initial_pity"], raw["initial_five_star_pity"]))
        except (TypeError, ValueError) as error:
            raise ValueError(f"初始保底参数无效：{rarity_label(6, pool.rarity_labels)}与{rarity_label(5, pool.rarity_labels)}保底进度不符合池规则") from error
    return dict(raw)


def load_experiment_document(raw: dict) -> ExperimentDocument:
    raw = _object(raw, {"format_version", "name", "pool_ref", "parameters"}, "实验文件")
    require_version(raw.get("format_version"), EXPERIMENT_FORMAT_VERSION, "实验配置格式")
    ref = _object(raw.get("pool_ref"), {"id", "name"}, "池引用")
    return ExperimentDocument(EXPERIMENT_FORMAT_VERSION,
                              normalize_name(raw.get("name"), "实验名称"),
                              {"id": _uuid(ref.get("id")), "name": normalize_name(ref.get("name"), "引用池名称")},
                              validate_experiment_parameters(raw.get("parameters")))


def resolve_pool_reference(ref: dict, directory: str | Path = DEFAULT_POOL_DIRECTORY,
                           *, interactive: bool = False, input_fn=input) -> PoolDocument:
    """仅扫描指定目录中的JSON文件，引用ID绝不拼接为路径。"""
    documents = []
    for path in sorted(Path(directory).glob("*.json")):
        try:
            documents.append(load_pool_document(read_config_json(path)))
        except ValueError:
            # A stale or broken, unrelated file cannot defeat an exact ID match.
            continue
    matches = [document for document in documents if document.id == ref["id"]]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError("池ID对应多个文件，请显式指定--pool-config")
    if not interactive:
        raise ValueError("无法按ID找到池；非交互执行请显式指定--pool-config")
    matches = [document for document in documents if document.name == ref["name"]]
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
