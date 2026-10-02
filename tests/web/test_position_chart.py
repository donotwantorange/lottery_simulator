"""Position graph contract: no database or worker is needed."""
from django.test import SimpleTestCase, RequestFactory

from dashboard.api.runs import _position_chart

R4 = "00000000-0000-4000-8000-000000000004"
R5 = "00000000-0000-4000-8000-000000000005"
R6 = "00000000-0000-4000-8000-000000000006"


class PositionChartTests(SimpleTestCase):
    def chart(self, query="", rows=None):
        class Reader:
            def position_counts(self, **kwargs):
                return rows if rows is not None else [{
                    "source_index": 66, "observations": 10,
                    "rarity_counts": {R4: 8, R5: 2, R6: 0},
                    "rarity_rates": {R4: .8, R5: .2, R6: 0},
                }]
        return _position_chart(RequestFactory().get("/?kind=position&" + query), Reader(), {
            "parameters": {"draws": "100", "trials": "10", "initial_main_draws": "65"},
            "counts": {"bonus_draws": 10},
            "pool_snapshot": {"rarity_labels": {R4: "R", R5: "SR", R6: "SSR"}},
            "rule_snapshot": {"rarities": [
                {"id": R4, "name": "R"}, {"id": R5, "name": "SR"}, {"id": R6, "name": "SSR"},
            ], "bonus": {"enabled": True, "draws": 1}},
        })

    def test_lines_hover_and_table_share_counts_including_zero(self):
        result = self.chart()
        self.assertEqual(result["rows"][0]["position"], "66")
        self.assertEqual(result["rows"][0]["observations"], "10")
        self.assertEqual(result["rows"][0]["window_position"], 0)
        self.assertEqual(result["rows"][0]["r2_count"], "0")
        lines, hover, rule = result["spec"]["layer"]
        self.assertEqual([point["value"] for point in lines["data"]["values"]], [8, 2, 0])
        self.assertEqual(hover["data"]["values"], result["rows"])
        self.assertTrue(hover["params"][0]["select"]["nearest"])
        self.assertEqual(rule["mark"]["type"], "rule")
        self.assertEqual(result["spec"]["width"], "container")
        self.assertEqual(result["spec"]["encoding"]["x"]["scale"]["domain"], [0, 1])
        self.assertTrue(lines["mark"]["point"])
        self.assertEqual(len(hover["encoding"]["tooltip"]), 8)

    def test_single_rarity_rate_and_bonus_use_same_denominator(self):
        result = self.chart(f"rarity_id={R5}&mode=rate&source=bonus")
        line = result["spec"]["layer"][0]
        self.assertEqual(line["data"]["values"][0]["value"], .2)
        self.assertEqual(line["data"]["values"][0]["rarity"], "SR")
        self.assertEqual(result["spec"]["encoding"]["x"]["title"], "赠送抽次")
        self.assertNotIn("r0_count", result["rows"][0])
        tooltip = result["spec"]["layer"][1]["encoding"]["tooltip"]
        self.assertEqual(tooltip[-1]["title"], "SR比例")
        self.assertEqual(tooltip[-1]["format"], ".2%")

    def test_empty_range_has_no_invented_zero_observations(self):
        result = self.chart(rows=[])
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["spec"]["layer"][0]["data"]["values"], [])

    def test_large_positions_keep_exact_labels_and_use_relative_window_coordinates(self):
        result = self.chart(rows=[{
            "source_index": 9007199254740993, "observations": 9007199254740994,
            "rarity_counts": {R4: 9007199254740993, R5: 1},
            "rarity_rates": {R4: 1, R5: 0},
        }])
        row = result["rows"][0]
        self.assertEqual(row["position"], "9007199254740993")
        self.assertEqual(row["r0_count"], "9007199254740993")
        self.assertEqual(row["observations"], "9007199254740994")
        self.assertEqual(row["window_position"], 0)
        self.assertTrue(result["chart_approximate"])
        self.assertIn("9007199254740993", result["spec"]["encoding"]["x"]["axis"]["labelExpr"])

    def test_source_window_is_capped_at_one_thousand_positions(self):
        class Reader:
            seen = None
            def position_counts(self, **kwargs):
                self.seen = kwargs
                return []
        reader = Reader()
        payload = {"parameters": {"draws": "10000", "trials": "10"},
            "pool_snapshot": {"rarity_labels": {}},
            "rule_snapshot": {"rarities": [{"id": R4, "name": "R"}],
                               "bonus": {"enabled": False, "draws": 0}}}
        _position_chart(RequestFactory().get("/?source_from=100&source_to=999999"), reader, payload)
        self.assertEqual(reader.seen["source_from"], 100)
        self.assertEqual(reader.seen["source_to"], 1099)
