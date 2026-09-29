"""新版配置契约的集中验收用例（任务14运行）。"""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lottery_simulator.config_documents import (
    DEFAULT_POOL_PATH, MAX_CONFIG_BYTES, load_pool_document, load_experiment_document,
    parse_config_json, read_config_json, resolve_pool_reference,
    validate_experiment_parameters,
)
from lottery_simulator.rules.pool_config import load_pool_config


class ConfigDocumentsTest(unittest.TestCase):
    def setUp(self):
        self.pool = read_config_json(DEFAULT_POOL_PATH)
        self.experiment = read_config_json(DEFAULT_POOL_PATH.parent.parent / "experiments/default.json")

    def test_default_preserves_existing_characters_and_rewards(self):
        previous = json.loads((DEFAULT_POOL_PATH.parent.parent / "rule1_default.json").read_text())
        previous.pop("format_version")
        self.assertEqual(previous, self.pool["pool_config"])
        self.assertEqual(load_pool_config().to_dict()["format_version"], 2)

    def test_file_roundtrip_and_snapshot_are_distinct(self):
        document = load_pool_document(self.pool)
        self.assertNotIn("format_version", document.pool_config)
        self.assertEqual(load_pool_document(document.to_dict()), document)
        snapshot = document.to_pool_config().to_dict()
        self.assertEqual(snapshot["format_version"], 2)
        self.assertEqual(snapshot["rarity_labels"], document.rarity_labels)

    def test_json_security_boundaries(self):
        for data in (b'{"a":1,"a":2}', b'{"a":{"x":1,"x":2}}',
                     b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e9999}',
                     b'[]', b'\xff', b'{'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_config_json(data, 100)
        with self.assertRaises(ValueError):
            parse_config_json(b'{"x":1}', 2)
        with self.assertRaisesRegex(ValueError, "上限"):
            parse_config_json(b'{"x":"' + b'x' * MAX_CONFIG_BYTES + b'"}', MAX_CONFIG_BYTES)

    def test_version_permissions_and_rule_rejected(self):
        for key, value in (("format_version", True), ("format_version", 1),
                           ("owner", "someone"), ("admin", True), ("rule_name", "missing")):
            raw = deepcopy(self.pool)
            raw[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                load_pool_document(raw)
        raw = deepcopy(self.pool)
        raw["pool_config"]["format_version"] = 2
        with self.assertRaises(ValueError):
            load_pool_document(raw)

    def test_rarity_labels_normalized_and_validated(self):
        self.pool["rarity_labels"] = {"6": " SSR "}
        document = load_pool_document(self.pool)
        self.assertEqual(document.rarity_labels, {"4": "四星", "5": "五星", "6": "SSR"})
        for labels in ({"7": "UR"}, {"4": " "}, {"4": "五星"}, {"6": "x" * 33}, None):
            self.pool["rarity_labels"] = labels
            with self.subTest(labels=labels), self.assertRaises(ValueError):
                load_pool_document(self.pool)

    def test_experiment_contract_and_rule_bound_pity(self):
        document = load_experiment_document(self.experiment)
        validate_experiment_parameters(document.parameters, load_pool_document(self.pool))
        for version in (True, 0, 2, "1"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                load_experiment_document({**self.experiment, "format_version": version})
        for key, value in (("trace", None), ("draws", True), ("seed", False)):
            raw = deepcopy(self.experiment)
            raw["parameters"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                load_experiment_document(raw)
        raw = deepcopy(self.experiment)
        raw["rule_name"] = "rule1"
        with self.assertRaises(ValueError):
            load_experiment_document(raw)
        parameters = dict(document.parameters, initial_pity=80)
        with self.assertRaises(ValueError):
            validate_experiment_parameters(parameters, load_pool_document(self.pool))

    def test_id_priority_and_explicit_name_confirmation(self):
        with TemporaryDirectory() as directory:
            Path(directory, "pool.json").write_text(json.dumps(self.pool), encoding="utf-8")
            Path(directory, "broken.json").write_text("{", encoding="utf-8")
            Path(directory, "old.json").write_text('{"format_version":1}', encoding="utf-8")
            ref = dict(self.experiment["pool_ref"], name="已改名")
            self.assertEqual(resolve_pool_reference(ref, directory).id, self.pool["id"])
            Path(directory, "duplicate.json").write_text(json.dumps(self.pool), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "多个文件"):
                resolve_pool_reference(ref, directory)
            Path(directory, "duplicate.json").unlink()
            ref = dict(self.experiment["pool_ref"], id="a33e8fb2-6ca9-4f89-9d7f-e4975c5c4aaa")
            with self.assertRaisesRegex(ValueError, "非交互"):
                resolve_pool_reference(ref, directory)
            self.assertEqual(resolve_pool_reference(ref, directory, interactive=True,
                                                    input_fn=lambda prompt: "1").id, self.pool["id"])
            with self.assertRaises(ValueError):
                resolve_pool_reference(ref, directory, interactive=True, input_fn=lambda prompt: "")


if __name__ == "__main__":
    unittest.main()
