import json
import unittest
from copy import deepcopy

import streamlit

from dashboard.models import result_payload
from dashboard.views.simulation import render_result
from lottery_simulator.engine import simulate
from lottery_simulator.rules.rule_1 import Rule1


class _Context:
    def __init__(self, owner=None, label=None):
        self.owner = owner
        self.label = label

    def __enter__(self):
        if self.owner is not None:
            self.previous_label = self.owner.active_expander
            self.owner.active_expander = self.label
        return self

    def __exit__(self, *unused):
        if self.owner is not None:
            self.owner.active_expander = self.previous_label
        return False


class _ColumnConfig:
    @staticmethod
    def NumberColumn(**kwargs):
        return kwargs


class RecordingStreamlit:
    def __init__(self, source="总计", reward_name="奖励A"):
        self.events = []
        self.metrics = []
        self.charts = []
        self.dataframes = []
        self.dataframe_kwargs = []
        self.labels = []
        self.downloads = []
        self.writes = []
        self.write_contexts = []
        self.active_expander = None
        self.source = source
        self.reward_name = reward_name
        self.column_config = _ColumnConfig

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
        return _Context(self, label)

    def dataframe(self, data, **kwargs):
        self.events.append(("dataframe", None))
        self.dataframes.append(data)
        self.dataframe_kwargs.append(kwargs)

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
        self.write_contexts.append((self.active_expander, value))

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
            simulate(rule, 2, seed=42, initial_pity=29, collect_records=True), rule, 0.25
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

        trace_table = next(table for table in st.dataframes if table and "总体抽取序号" in table[0])
        self.assertEqual(trace_table[0]["总体抽取序号"], 1)
        self.assertEqual(trace_table[0]["来源"], "主池")
        self.assertEqual(trace_table[0]["星级"], 4)
        self.assertEqual(trace_table[0]["角色"], "未配置角色名单")
        self.assertEqual(trace_table[0]["六星概率"], 0.008)
        trace_kwargs = next(
            kwargs for table, kwargs in zip(st.dataframes, st.dataframe_kwargs)
            if table is trace_table
        )
        self.assertEqual(
            trace_kwargs["column_config"]["六星概率"],
            {"format": "percent"},
        )
        label, download = st.downloads[0]
        self.assertEqual(label, "下载结果 JSON")
        self.assertEqual(download["file_name"], "simulation-result.json")
        self.assertEqual(download["mime"], "application/json")
        self.assertIsInstance(download["data"], bytes)
        self.assertIn("六星".encode("utf-8"), download["data"])
        self.assertEqual(json.loads(download["data"].decode("utf-8")), self.payload)

    def test_renderer_switches_all_summary_tables_between_sources(self):
        self.payload["source_summaries"]["main"]["mean_rarity_counts"] = {
            "4": 10.1, "5": 10.2, "6": 10.3,
        }
        self.payload["source_summaries"]["bonus"]["mean_rarity_counts"] = {
            "4": 20.1, "5": 20.2, "6": 20.3,
        }
        self.payload["source_summaries"]["total"]["mean_rarity_counts"] = {
            "4": 30.1, "5": 30.2, "6": 30.3,
        }
        self.payload["source_summaries"]["main"]["mean_six_star_categories"] = {
            "up": 11.1, "other_limited": 11.2, "standard": 11.3,
        }
        self.payload["source_summaries"]["bonus"]["mean_six_star_categories"] = {
            "up": 21.1, "other_limited": 21.2, "standard": 21.3,
        }
        self.payload["source_summaries"]["total"]["mean_six_star_categories"] = {
            "up": 31.1, "other_limited": 31.2, "standard": 31.3,
        }
        self.payload["source_summaries"]["main"]["mean_character_counts"]["UP-A"] = 12.1
        self.payload["source_summaries"]["bonus"]["mean_character_counts"]["UP-A"] = 22.1
        self.payload["source_summaries"]["total"]["mean_character_counts"]["UP-A"] = 32.1
        self.payload["source_summaries"]["main"]["mean_rewards"] = {
            "奖励A": 13.1, "奖励B": 13.2,
        }
        self.payload["source_summaries"]["bonus"]["mean_rewards"] = {
            "奖励A": 23.1, "奖励B": 23.2,
        }
        self.payload["source_summaries"]["total"]["mean_rewards"] = {
            "奖励A": 33.1, "奖励B": 33.2,
        }
        self.payload["source_distributions"]["main"]["reward_totals"]["奖励A"] = {
            "14.1": 1,
        }
        self.payload["source_distributions"]["bonus"]["reward_totals"]["奖励A"] = {
            "24.1": 1,
        }
        self.payload["source_distributions"]["total"]["reward_totals"]["奖励A"] = {
            "34.1": 1,
        }
        self.payload["source_summaries"]["main"]["mean_pity_triggers"] = {
            "five_star": 15.1, "six_star_hard": 15.2,
        }
        self.payload["source_summaries"]["bonus"]["mean_pity_triggers"] = {
            "five_star": 25.1, "six_star_hard": 25.2,
        }
        self.payload["source_summaries"]["total"]["mean_pity_triggers"] = {
            "five_star": 35.1, "six_star_hard": 35.2,
        }
        expected = {
            "主池": {
                "rarities": [10.1, 10.2, 10.3],
                "categories": [11.1, 11.2, 11.3],
                "character": 12.1,
                "rewards": [13.1, 13.2],
                "distribution": [{"奖励总量": 14.1, "实验次数": 1, "占比": 1.0}],
                "pity": [15.1, 15.2],
            },
            "赠送": {
                "rarities": [20.1, 20.2, 20.3],
                "categories": [21.1, 21.2, 21.3],
                "character": 22.1,
                "rewards": [23.1, 23.2],
                "distribution": [{"奖励总量": 24.1, "实验次数": 1, "占比": 1.0}],
                "pity": [25.1, 25.2],
            },
            "总计": {
                "rarities": [30.1, 30.2, 30.3],
                "categories": [31.1, 31.2, 31.3],
                "character": 32.1,
                "rewards": [33.1, 33.2],
                "distribution": [{"奖励总量": 34.1, "实验次数": 1, "占比": 1.0}],
                "pity": [35.1, 35.2],
            },
        }
        for label, source_values in expected.items():
            with self.subTest(source=label):
                st = RecordingStreamlit(source=label)

                render_result(st, self.payload, trace_enabled=False)

                rarity_table = self.table_with_column(st, "星级")
                self.assertEqual(
                    [row["模拟均值"] for row in rarity_table],
                    source_values["rarities"],
                )
                category_table = self.table_with_column(st, "类型")
                self.assertEqual(
                    [row["模拟均值"] for row in category_table],
                    source_values["categories"],
                )
                character_table = self.table_with_column(st, "角色")
                self.assertEqual(
                    character_table[0]["模拟均值"], source_values["character"]
                )
                reward_table = self.table_with_column(st, "奖励")
                self.assertEqual(
                    [row["模拟均值"] for row in reward_table],
                    source_values["rewards"],
                )
                reward_distribution = self.table_with_column(st, "奖励总量")
                self.assertEqual(
                    reward_distribution, source_values["distribution"]
                )
                pity_table = self.table_with_column(st, "保底类型")
                self.assertEqual(
                    [row["模拟均值"] for row in pity_table],
                    source_values["pity"],
                )

    def test_renderer_never_passes_records_to_dataframe_without_trace(self):
        st = RecordingStreamlit()

        render_result(st, self.payload, trace_enabled=False)

        self.assertNotIn(self.payload["records"], st.dataframes)
        self.assertIn("本次运行未保存逐抽记录", st.labels)

    def test_current_and_saved_results_share_trace_and_folded_run_metadata(self):
        self.payload.update(
            id=9, sampling_version=1, rng_algorithm="python.random.Random",
            python_implementation="CPython", python_version="3.12.3",
        )
        before = deepcopy(self.payload)
        trace_tables = []
        for saved in (False, True):
            with self.subTest(saved_snapshot=saved):
                st = RecordingStreamlit()
                render_result(st, self.payload, trace_enabled=True, saved_snapshot=saved)
                trace_tables.append(self.table_with_column(st, "总体抽取序号"))
                self.assertIn(("运行信息", {
                    "sampling_version": 1, "rng_algorithm": "python.random.Random",
                    "python_implementation": "CPython", "python_version": "3.12.3",
                }), st.write_contexts)
                downloaded = json.loads(st.downloads[0][1]["data"].decode("utf-8"))
                self.assertEqual(downloaded, before)
                self.assertIn("draw_result", downloaded["records"][0])
                self.assertEqual(self.payload, before)
        self.assertEqual(trace_tables[0], trace_tables[1])
        self.assertEqual(trace_tables[1][0]["六星概率"], 0.008)

    def test_renderer_uses_real_number_column_percent_for_raw_probability_boundaries(self):
        records = []
        for index, probability in enumerate((0.0, 0.008, 1.0), start=1):
            record = deepcopy(self.payload["records"][0])
            record["draw_index"] = index
            record["draw_result"]["probabilities"] = {
                "four_star": 1.0 - probability, "five_star": 0.0, "six_star": probability,
            }
            records.append(record)
        self.payload["records"] = records
        before = deepcopy(self.payload)
        st = RecordingStreamlit()
        st.column_config = streamlit.column_config

        render_result(st, self.payload, trace_enabled=True)

        table = self.table_with_column(st, "总体抽取序号")
        self.assertEqual([row["六星概率"] for row in table], [0.0, 0.008, 1.0])
        kwargs = next(kwargs for data, kwargs in zip(st.dataframes, st.dataframe_kwargs)
                      if data is table)
        for name in ("四星概率", "五星概率", "六星概率"):
            self.assertEqual(kwargs["column_config"][name]["type_config"]["format"], "percent")
        self.assertEqual(self.payload, before)
        self.assertEqual(json.loads(st.downloads[0][1]["data"].decode("utf-8")), before)


if __name__ == "__main__":
    unittest.main()
