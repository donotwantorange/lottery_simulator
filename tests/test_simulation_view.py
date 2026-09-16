import json
import unittest

from dashboard.models import result_payload
from dashboard.views.simulation import render_result
from lottery_simulator.engine import simulate
from lottery_simulator.rules.rule_1 import Rule1


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False


class RecordingStreamlit:
    def __init__(self, source="总计", reward_name="奖励A"):
        self.events = []
        self.metrics = []
        self.charts = []
        self.dataframes = []
        self.labels = []
        self.downloads = []
        self.writes = []
        self.source = source
        self.reward_name = reward_name

    def columns(self, count):
        return [self] * count

    def metric(self, label, value, delta=None):
        self.labels.append(label)
        self.metrics.append((label, value, delta))

    def subheader(self, label):
        self.labels.append(label)
        self.events.append(("subheader", label))

    def line_chart(self, data, **kwargs):
        self.events.append(("line_chart", None))
        self.charts.append(("line", data, kwargs))

    def bar_chart(self, data, **kwargs):
        self.events.append(("bar_chart", None))
        self.charts.append(("bar", data, kwargs))

    def expander(self, label):
        self.labels.append(label)
        self.events.append(("expander", label))
        return _Context()

    def dataframe(self, data, **kwargs):
        self.events.append(("dataframe", None))
        self.dataframes.append(data)

    def tabs(self, labels):
        self.labels.extend(labels)
        self.events.append(("tabs", tuple(labels)))
        return [_Context() for _ in labels]

    def radio(self, label, options, **kwargs):
        self.labels.append(label)
        self.events.append(("radio", (label, tuple(options), kwargs)))
        return self.source

    def selectbox(self, label, options, **kwargs):
        self.labels.append(label)
        self.events.append(("selectbox", (label, tuple(options), kwargs)))
        return self.reward_name

    def write(self, value):
        self.writes.append(value)

    def info(self, label):
        self.labels.append(label)
        self.events.append(("info", label))

    def download_button(self, label, **kwargs):
        self.labels.append(label)
        self.downloads.append((label, kwargs))


class SimulationResultViewTest(unittest.TestCase):
    def setUp(self):
        rule = Rule1()
        self.payload = result_payload(
            simulate(rule, 2, seed=42, initial_pity=29), rule, 0.25
        )
        self.payload["备注"] = "六星"

    @staticmethod
    def table_with_column(st, column):
        return next(table for table in st.dataframes if table and column in table[0])

    def test_renderer_shows_six_regions_dynamic_rows_trace_and_utf8_download(self):
        st = RecordingStreamlit()

        render_result(st, self.payload, trace_enabled=True)

        self.assertEqual(
            next(value for event, value in st.events if event == "tabs"),
            ("总览", "六星构成", "具体角色", "附赠奖励", "保底统计", "Trace"),
        )
        source_event = next(value for event, value in st.events if event == "radio")
        self.assertEqual(source_event[0], "数据来源")
        self.assertEqual(source_event[1], ("主池", "赠送", "总计"))

        probability_table = self.table_with_column(st, "抽次")
        self.assertEqual(len(probability_table), 80)
        self.assertEqual(
            (probability_table[64]["抽次"], probability_table[64]["条件六星概率"]),
            (65, 0.008),
        )
        self.assertEqual(
            (probability_table[65]["抽次"], probability_table[65]["条件六星概率"]),
            (66, 0.058),
        )

        rarity_table = self.table_with_column(st, "星级")
        self.assertEqual([row["星级"] for row in rarity_table], ["四星", "五星", "六星"])
        self.assertEqual([row["模拟均值"] for row in rarity_table], [9.0, 3.0, 0.0])

        category_table = self.table_with_column(st, "类型")
        self.assertEqual(
            [row["类型"] for row in category_table],
            ["UP限定", "其他限定", "常驻"],
        )

        character_table = self.table_with_column(st, "角色")
        self.assertEqual(len(character_table), 9)
        self.assertEqual(character_table[0]["角色"], "UP-A")
        self.assertEqual(character_table[-1]["角色"], "常驻-I")

        reward_table = self.table_with_column(st, "奖励")
        self.assertEqual([row["奖励"] for row in reward_table], ["奖励A", "奖励B"])
        reward_distribution = self.table_with_column(st, "奖励总量")
        self.assertEqual(reward_distribution, [
            {"奖励总量": 24.0, "实验次数": 1, "占比": 1.0},
        ])

        pity_table = self.table_with_column(st, "保底类型")
        self.assertEqual(
            [row["保底类型"] for row in pity_table],
            ["五星保底", "六星硬保底"],
        )

        trace_table = next(table for table in st.dataframes if table is self.payload["records"])
        self.assertEqual(trace_table, self.payload["records"])
        self.assertTrue({
            "rarity", "six_star_character", "rewards", "source_state_before",
            "source_state_after", "five_star_pity_triggered",
            "six_star_hard_pity_triggered",
        }.issubset(trace_table[0]))
        label, download = st.downloads[0]
        self.assertEqual(label, "下载结果 JSON")
        self.assertEqual(download["file_name"], "simulation-result.json")
        self.assertEqual(download["mime"], "application/json")
        self.assertIsInstance(download["data"], bytes)
        self.assertIn("六星".encode("utf-8"), download["data"])
        self.assertEqual(json.loads(download["data"].decode("utf-8")), self.payload)

    def test_renderer_switches_all_summary_tables_between_sources(self):
        expected = {
            "主池": [2.0, 0.0, 0.0],
            "赠送": [7.0, 3.0, 0.0],
            "总计": [9.0, 3.0, 0.0],
        }
        for label, rarity_means in expected.items():
            with self.subTest(source=label):
                st = RecordingStreamlit(source=label)

                render_result(st, self.payload, trace_enabled=False)

                rarity_table = self.table_with_column(st, "星级")
                self.assertEqual(
                    [row["模拟均值"] for row in rarity_table], rarity_means
                )

    def test_renderer_never_passes_records_to_dataframe_without_trace(self):
        st = RecordingStreamlit()

        render_result(st, self.payload, trace_enabled=False)

        self.assertNotIn(self.payload["records"], st.dataframes)
        self.assertIn("本次运行未保存逐抽记录", st.labels)


if __name__ == "__main__":
    unittest.main()
