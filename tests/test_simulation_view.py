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
    def __init__(self):
        self.events = []
        self.metrics = []
        self.charts = []
        self.dataframes = []
        self.labels = []
        self.downloads = []
        self.writes = []

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

    def test_renderer_shows_all_labels_charts_numeric_tables_trace_and_utf8_download(self):
        st = RecordingStreamlit()

        render_result(st, self.payload, trace_enabled=True)

        self.assertEqual(
            st.labels,
            [
                "主池抽数",
                "赠送抽数",
                "总抽数",
                "主池模拟六星均值",
                "赠送模拟六星均值",
                "总模拟六星均值",
                "主池理论期望",
                "赠送理论期望",
                "总理论期望",
                "绝对误差",
                "相对误差",
                "初始主池累计抽数",
                "结束主池累计抽数",
                "随机种子",
                "运行耗时（秒）",
                "主池六星概率",
                "查看主池六星概率数值",
                "六星数量分布",
                "查看六星数量分布数值",
                "模拟值与理论期望",
                "查看来源对比数值",
                "汇总",
                "主池与赠送拆分",
                "逐抽记录",
                "下载结果 JSON",
            ],
        )
        self.assertEqual([kind for kind, _, _ in st.charts], ["line", "bar", "bar"])
        self.assertEqual(len(st.dataframes), 4)
        probability_table, count_table, source_table, trace_table = st.dataframes
        self.assertEqual(len(probability_table), 80)
        self.assertEqual(
            (probability_table[64]["抽次"], probability_table[64]["条件六星概率"]),
            (65, 0.008),
        )
        self.assertEqual(
            (probability_table[65]["抽次"], probability_table[65]["条件六星概率"]),
            (66, 0.058),
        )
        self.assertEqual(
            count_table, [{"六星数量": 0, "实验次数": 1, "占比": 1.0}]
        )
        expected_sources = [
            {"来源": "主池", "模拟均值": 0.0, "理论期望": 0.016},
            {"来源": "赠送", "模拟均值": 0.0, "理论期望": 0.08},
            {"来源": "总计", "模拟均值": 0.0, "理论期望": 0.096},
        ]
        self.assertEqual(len(source_table), len(expected_sources))
        for actual, expected in zip(source_table, expected_sources):
            self.assertEqual(actual.keys(), expected.keys())
            self.assertEqual(actual["来源"], expected["来源"])
            self.assertEqual(actual["模拟均值"], expected["模拟均值"])
            self.assertAlmostEqual(actual["理论期望"], expected["理论期望"], places=12)
        self.assertEqual(trace_table, self.payload["records"])
        event_start = 0
        for chart, expander in (
            ("line_chart", "查看主池六星概率数值"),
            ("bar_chart", "查看六星数量分布数值"),
            ("bar_chart", "查看来源对比数值"),
        ):
            chart_index = st.events.index((chart, None), event_start)
            self.assertEqual(st.events[chart_index + 1], ("expander", expander))
            self.assertEqual(st.events[chart_index + 2], ("dataframe", None))
            event_start = chart_index + 3
        label, download = st.downloads[0]
        self.assertEqual(label, "下载结果 JSON")
        self.assertEqual(download["file_name"], "simulation-result.json")
        self.assertEqual(download["mime"], "application/json")
        self.assertIsInstance(download["data"], bytes)
        self.assertIn("六星".encode("utf-8"), download["data"])
        self.assertEqual(json.loads(download["data"].decode("utf-8")), self.payload)

    def test_renderer_never_passes_records_to_dataframe_without_trace(self):
        st = RecordingStreamlit()

        render_result(st, self.payload, trace_enabled=False)

        self.assertEqual(len(st.dataframes), 3)
        self.assertNotIn(self.payload["records"], st.dataframes)
        self.assertIn("本次运行未保存逐抽记录", st.labels)


if __name__ == "__main__":
    unittest.main()
