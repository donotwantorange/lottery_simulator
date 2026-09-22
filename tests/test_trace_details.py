import json
import unittest

from dashboard.trace import trace_rows
from dashboard.views.simulation import render_result


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _Streamlit:
    def __init__(self, view="实验概览"):
        self.view = view
        self.session_state = {}
        self.calls = []
        self.tables = []
        self.downloads = []

    def selectbox(self, label, options, **kwargs):
        self.calls.append(("selectbox", label))
        if label == "结果视图":
            return self.view
        return options[0]

    def radio(self, label, options, **kwargs):
        self.calls.append(("radio", label))
        return options[0]

    def number_input(self, label, **kwargs):
        self.calls.append(("number_input", label))
        return kwargs.get("value", kwargs.get("min_value", 1))

    def checkbox(self, label, **kwargs):
        self.calls.append(("checkbox", label))
        return False

    def button(self, label, **kwargs):
        self.calls.append(("button", label))
        return False

    def columns(self, count):
        return [self] * count

    def metric(self, *args, **kwargs):
        self.calls.append(("metric", args[0]))

    def dataframe(self, data, **kwargs):
        self.tables.append(data)

    def bar_chart(self, data, **kwargs):
        self.tables.append(data)

    def line_chart(self, data, **kwargs):
        self.tables.append(data)

    def expander(self, *args, **kwargs):
        return _Context()

    def info(self, value):
        self.calls.append(("info", value))

    def caption(self, value):
        self.calls.append(("caption", value))

    def warning(self, value):
        self.calls.append(("warning", value))

    def download_button(self, label, **kwargs):
        self.downloads.append((label, kwargs))

    def write(self, *args, **kwargs):
        pass


class _Reader:
    def __init__(self):
        self.query_calls = []
        self.iter_calls = []
        self.position_calls = []
        self.records = [{"trial_index": 1, "draw_index": 1, "source": "main"}]

    def query_records(self, filters, *, limit=100, offset=0):
        self.query_calls.append((filters, limit, offset))
        return self.records[offset : offset + limit], len(self.records)

    def iter_records(self, filters, *, batch_size=1000):
        self.iter_calls.append(filters)
        yield from self.records

    def position_counts(self, **kwargs):
        self.position_calls.append(kwargs)
        return [{
            "source_index": 1, "observations": 1,
            "four_count": 1, "five_count": 0, "six_count": 0,
            "four_rate": 1.0, "five_rate": 0.0, "six_rate": 0.0,
        }]


class _RoleFilterStreamlit(_Streamlit):
    def __init__(self):
        super().__init__("逐抽明细")
        self.role_options = ()

    def selectbox(self, label, options, **kwargs):
        if label == "星级":
            return 4
        if label == "角色":
            self.role_options = tuple(options)
            return "四星A" if "四星A" in options else options[0]
        return super().selectbox(label, options, **kwargs)


class _EmptyPositionReader(_Reader):
    def position_counts(self, **kwargs):
        self.position_calls.append(kwargs)
        return []


class TraceDetailsTest(unittest.TestCase):
    def test_trace_rows_add_trial_and_in_trial_draw_columns(self):
        record = {
            "trial_index": 2,
            "draw_index": 7,
            "source": "main",
            "source_index": 7,
            "main_draws_completed": 7,
            "bonus_event": None,
            "main_state_before": {"misses_since_six_star": 0, "misses_since_five_or_higher": 0},
            "main_state_after": {"misses_since_six_star": 1, "misses_since_five_or_higher": 1},
            "draw_result": {
                "outcome": {
                    "rarity": 4, "character_name": None, "is_up": False,
                    "is_limited": False, "rewards": {},
                    "five_star_pity_triggered": False,
                    "six_star_hard_pity_triggered": False,
                },
                "probabilities": {"four_star": 0.9, "five_star": 0.09, "six_star": 0.01},
                "state_before": {"misses_since_six_star": 0, "misses_since_five_or_higher": 0},
                "state_after": {"misses_since_six_star": 1, "misses_since_five_or_higher": 1},
            },
        }
        self.assertEqual(trace_rows([record], [])[0]["轮次"], 2)
        self.assertEqual(trace_rows([record], [])[0]["轮内总抽次"], 7)

    def test_overview_does_not_query_reader(self):
        st = _Streamlit("实验概览")
        reader = _Reader()
        render_result(st, {"trials": 1, "draws": 1, "bonus_draws": 0, "total_draws": 1,
                           "mean_six_stars": 0, "theoretical_expected_count": 0,
                           "mean_count_error": 0, "mean_count_relative_error": None,
                           "rule_name": "rule_1", "rule_version": "2.0",
                           "initial_main_draws": 0, "final_main_draws": 1,
                           "seed": 1, "duration_seconds": 0,
                           "source_summaries": {"main": {}, "bonus": {}, "total": {}},
                           "theoretical_source_summaries": {"main": {}, "bonus": {}, "total": {}},
                           "pool_config": {}}, reader)
        self.assertEqual(reader.query_calls, [])
        self.assertEqual(reader.position_calls, [])

    def test_download_uses_all_matching_records(self):
        st = _Streamlit("逐抽明细")
        reader = _Reader()
        reader.records = [{"trial_index": 1, "draw_index": i, "source": "main"} for i in (1, 2, 3)]
        st.button = lambda label, **kwargs: label == "准备下载"
        payload = {"id": "run", "trials": 1, "draws": 3, "bonus_draws": 0,
                   "total_draws": 3, "trace_enabled": True, "pool_config": {}}
        render_result(st, payload, reader)
        self.assertEqual(len(reader.iter_calls), 1)
        self.assertEqual(len(json.loads(st.downloads[0][1]["data"].splitlines()[1])["record"]), 3)

    def test_role_filter_lists_configured_four_star_name_and_binds_rarity(self):
        st = _RoleFilterStreamlit()
        reader = _Reader()
        payload = {
            "id": "run", "trials": 1, "draws": 3, "bonus_draws": 0,
            "total_draws": 3,
            "pool_config": {
                "four_star_characters": [{"name": "四星A", "weight": 1.0}],
                "five_star_characters": [{"name": "五星A", "weight": 1.0}],
                "six_star_characters": [{"name": "六星A"}],
            },
        }
        from dashboard.views.trace_details import render_trace_details

        render_trace_details(st, payload, reader)

        self.assertIn("四星A", st.role_options)
        filters = reader.query_calls[0][0]
        self.assertEqual((filters.rarity, filters.character_name), (4, "四星A"))

    def test_empty_position_aggregate_shows_no_data(self):
        from dashboard.views.trace_details import render_position_analysis

        st = _Streamlit("按抽次分析")
        reader = _EmptyPositionReader()
        render_position_analysis(st, {"trials": 1, "draws": 3, "bonus_draws": 0}, reader)

        self.assertIn("无数据", st.calls[-1][1])


if __name__ == "__main__":
    unittest.main()
