import copy
import unittest
from dataclasses import asdict

from dashboard.models import result_payload
from dashboard.views.simulation import render_result
from lottery_simulator.engine import simulate
from lottery_simulator.rules.rule_1 import Rule1


class RecordingStreamlit:
    def __init__(self, view="实验概览", source="总计", category="星级", columns="基础列"):
        self.view = view
        self.source = source
        self.category = category
        self.detail_columns = columns
        self.session_state = {}
        self.metrics = []
        self.dataframes = []
        self.charts = []
        self.infos = []
        self.captions = []
        self.writes = []
        self.downloads = []
        self.category_options = ()

    def columns(self, count):
        return [self] * count

    def metric(self, label, value, delta=None):
        self.metrics.append((label, value, delta))

    def selectbox(self, label, options, **kwargs):
        if label == "结果视图":
            return self.view
        if label == "分类统计":
            self.category_options = tuple(options)
            return self.category
        if label == "每页条数":
            return 100
        return options[0]

    def radio(self, label, options, **kwargs):
        if label == "数据来源":
            return self.source
        if label == "明细列":
            return self.detail_columns
        return options[0]

    def dataframe(self, data, **kwargs):
        self.dataframes.append(data)

    def bar_chart(self, data, **kwargs):
        self.charts.append(data)

    def line_chart(self, data, **kwargs):
        self.charts.append(data)

    def write(self, value):
        self.writes.append(value)

    def caption(self, value):
        self.captions.append(value)

    def info(self, value):
        self.infos.append(value)

    def warning(self, value):
        pass

    def checkbox(self, label, **kwargs):
        return False

    def number_input(self, label, **kwargs):
        return kwargs.get("value", kwargs.get("min_value", 1))

    def button(self, label, **kwargs):
        return False

    def download_button(self, label, **kwargs):
        self.downloads.append((label, kwargs))


class TraceReaderStub:
    def __init__(self, records):
        self.records = records
        self.query_calls = []
        self.iter_calls = []
        self.position_calls = []

    def query_records(self, filters, *, limit=100, offset=0):
        self.query_calls.append((filters, limit, offset))
        return self.records[offset : offset + limit], len(self.records)

    def iter_records(self, filters, *, batch_size=1000):
        self.iter_calls.append(filters)
        yield from self.records

    def position_counts(self, **kwargs):
        self.position_calls.append(kwargs)
        return []


class SimulationResultViewTest(unittest.TestCase):
    def setUp(self):
        rule = Rule1()
        simulation = simulate(
            rule, 2, trials=2, seed=42, initial_pity=29, collect_records=True
        )
        self.payload = result_payload(simulation, rule, 0.25)
        self.payload["id"] = "run-1"
        self.records = [asdict(record) for record in simulation.records]

    @staticmethod
    def table_with_column(st, column):
        return next(table for table in st.dataframes if table and column in table[0])

    def test_renderer_shows_four_result_views_and_summary_without_reader_query(self):
        reader = TraceReaderStub(self.records)
        st = RecordingStreamlit(view="实验概览")

        render_result(st, self.payload, reader)

        self.assertEqual(reader.query_calls, [])
        self.assertEqual(reader.iter_calls, [])
        self.assertEqual(
            [label for label, _, _ in st.metrics][:3],
            ["每轮主池抽数", "每轮赠送抽数", "每轮总抽数"],
        )
        summary = self.table_with_column(st, "范围")
        self.assertEqual(summary[-1]["范围"], "全实验")
        self.assertEqual(st.downloads[0][0], "下载汇总 JSON")
        self.assertNotIn(b'"records"', st.downloads[0][1]["data"])

    def test_renderer_switches_category_subviews_without_reader_query(self):
        reader = TraceReaderStub(self.records)
        for category in ("星级", "六星构成", "六星具体角色", "奖励", "保底"):
            with self.subTest(category=category):
                st = RecordingStreamlit(view="分类统计", category=category, source="总计")
                render_result(st, self.payload, reader)
                self.assertEqual(reader.query_calls, [])
                self.assertTrue(st.dataframes)
                self.assertIn("六星具体角色", st.category_options)

    def test_renderer_detail_uses_reader_and_keeps_new_round_columns(self):
        reader = TraceReaderStub(self.records)
        st = RecordingStreamlit(view="逐抽明细", columns="完整列")

        render_result(st, self.payload, reader)

        self.assertEqual(len(reader.query_calls), 1)
        filters, limit, offset = reader.query_calls[0]
        self.assertEqual((filters.trial_from, filters.trial_to, filters.source), (1, 1, None))
        self.assertEqual((limit, offset), (100, 0))
        table = self.table_with_column(st, "轮次")
        self.assertEqual((table[0]["轮次"], table[0]["轮内总抽次"]), (1, 1))
        self.assertIn("总体抽取序号", table[0])

    def test_renderer_detail_probability_boundaries_come_from_reader_records(self):
        records = [copy.deepcopy(record) for record in self.records[:3]]
        for index, probability in enumerate((0.0, 0.008, 1.0), start=1):
            records[index - 1]["draw_index"] = index
            records[index - 1]["draw_result"]["probabilities"] = {
                "four_star": 1.0 - probability,
                "five_star": 0.0,
                "six_star": probability,
            }
        reader = TraceReaderStub(records)
        st = RecordingStreamlit(view="逐抽明细", columns="完整列")

        render_result(st, self.payload, reader)

        table = self.table_with_column(st, "六星概率")
        self.assertEqual([row["六星概率"] for row in table], [0.0, 0.008, 1.0])

    def test_renderer_without_trace_shows_detail_notice_without_reader(self):
        st = RecordingStreamlit(view="逐抽明细")

        render_result(st, self.payload, None)

        self.assertIn("本次运行未保存逐抽结果", st.infos)

    def test_legacy_trace_argument_is_rejected_without_reading_payload_records(self):
        st = RecordingStreamlit(view="逐抽明细")
        payload = dict(self.payload)
        payload["records"] = object()

        with self.assertRaises(TypeError):
            render_result(st, payload, None, trace_enabled=True)


if __name__ == "__main__":
    unittest.main()
