"""Strict new file contracts; collected for task-16 acceptance."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lottery_simulator.config_documents import (
    DEFAULT_EXPERIMENT_PATH, DEFAULT_POOL_PATH, DEFAULT_RULE_PATH, MAX_CONFIG_BYTES,
    load_rule_document, load_pool_document, load_experiment_document, parse_config_json,
    read_config_json, resolve_pool_reference, resolve_rule_reference,
    validate_experiment_parameters,
)


class ConfigDocumentsTest(unittest.TestCase):
    def setUp(self):
        self.rule = read_config_json(DEFAULT_RULE_PATH)
        self.pool = read_config_json(DEFAULT_POOL_PATH)
        self.experiment = read_config_json(DEFAULT_EXPERIMENT_PATH)

    def test_defaults_preserve_roster_and_rewards_with_new_identity(self):
        characters = self.pool["rarity_pools"][-1]["characters"]
        self.assertEqual([(c["name"], c["is_up"], c["is_limited"]) for c in characters], [
            ("UP-A", True, True), ("限定-B", False, True),
            ("限定-C", False, True), ("常驻-D", False, False),
            ("常驻-E", False, False), ("常驻-F", False, False),
            ("常驻-G", False, False), ("常驻-H", False, False),
            ("常驻-I", False, False),
        ])
        self.assertTrue(all(c["weight"] == 1 for c in characters))
        rarity_ids = [r["id"] for r in self.rule["rarities"]]
        self.assertEqual(self.pool["rule_ref"]["id"], self.rule["id"])
        self.assertEqual(self.experiment["pool_ref"]["id"], self.pool["id"])
        self.assertEqual([reward["name"] for reward in self.pool["rewards"]], ["奖励A", "奖励B"])
        self.assertTrue(all(set(reward["amounts"]) == set(rarity_ids) for reward in self.pool["rewards"]))
        self.assertTrue(all(not p["characters"] for p in self.pool["rarity_pools"][:2]))

    def test_three_file_roundtrips(self):
        for raw, load in ((self.rule, load_rule_document), (self.pool, load_pool_document),
                          (self.experiment, load_experiment_document)):
            with self.subTest(loader=load):
                document = load(raw)
                self.assertEqual(load(document.to_dict()), document)
                self.assertEqual(load(parse_config_json(json.dumps(document.to_dict()).encode())), document)
        self.assertIsNone(load_experiment_document(self.experiment).initial_context)

    def test_json_security_boundaries(self):
        for data in (b'{"a":1,"a":2}', b'{"a":{"x":1,"x":2}}', b'{"x":NaN}',
                     b'{"x":Infinity}', b'{"x":1e9999}', b'[]', b'\xff', b'{'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_config_json(data, 100)
        for limit in (True, 0, -1):
            with self.assertRaises(ValueError):
                parse_config_json(b'{}', limit)
        with self.assertRaises(ValueError):
            parse_config_json(b'{"x":1}', 2)
        with self.assertRaisesRegex(ValueError, "上限"):
            parse_config_json(b'{"x":"' + b'x' * MAX_CONFIG_BYTES + b'"}')
        with self.assertRaises(ValueError):
            read_config_json(Path("missing-config-file.json"))

    def test_old_versions_and_forged_metadata_are_rejected(self):
        for raw, load, old_version in ((self.rule, load_rule_document, 0),
                                       (self.pool, load_pool_document, 2),
                                       (self.experiment, load_experiment_document, 1)):
            for version in (True, old_version, str(raw["format_version"])):
                with self.subTest(loader=load, version=version), self.assertRaises(ValueError):
                    load({**raw, "format_version": version})
            for field in ("owner", "admin", "visibility", "revision"):
                with self.subTest(field=field), self.assertRaises(ValueError):
                    load({**raw, field: "forged"})
        with self.assertRaises(ValueError):
            load_pool_document({"format_version": 2})

    def test_reference_and_parameters_are_strict(self):
        document = load_experiment_document(self.experiment)
        pool = load_pool_document(self.pool)
        self.assertEqual(validate_experiment_parameters(document.parameters.to_dict(), pool), document.parameters.to_dict())
        for key, value in (("trace", None), ("draws", True), ("seed", False), ("initial_main_draws", "0")):
            raw = deepcopy(self.experiment)
            raw["parameters"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                load_experiment_document(raw)
        for changed in ({"id": "../path", "name": "池"}, {"id": self.pool["id"], "name": " "},
                        {**self.experiment["pool_ref"], "path": "injected"}):
            with self.assertRaises(ValueError):
                load_experiment_document({**self.experiment, "pool_ref": changed})
        with self.assertRaises(ValueError):
            load_experiment_document({**self.experiment, "rule_snapshot": self.rule})
        parameters = document.parameters.to_dict()
        parameters["initial_small_pity"] = {"00000000-0000-0000-0000-000000000001": 0}
        with self.assertRaises(ValueError):
            validate_experiment_parameters(parameters, pool)

    def test_rarity_labels_and_nested_unknown_fields(self):
        raw = deepcopy(self.pool)
        rid = raw["rarity_pools"][-1]["rarity_id"]
        raw["rarity_labels"] = {rid: " SSR "}
        self.assertEqual(load_pool_document(raw).rarity_labels[rid], "SSR")
        for place in (raw["rarity_pools"][-1], raw["rarity_pools"][-1]["characters"][0], raw["rewards"][0]):
            place["unknown"] = 1
            with self.assertRaises(ValueError):
                load_pool_document(raw)
            del place["unknown"]

    def test_id_priority_and_explicit_name_confirmation(self):
        with TemporaryDirectory() as directory:
            Path(directory, "pool.json").write_text(json.dumps(self.pool), encoding="utf-8")
            Path(directory, "broken.json").write_text("{", encoding="utf-8")
            Path(directory, "old.json").write_text('{"format_version":2}', encoding="utf-8")
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

    def test_rule_id_priority_name_confirmation_and_invalid_exact_id(self):
        with TemporaryDirectory() as directory:
            Path(directory, "zmd.json").write_text(json.dumps(self.rule), encoding="utf-8")
            Path(directory, "broken.json").write_text("{", encoding="utf-8")
            ref = dict(self.pool["rule_ref"], name="旧名称")
            self.assertEqual(resolve_rule_reference(ref, directory).id, self.rule["id"])
            missing = dict(ref, id="a33e8fb2-6ca9-4f89-9d7f-e4975c5c4aaa", name=self.rule["name"])
            with self.assertRaisesRegex(ValueError, "确认"):
                resolve_rule_reference(missing, directory)
            self.assertEqual(resolve_rule_reference(missing, directory,
                confirm=lambda candidate: candidate.name == self.rule["name"]).id, self.rule["id"])
            self.assertNotEqual(resolve_rule_reference(dict(ref, id=self.rule["id"].upper()), directory).id,
                                "")
            invalid = deepcopy(self.rule)
            invalid["future_field"] = True
            Path(directory, "invalid.json").write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "格式无效"):
                resolve_rule_reference(ref, directory)


if __name__ == "__main__":
    unittest.main()
