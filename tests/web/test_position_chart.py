"""Position graph contract: no database or worker is needed."""
from django.test import SimpleTestCase, RequestFactory

from dashboard.api.runs import _position_chart


class PositionChartTests(SimpleTestCase):
    def chart(self, query="", rows=None):
        class Reader:
            def position_counts(self, **kwargs):
                return rows if rows is not None else [{
                    "source_index": 66, "observations": 10,
                    "four_count": 8, "five_count": 2, "six_count": 0,
                    "four_rate": .8, "five_rate": .2, "six_rate": 0,
                }]
        return _position_chart(RequestFactory().get("/?" + query), Reader(), {
            "main_draws": 100, "bonus_draws": 10, "trials": 10,
            "pool_config": {"rarity_labels": {"4": "R", "5": "SR", "6": "SSR"}},
        })

    def test_lines_hover_and_table_share_counts_including_zero(self):
        result = self.chart()
        self.assertEqual(result["rows"][0]["observations"], 10)
        self.assertEqual(result["rows"][0]["six_count"], 0)
        lines, hover, rule = result["spec"]["layer"]
        self.assertEqual([point["value"] for point in lines["data"]["values"]], [8, 2, 0])
        self.assertEqual(hover["data"]["values"], result["rows"])
        self.assertTrue(hover["params"][0]["select"]["nearest"])
        self.assertEqual(rule["mark"]["type"], "rule")
        self.assertEqual(result["spec"]["width"], "container")
        self.assertEqual(result["spec"]["encoding"]["x"]["scale"]["domain"], [65.5, 66.5])
        self.assertTrue(lines["mark"]["point"])
        self.assertEqual(len(hover["encoding"]["tooltip"]), 8)

    def test_single_rarity_rate_and_bonus_use_same_denominator(self):
        result = self.chart("rarity=5&mode=rate&source=bonus")
        line = result["spec"]["layer"][0]
        self.assertEqual(line["data"]["values"][0]["value"], .2)
        self.assertEqual(line["data"]["values"][0]["rarity"], "SR")
        self.assertEqual(result["spec"]["encoding"]["x"]["title"], "赠送抽次")
        self.assertNotIn("four_count", result["rows"][0])
        tooltip = result["spec"]["layer"][1]["encoding"]["tooltip"]
        self.assertEqual(tooltip[-1]["title"], "SR比例")
        self.assertEqual(tooltip[-1]["format"], ".2%")

    def test_empty_range_has_no_invented_zero_observations(self):
        result = self.chart(rows=[])
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["spec"]["layer"][0]["data"]["values"], [])
