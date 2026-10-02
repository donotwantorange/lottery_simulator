from copy import deepcopy
import unittest

from dashboard.charts import summary_chart_data
from dashboard.charts import comparison_bar_chart, format_comparison_value
from lottery_simulator.engine import _empty_summary
from tests.fixtures_rules import make_default_compiled


class DynamicChartTests(unittest.TestCase):
    def test_comparison_chart_preserves_order_offsets_precision_and_empty_range(self):
        self.assertEqual(format_comparison_value(0), "0")
        self.assertEqual(format_comparison_value(1.25), "1.2500")
        self.assertIn("e", format_comparison_value(0.000001))
        names = ["四星", "一个很长的角色名称"]
        chart = comparison_bar_chart(
            [{"角色": name, "模拟均值": 0.0, "理论期望": 0.000001} for name in names],
            category_field="角色", unit="每轮数量", horizontal=True,
        ).to_dict()
        encoding = chart["layer"][0]["encoding"]
        self.assertEqual(encoding["yOffset"]["field"], "系列")
        self.assertEqual(encoding["color"]["scale"]["domain"], ["模拟均值", "理论期望"])
        self.assertEqual({row["类别"] for row in chart["data"]["values"]}, set(names))
        tiny_domain = encoding["x"]["scale"]["domain"]
        self.assertEqual(tiny_domain[0], 0)
        self.assertGreater(tiny_domain[1], 0.000001)
        vertical = comparison_bar_chart(
            [{"稀有度": "六星", "模拟均值": 0.0, "理论期望": 0.000001}],
            category_field="稀有度", unit="每轮数量",
        ).to_dict()
        vertical_encoding = vertical["layer"][0]["encoding"]
        self.assertEqual(vertical_encoding["xOffset"]["field"], "系列")
        self.assertEqual(vertical_encoding["color"]["scale"]["domain"], ["模拟均值", "理论期望"])
        zero = comparison_bar_chart(
            [{"稀有度": "新档", "模拟均值": 0.0, "理论期望": 0.0}],
            category_field="稀有度", unit="每轮数量",
        ).to_dict()
        domain = zero["layer"][0]["encoding"]["y"]["scale"]["domain"]
        self.assertEqual(domain[0], 0)
        self.assertGreater(domain[1], 0)

    def test_snapshot_labels_sources_and_grants_keep_distinct_statistics(self):
        compiled = make_default_compiled()
        draw = _empty_summary(compiled, "draws")
        grant = _empty_summary(compiled, "grants")
        target = compiled.targets["periodic_grant"]
        grant["character_counts"][target] = 2
        observed = {"draws": {source: deepcopy(draw) for source in ("main", "bonus", "total")},
                    "grants": grant, "acquisitions": deepcopy(grant)}
        payload = {"rule_snapshot": compiled.rule.to_dict(),
                   "pool_snapshot": compiled.pool.to_dict(),
                   "simulation": observed, "theoretical": deepcopy(observed)}
        tier = min(compiled.rule.rarities, key=lambda rarity: rarity.rank)
        payload["pool_snapshot"]["rarity_labels"][tier.id] = "自定义最低档"
        payload["simulation"]["draws"]["main"]["rarity_counts"][tier.id] = 17
        main = summary_chart_data(payload, "main")
        self.assertEqual(main["rows"]["rarity"][0],
                         {"稀有度": "自定义最低档", "模拟均值": 17, "理论期望": 0, "相对误差": None})
        grants = summary_chart_data(payload, "grants")
        self.assertEqual(grants["rows"]["rewards"], [])
        self.assertEqual(grants["rows"]["pity"], [])
        self.assertEqual(grants["rows"]["characters"][0]["模拟均值"], 2)
        self.assertEqual(len(main["rows"]["categories"]), len(compiled.rule.rarities) * 4)
        self.assertIsNone(main["rows"]["rarity"][0]["相对误差"])
        self.assertFalse(main["chart_approximate"])
        with self.assertRaises(ValueError):
            summary_chart_data(payload, "unknown")

    def test_unsafe_integer_counts_remain_decimal_text_in_the_table(self):
        compiled = make_default_compiled()
        draw = _empty_summary(compiled, "draws")
        payload = {"rule_snapshot": compiled.rule.to_dict(), "pool_snapshot": compiled.pool.to_dict(),
            "simulation": {"draws": {source: deepcopy(draw) for source in ("main", "bonus", "total")},
                           "grants": _empty_summary(compiled, "grants"),
                           "acquisitions": _empty_summary(compiled, "acquisitions")},
            "theoretical": {"draws": {source: deepcopy(draw) for source in ("main", "bonus", "total")},
                            "grants": _empty_summary(compiled, "grants"),
                            "acquisitions": _empty_summary(compiled, "acquisitions")}}
        rarity_id = compiled.rule.rarities[0].id
        payload["simulation"]["draws"]["main"]["rarity_counts"][rarity_id] = 9007199254740993
        result = summary_chart_data(payload, "main")
        self.assertEqual(result["rows"]["rarity"][0]["模拟均值"], "9007199254740993")
        self.assertTrue(result["chart_approximate"])
