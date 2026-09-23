import copy
import unittest
from dataclasses import asdict

from dashboard.models import result_payload
from dashboard.views.simulation import _render_overview, render_result, render_summary_download
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
        self.dataframe_calls = []
        self.charts = []
        self.altair_charts = []
        self.infos = []
        self.captions = []
        self.writes = []
        self.downloads = []
        self.radio_calls = []
        self.category_options = ()
        self.column_config = type(
            "ColumnConfig",
            (),
            {"NumberColumn": staticmethod(
                lambda **kwargs: {"type_config": {"format": kwargs["format"]}}
            )},
        )()

    def columns(self, count):
        return [self] * count

    def expander(self, *args, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

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
        self.radio_calls.append((label, tuple(options), kwargs))
        if label == "结果视图":
            return self.view
        if label == "数据来源":
            return self.source
        if label == "明细列":
            return self.detail_columns
        return options[0]

    def dataframe(self, data, **kwargs):
        self.dataframes.append(data)
        self.dataframe_calls.append((data, kwargs))

    def bar_chart(self, data, **kwargs):
        self.charts.append(data)

    def altair_chart(self, chart, **kwargs):
        self.altair_charts.append(chart)

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
            ["模拟六星均值", "理论六星期望", "相对误差"],
        )
        summary = self.table_with_column(st, "范围")
        self.assertEqual(summary[-1]["范围"], "全实验（2轮）")
        self.assertEqual(st.downloads, [])
        render_summary_download(st, self.payload, key="summary-download-run-1")
        self.assertEqual(st.downloads[0][0], "下载汇总 JSON")
        self.assertNotIn(b'"records"', st.downloads[0][1]["data"])
        self.assertEqual(st.downloads[0][1]["key"], "summary-download-run-1")

    def test_overview_shortens_float_metrics_without_changing_payload(self):
        payload = dict(self.payload, mean_six_stars=1 / 3,
                       theoretical_expected_count=0.09599999999999997)
        st = RecordingStreamlit()

        _render_overview(st, payload)

        self.assertEqual(st.metrics[0][1], "0.3333")
        self.assertEqual(st.metrics[1][1], "0.0960")
        self.assertEqual(payload["theoretical_expected_count"], 0.09599999999999997)

    def test_result_view_uses_horizontal_radio_with_stable_owner_key(self):
        st = RecordingStreamlit(view="实验概览")

        render_result(st, self.payload, TraceReaderStub(self.records))

        label, options, kwargs = st.radio_calls[0]
        self.assertEqual(label, "结果视图")
        self.assertEqual(options, ("实验概览", "分类统计", "按抽次分析", "逐抽明细"))
        self.assertTrue(kwargs["horizontal"])
        self.assertEqual(kwargs["key"], "result-view-('history', 'run-1')")

    def test_overview_keeps_large_trial_counts_to_two_summary_rows(self):
        st = RecordingStreamlit()

        _render_overview(st, {
            "draws": 100, "bonus_draws": 10,
            "total_draws": 110, "trials": 100_000,
        })

        self.assertEqual(len(st.dataframes[0]), 2)
        self.assertEqual(st.dataframes[0][1]["总抽数"], 11_000_000)

    def test_overview_total_excludes_initial_history_draws(self):
        st = RecordingStreamlit()

        _render_overview(st, {
            "initial_pity": 29, "draws": 1, "bonus_draws": 10,
            "total_draws": 11, "trials": 3,
        })

        self.assertEqual(st.dataframes[0][1]["总抽数"], 33)

    def test_renderer_switches_category_subviews_without_reader_query(self):
        reader = TraceReaderStub(self.records)
        for category in ("星级", "六星构成", "六星具体角色", "奖励", "保底"):
            with self.subTest(category=category):
                st = RecordingStreamlit(view="分类统计", category=category, source="总计")
                render_result(st, self.payload, reader)
                self.assertEqual(reader.query_calls, [])
                self.assertTrue(st.dataframes)
                self.assertEqual(len(st.altair_charts), 1)
                self.assertIn("六星具体角色", st.category_options)

    def test_each_category_uses_the_shared_comparison_chart_with_source_unit(self):
        for category in ("星级", "六星构成", "六星具体角色", "奖励", "保底"):
            with self.subTest(category=category):
                st = RecordingStreamlit(view="分类统计", category=category, source="赠送")
                render_result(st, self.payload, TraceReaderStub(self.records))
                spec = st.altair_charts[0].to_dict()
                encoding = spec["layer"][0]["encoding"]
                axis = encoding["x"] if "yOffset" in encoding else encoding["y"]
                title = axis["title"]
                self.assertIn("赠送", title)
                self.assertTrue(
                    any(term in title for term in ("每轮平均数量", "奖励量", "触发次数"))
                )

    def test_unconfigured_rewards_show_explicit_empty_state(self):
        payload = copy.deepcopy(self.payload)
        payload["pool_config"]["rewards"] = []
        payload["source_summaries"]["total"]["mean_rewards"] = {}
        payload["theoretical_source_summaries"]["total"]["rewards"] = {}
        st = RecordingStreamlit(view="分类统计", category="奖励")

        render_result(st, payload, TraceReaderStub(self.records))

        self.assertEqual(st.altair_charts, [])
        self.assertTrue(any("奖励" in message for message in st.infos))

    def test_category_numeric_table_uses_twelve_significant_digit_number_columns(self):
        st = RecordingStreamlit(view="分类统计", category="星级")

        render_result(st, self.payload, TraceReaderStub(self.records))

        _, kwargs = st.dataframe_calls[-1]
        config = kwargs["column_config"]
        self.assertEqual(
            config["模拟均值"]["type_config"]["format"], "%.12g"
        )
        self.assertEqual(
            config["理论期望"]["type_config"]["format"], "%.12g"
        )

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
