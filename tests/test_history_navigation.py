import unittest
from types import SimpleNamespace
from unittest.mock import patch

from dashboard.views.history import (
    _clear_deleted_run_state,
    _render_comparison,
    apply_pending_reuse,
    render_history,
)
from lottery_simulator.rules.pool_config import load_pool_config


class FakeStreamlit:
    def __init__(self, *, buttons=()):
        self.session_state = {}
        self.buttons = set(buttons)
        self.captions = []
        self.infos = []
        self.warnings = []
        self.errors = []
        self.dataframes = []
        self.widgets = []

    def header(self, value):
        self.widgets.append(("header", value))

    def caption(self, value):
        self.captions.append(value)

    def selectbox(self, label, options, **kwargs):
        self.widgets.append(("selectbox", label, options))
        return options[0]

    def date_input(self, label, **kwargs):
        self.widgets.append(("date_input", label))
        return None

    def number_input(self, label, **kwargs):
        self.widgets.append(("number_input", label))
        return 1

    def dataframe(self, value, **kwargs):
        self.dataframes.append(value)

    def multiselect(self, label, options, **kwargs):
        self.widgets.append(("multiselect", label, options, kwargs))
        return self.session_state.get(kwargs.get("key"), [])

    def columns(self, count):
        return [self] * count

    def subheader(self, value):
        self.widgets.append(("subheader", value))

    def expander(self, *args, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def text(self, value):
        self.widgets.append(("text", value))

    def code(self, value, **kwargs):
        self.widgets.append(("code", value))

    def button(self, label, **kwargs):
        self.widgets.append(("button", label, kwargs))
        return not kwargs.get("disabled", False) and label in self.buttons

    def warning(self, value):
        self.warnings.append(value)

    def error(self, value):
        self.errors.append(value)

    def info(self, value):
        self.infos.append(value)

    def download_button(self, *args, **kwargs):
        self.widgets.append(("download_button", args[0]))

    def rerun(self):
        return None


class FakeRepository:
    def __init__(self, rows):
        self.rows = rows
        self.readers = 0
        self.deleted = []

    def list_runs(self, filters, limit, offset):
        return self.rows[offset : offset + limit]

    def count_runs(self, filters):
        return len(self.rows)

    def get_run(self, run_id):
        return next((row for row in self.rows if row["id"] == run_id), None)

    def get_trace_reader(self, run_id):
        self.readers += 1
        raise AssertionError("history comparison must not create a detail reader")

    def delete_run(self, run_id):
        self.deleted.append(run_id)


def run_row(run_id="run-1", *, trials=3, trace=True):
    return {
        "id": run_id,
        "created_at": "2026-09-20T00:00:00+00:00",
        "rule_name": "rule1",
        "rule_version": "2.0",
        "schema_version": 4,
        "main_draws": 2,
        "draws": 2,
        "trials": trials,
        "initial_pity": 4,
        "initial_five_star_pity": 5,
        "seed": 42,
        "trace_enabled": trace,
        "pool_config": load_pool_config().to_dict(),
        "mean_six_stars": 1,
        "mean_count_error": 0,
        "bonus_draws": 0,
        "total_draws": 2,
        "theoretical_expected_count": 1,
        "theoretical_mean_interval": 1,
        "mean_count_relative_error": 0,
        "record_count": 6 if trace else 0,
        "duration_seconds": 0.1,
    }


class HistoryNavigationTest(unittest.TestCase):
    def _buttons(self, st):
        return {widget[1]: widget[2] for widget in st.widgets if widget[0] == "button"}

    def test_zero_selection_disables_single_record_actions(self):
        st = FakeStreamlit()
        repository = FakeRepository([run_row()])

        render_history(st, repository)

        buttons = self._buttons(st)
        self.assertIn("查看结果", buttons)
        self.assertTrue(buttons["查看结果"]["disabled"])
        self.assertTrue(buttons["复用参数"]["disabled"])
        self.assertTrue(buttons["删除历史（不可撤销）"]["disabled"])
        self.assertTrue(any("选择一条" in value for value in st.infos))

    def test_history_list_has_total_and_single_view_navigates_without_reader(self):
        row = run_row()
        st = FakeStreamlit(buttons={"查看结果"})
        st.session_state["selected_history_ids"] = [row["id"]]
        repository = FakeRepository([row])

        with patch("dashboard.views.history._render_comparison") as comparison:
            render_history(st, repository)

        self.assertTrue(any("共 1 条" in value for value in st.captions))
        self.assertEqual(st.dataframes[0][0].get("Trace记录数"), 6)
        self.assertIn("查看结果", self._buttons(st))
        self.assertEqual(st.session_state["selected_result"], ("history", "run-1"))
        self.assertEqual(st.session_state["_pending_page"], "实验结果")
        comparison.assert_not_called()
        self.assertEqual(repository.readers, 0)

    def test_one_selection_enables_reuse_and_delete_with_complete_id(self):
        row = run_row("12345678-aaaa-bbbb-cccc-000000000001")
        st = FakeStreamlit(buttons={"复用参数", "删除历史（不可撤销）"})
        st.session_state["selected_history_ids"] = [row["id"]]

        with patch("dashboard.views.history._render_comparison"):
            render_history(st, FakeRepository([row]))

        buttons = self._buttons(st)
        self.assertIn("复用参数", buttons)
        self.assertFalse(buttons["复用参数"]["disabled"])
        self.assertFalse(buttons["删除历史（不可撤销）"]["disabled"])
        self.assertIn(("code", row["id"]), st.widgets)
        self.assertEqual(st.session_state["pending_reuse_id"], row["id"])
        self.assertEqual(st.session_state["pending_delete_id"], row["id"])

    def test_two_selections_keep_summary_comparison_and_disable_single_actions(self):
        rows = [run_row("run-1"), run_row("run-2")]
        st = FakeStreamlit()
        st.session_state["selected_history_ids"] = [row["id"] for row in rows]

        with patch("dashboard.views.history._render_overview") as overview, \
                patch("dashboard.views.history._render_category") as category:
            render_history(st, FakeRepository(rows))

        buttons = self._buttons(st)
        self.assertIn("查看结果", buttons)
        self.assertTrue(buttons["查看结果"]["disabled"])
        self.assertTrue(buttons["复用参数"]["disabled"])
        self.assertTrue(buttons["删除历史（不可撤销）"]["disabled"])
        self.assertTrue(any("只能比较" in value for value in st.infos))
        self.assertEqual(overview.call_count, 2)
        self.assertEqual(category.call_count, 2)

    def test_more_than_two_selections_are_trimmed_before_rendering_comparison(self):
        rows = [run_row(f"run-{number}") for number in range(1, 4)]
        st = FakeStreamlit()
        st.session_state["selected_history_ids"] = [row["id"] for row in rows]

        with patch("dashboard.views.history._render_comparison") as comparison:
            render_history(st, FakeRepository(rows))

        self.assertEqual(st.session_state["selected_history_ids"], ["run-1", "run-2"])
        self.assertTrue(any("最多选择两次" in value for value in st.errors))
        self.assertEqual(comparison.call_count, 2)

    def test_comparison_keeps_summary_without_detail_reader(self):
        rows = [run_row("run-1"), run_row("run-2")]
        st = FakeStreamlit()
        st.session_state["selected_history_ids"] = ["run-1", "run-2"]
        repository = FakeRepository(rows)

        with patch("dashboard.views.history._render_overview") as overview, \
                patch("dashboard.views.history._render_category") as category:
            render_history(st, repository)

        self.assertEqual(overview.call_count, 2)
        self.assertEqual(category.call_count, 2)
        self.assertEqual(repository.readers, 0)

    def test_comparison_categories_use_each_run_as_widget_owner(self):
        rows = [run_row("run-1"), run_row("run-2")]
        st = FakeStreamlit()
        st.session_state["selected_result"] = ("history", "run-1")

        with patch("dashboard.views.history._render_overview"), \
                patch("dashboard.views.history._render_config_summary"), \
                patch("dashboard.views.history._render_saved_summary_download"), \
                patch("dashboard.views.history._render_category") as category:
            for row in rows:
                _render_comparison(st, row)

        self.assertEqual(
            [call.kwargs["owner"] for call in category.call_args_list],
            [("history", "run-1"), ("history", "run-2")],
        )

    def test_page_or_filter_trim_cancels_stale_delete_confirmation(self):
        first, second = run_row("run-1"), run_row("run-2")
        st = FakeStreamlit(buttons={"确认删除（不可撤销）"})
        st.session_state.update(
            selected_history_ids=[second["id"]], pending_delete_id=first["id"],
        )
        repository = FakeRepository([first, second])

        with patch("dashboard.views.history._render_comparison"):
            render_history(st, repository)

        self.assertEqual(st.session_state["selected_history_ids"], [second["id"]])
        self.assertNotIn("pending_delete_id", st.session_state)
        self.assertEqual(repository.deleted, [])

    def test_colliding_short_ids_are_selected_and_viewed_by_complete_id(self):
        first = run_row("12345678-aaaa-bbbb-cccc-000000000001")
        second = run_row("12345678-dddd-eeee-ffff-000000000002")
        st = FakeStreamlit(buttons={"查看结果"})
        st.session_state["selected_history_ids"] = [second["id"]]

        with patch("dashboard.views.history._render_comparison") as comparison:
            render_history(st, FakeRepository([first, second]))

        multiselect = next(
            widget for widget in st.widgets if widget[0] == "multiselect"
        )
        labels = [multiselect[3]["format_func"](run_id) for run_id in multiselect[2]]
        self.assertEqual(len(set(labels)), 2)
        self.assertTrue(
            all(run_id in label for run_id, label in zip(multiselect[2], labels))
        )
        self.assertEqual(st.dataframes[0][0]["运行 ID"], "12345678")
        self.assertEqual(st.dataframes[0][1]["运行 ID"], "12345678")
        self.assertEqual(st.session_state["selected_result"], ("history", second["id"]))
        comparison.assert_not_called()

    def test_reuse_accepts_multi_trial_trace_and_only_updates_draft(self):
        row = run_row(trials=3, trace=True)
        st = FakeStreamlit()
        st.session_state["pending_reuse_id"] = row["id"]
        repository = FakeRepository([row])

        with patch("dashboard.views.history.update_draft_from_history") as update, \
                patch("dashboard.views.history.set_pool_config_editor_state"):
            apply_pending_reuse(st, repository)

        update.assert_called_once_with(st, row)
        self.assertEqual(st.session_state["trials"], 3)
        self.assertTrue(st.session_state["trace"])
        self.assertNotIn("current_job_id", st.session_state)
        self.assertEqual(st.session_state["_pending_page"], "新建实验")

    def test_delete_state_clears_only_deleted_run_pagination_and_downloads(self):
        st = SimpleNamespace(session_state={
            "selected_history_ids": ["run-1", "run-2"],
            "selected_result": ("history", "run-1"),
            "trace-page": 4,
            "trace-download": b"cached",
            "trace-filter-signature": ("run-1", ()),
            "result-view-run-1": "逐抽明细",
            "history-download-run-1": True,
            "trace-page-size-run-2": 100,
        })

        _clear_deleted_run_state(st, "run-1")

        self.assertEqual(st.session_state["selected_history_ids"], ["run-2"])
        self.assertNotIn("selected_result", st.session_state)
        for key in ("trace-page", "trace-download", "trace-filter-signature",
                    "result-view-run-1", "history-download-run-1"):
            self.assertNotIn(key, st.session_state)
        self.assertEqual(st.session_state["trace-page-size-run-2"], 100)

    def test_delete_keeps_shared_trace_cache_owned_by_another_result(self):
        st = SimpleNamespace(session_state={
            "selected_history_ids": ["run-1", "run-2"],
            "selected_result": ("history", "run-2"),
            "trace-page": 4,
            "trace-download": b"run-2-cache",
            "trace-filter-signature": ("run-2", ()),
        })

        _clear_deleted_run_state(st, "run-1")

        self.assertEqual(st.session_state["selected_history_ids"], ["run-2"])
        self.assertEqual(st.session_state["selected_result"], ("history", "run-2"))
        self.assertEqual(st.session_state["trace-page"], 4)
        self.assertEqual(st.session_state["trace-download"], b"run-2-cache")

    def test_delete_clears_tuple_owner_cache_and_its_result_widgets(self):
        owner = ("job", "run-1")
        st = SimpleNamespace(session_state={
            "trace-filter-signature": (owner, ()),
            "trace-download": b"run-1-cache",
            f"result-view-{owner}": "逐抽明细",
            f"trace-trial-{owner}": "全部轮次",
        })
        _clear_deleted_run_state(st, "run-1")
        self.assertNotIn("trace-download", st.session_state)
        self.assertNotIn(f"result-view-{owner}", st.session_state)
        self.assertNotIn(f"trace-trial-{owner}", st.session_state)


if __name__ == "__main__":
    unittest.main()
