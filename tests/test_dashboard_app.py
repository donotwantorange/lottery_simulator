from contextlib import closing
from dataclasses import replace
from datetime import date
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import streamlit as st
from streamlit.testing.v1 import AppTest
from streamlit.runtime.secrets import AttrDict

from dashboard.jobs import JobManager
from dashboard.models import JobState, RunParameters, result_payload, write_json
from dashboard.repository import HistoryRepository
from dashboard.worker import run
from lottery_simulator.engine import simulate
from lottery_simulator.rules.pool_config import PoolConfig, load_pool_config
from lottery_simulator.rules.rule_1 import Rule1


APP = Path(__file__).resolve().parents[1] / "dashboard/app.py"
PITY_LABEL = "假设主池已累计多少抽仍未出6星"
FIVE_STAR_PITY_LABEL = "假设主池已连续多少抽未出5星及以上"


def render_fixture():
    import streamlit as st
    from dashboard.models import result_payload
    from dashboard.views.simulation import render_result
    from lottery_simulator.engine import simulate
    from lottery_simulator.rules.rule_1 import Rule1
    rule = Rule1()
    render_result(st, result_payload(simulate(rule, 2, seed=42, initial_pity=29),
                                    rule, 0.25), True)


class ResultRenderingRegressionTest(unittest.TestCase):
    def test_real_renderer_has_no_deprecated_width_warnings(self):
        with self.assertNoLogs("streamlit.deprecation_util", level="WARNING"):
            app = AppTest.from_function(render_fixture).run()
        self.assertEqual(len(app.exception), 0)

    def test_error_metrics_are_magnitudes_while_payload_remains_signed(self):
        app = AppTest.from_function(render_fixture).run()
        self.assertEqual(len(app.exception), 0)
        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(metrics["绝对误差"], "0.096000")
        self.assertEqual(metrics["相对误差"], "100.0000%")
        rule = Rule1()
        payload = result_payload(simulate(rule, 2, seed=42, initial_pity=29), rule, 0.25)
        self.assertAlmostEqual(payload["mean_count_error"], -0.096)
        self.assertEqual(payload["mean_count_relative_error"], -1.0)


class DashboardAppTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        environment = patch.dict(os.environ, {
            "APP_ENVIRONMENT": "development", "APP_AUTH_MODE": "disabled",
            "STREAMLIT_SERVER_ADDRESS": "127.0.0.1", "ALLOWED_EMAILS": "",
            "DASHBOARD_SYNC_JOBS": "1", "LOTTERY_DATA_DIR": str(self.root),
        })
        environment.start()
        self.addCleanup(environment.stop)
        old_address = st.get_option("server.address")
        st.config.set_option("server.address", "127.0.0.1")
        self.addCleanup(st.config.set_option, "server.address", old_address)

    def load(self):
        self.assertTrue(APP.exists(), "Missing runnable dashboard/app.py")
        with patch("streamlit.user_info._get_user_info", return_value={"is_logged_in": False}):
            app = AppTest.from_file(str(APP)).run()
        self.assertEqual(len(app.exception), 0)
        return app

    @staticmethod
    def widget(elements, label):
        return next(element for element in elements if element.label == label)

    def test_confirmed_copy_trace_gate_and_invalid_work_preserve_parameters(self):
        app = self.load()
        self.widget(app.number_input, PITY_LABEL).set_value(29)
        self.widget(app.number_input, "实验轮数").set_value(2).run()
        trace = self.widget(app.toggle, "Trace")
        self.assertTrue(trace.disabled)
        self.assertIn("单轮", trace.help)
        self.widget(app.number_input, "主池抽数").set_value(10_000_000)
        self.widget(app.number_input, "实验轮数").set_value(11)
        self.widget(app.button, "开始模拟").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("超过上限" in error.value for error in app.error))
        self.assertEqual(self.widget(app.number_input, "主池抽数").value, 10_000_000)
        self.assertEqual(self.widget(app.number_input, PITY_LABEL).value, 29)
        self.assertIsNone(app.session_state.filtered_state.get("current_job_id"))
        self.assertEqual(list(self.root.glob("jobs/*/state.json")), [])

    def test_deployment_database_override_is_used_by_page_and_worker(self):
        database = self.root / "lottery.sqlite3"
        with patch.dict(os.environ, {"LOTTERY_DB_PATH": str(database)}):
            app = self.load()
            self.widget(app.button, "开始模拟").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(database.is_file(), "Deployment database must receive simulations")
        self.assertFalse((self.root / "history_v2.sqlite3").exists())
        runs = HistoryRepository(database).list_runs({}, 20, 0)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["main_draws"], 100)

    def test_repository_initialization_failure_shows_safe_read_only_error_before_business_ui(self):
        with (patch.object(HistoryRepository, "initialize",
                           side_effect=sqlite3.DatabaseError("synthetic migration detail")),
              patch("streamlit.user_info._get_user_info", return_value={"is_logged_in": False}),
              self.assertLogs(level="ERROR") as logs):
            app = AppTest.from_file(str(APP)).run()

        self.assertTrue(any("History database initialization failed" in item for item in logs.output))
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(
            [item.value for item in app.error],
            ["历史数据库暂不可用；当前为只读错误页。请联系管理员检查迁移或从备份恢复。"],
        )
        self.assertEqual(len(app.title), 0)
        self.assertEqual(len(app.number_input), 0)
        self.assertNotIn("synthetic migration detail", " ".join(item.value for item in app.error))

    def repository(self):
        repository = HistoryRepository(self.root / "history_v2.sqlite3")
        repository.initialize()
        return repository

    def test_default_database_is_v2_and_legacy_database_is_never_read_or_changed(self):
        legacy = self.root / "history.sqlite3"
        legacy.write_bytes(b"legacy database must stay untouched")
        before = legacy.read_bytes()

        app = self.load()

        self.assertEqual(len(app.exception), 0)
        self.assertTrue((self.root / "history_v2.sqlite3").is_file())
        self.assertEqual(legacy.read_bytes(), before)

    def test_configuration_sections_render_default_editors_and_utf8_download(self):
        app = self.load()

        self.assertIn("高级设置", [item.label for item in app.expander])
        self.assertIn("奖池与奖励设置", [item.label for item in app.expander])
        character_editor = next(item for item in app.dataframe
                                if item.key == "pool_character_editor")
        reward_editor = next(item for item in app.dataframe if item.key == "pool_reward_editor")
        self.assertEqual(len(character_editor.value), 9)
        self.assertEqual(len(reward_editor.value), 2)
        self.assertEqual(list(character_editor.value.columns),
                         ["角色名称", "是否UP", "是否限定", "UP权重"])
        self.assertEqual(list(reward_editor.value.columns),
                         ["奖励名称", "四星", "五星", "六星"])
        self.widget(app.download_button, "导出配置 JSON")

    def test_empty_reward_configuration_keeps_four_columns_available_for_new_rows(self):
        raw = load_pool_config().to_dict()
        raw["rewards"] = []
        app = self.load()

        self.widget(app.file_uploader, "导入配置 JSON").set_value((
            "no-rewards.json", json.dumps(raw).encode("utf-8"), "application/json",
        )).run()

        reward_editor = next(item for item in app.dataframe if item.key == "pool_reward_editor")
        self.assertEqual(list(reward_editor.value.columns),
                         ["奖励名称", "四星", "五星", "六星"])
        self.assertEqual(len(reward_editor.value), 0)

    def test_disabling_five_star_pity_disables_and_zeroes_initial_progress(self):
        app = self.load()
        self.widget(app.number_input, FIVE_STAR_PITY_LABEL).set_value(7)

        self.widget(app.toggle, "启用五星保底").set_value(False).run()

        initial = self.widget(app.number_input, FIVE_STAR_PITY_LABEL)
        self.assertTrue(initial.disabled)
        self.assertEqual(initial.value, 0)

    def test_invalid_uploaded_configuration_is_safe_and_never_creates_job_or_history(self):
        app = self.load()
        self.widget(app.file_uploader, "导入配置 JSON").set_value(
            ("private.json", b'{"up_share": "private-invalid"}', "application/json")
        ).run()

        self.widget(app.button, "开始模拟").click().run()

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("配置 JSON 无效" in item.value for item in app.error))
        self.assertNotIn("private-invalid", " ".join(item.value for item in app.error))
        self.assertEqual(list(self.root.glob("jobs/*/state.json")), [])
        self.assertEqual(self.repository().list_runs({}, 10, 0), [])

    def test_uploaded_configuration_and_initial_five_pity_are_saved_as_job_snapshot(self):
        raw = load_pool_config().to_dict()
        raw["up_share"] = 0.6
        raw["six_star_characters"][0]["name"] = "自定义UP"
        app = self.load()
        self.widget(app.file_uploader, "导入配置 JSON").set_value((
            "custom.json", json.dumps(raw, ensure_ascii=False).encode("utf-8"),
            "application/json",
        )).run()
        self.widget(app.number_input, FIVE_STAR_PITY_LABEL).set_value(7)

        self.start_small(app)

        rows = self.repository().list_runs({}, 10, 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pool_config"]["up_share"], 0.6)
        self.assertEqual(rows[0]["pool_config"]["six_star_characters"][0]["name"], "自定义UP")
        self.assertEqual(rows[0]["initial_five_star_pity"], 7)

    def test_restore_default_replaces_imported_configuration(self):
        raw = load_pool_config().to_dict()
        raw["up_share"] = 0.6
        app = self.load()
        self.widget(app.file_uploader, "导入配置 JSON").set_value((
            "custom.json", json.dumps(raw).encode("utf-8"), "application/json",
        )).run()
        self.assertEqual(self.widget(app.number_input, "UP占比").value, 0.6)

        self.widget(app.button, "恢复默认配置").click().run()

        self.assertEqual(self.widget(app.number_input, "UP占比").value, 0.5)

    def seed_history(self):
        repository = self.repository()
        ids = []
        for index in range(3):
            rule = Rule1()
            payload = result_payload(simulate(rule, index + 2, trials=2 if index == 1 else 1,
                                              seed=42 + index,
                                              initial_pity=29), rule, 0.25)
            if index == 0:
                payload["rule_name"] = "retired-rule"
            if index == 1:
                payload["rule_version"] = "0.9"
            ids.append(repository.save_run(payload, trace_enabled=index != 1))
        with closing(sqlite3.connect(repository.path)) as connection, connection:
            for index, run_id in enumerate(ids):
                connection.execute("UPDATE simulation_runs SET created_at=? WHERE id=?",
                                   (f"2026-09-{10 + index}T12:00:00+00:00", run_id))
        return repository, ids

    def test_history_workflow(self):
        repository, ids = self.seed_history()
        app = self.load()
        self.assertIn("历史规则", [item.label for item in app.selectbox])
        self.assertEqual(app.dataframe[0].value["运行 ID"].tolist(), ids[::-1])
        self.widget(app.selectbox, "历史 Trace").set_value("不含 Trace").run()
        self.assertEqual(app.dataframe[0].value["运行 ID"].tolist(), [ids[1]])
        self.widget(app.selectbox, "历史 Trace").set_value("全部").run()
        self.widget(app.selectbox, "历史规则").set_value("retired-rule").run()
        self.assertEqual(app.dataframe[0].value["运行 ID"].tolist(), [ids[0]])
        self.widget(app.selectbox, "历史规则").set_value("全部").run()
        self.widget(app.multiselect, "选择历史运行").set_value(ids[1:]).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.metric), 30)
        self.assertTrue(any("统计口径不同" in item.value for item in app.warning))
        self.widget(app.multiselect, "选择历史运行").set_value(ids).run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("最多选择两次运行" in item.value for item in app.error))
        self.assertEqual(app.session_state["selected_history_ids"], ids[:2])
        self.assertEqual(len(app.metric), 30)
        self.assertEqual(len(app.get("download_button")), 3)
        self.assertTrue(any("未保存概率曲线" in item.value for item in app.info))
        with (patch("streamlit.elements.lib.policies._shown_default_value_warning", False),
              self.assertNoLogs("streamlit.elements.lib.policies", level="WARNING")):
            self.widget(app.button, "复用参数 " + ids[1]).click().run()
        self.assertEqual(len(app.exception), 0)
        for key, value in {"draws": 3, "trials": 2, "initial_pity": 29,
                           "seed_text": "43", "rule_name": "rule1", "trace": False}.items():
            self.assertEqual(app.session_state[key], value)
        self.assertEqual(self.widget(app.number_input, "主池抽数").value, 3)
        self.assertEqual(self.widget(app.number_input, "实验轮数").value, 2)
        self.assertEqual(self.widget(app.number_input, PITY_LABEL).value, 29)
        self.assertEqual(self.widget(app.text_input, "随机种子（留空自动生成）").value, "43")
        self.assertTrue(self.widget(app.toggle, "Trace").disabled)
        self.assertEqual(list(self.root.glob("jobs/*/state.json")), [])
        self.assertIsNone(app.session_state.filtered_state.get("current_job_id"))
        self.assertEqual(len(repository.list_runs({}, 20, 0)), 3)
        self.widget(app.button, "删除历史 " + ids[0]).click().run()
        self.assertIsNotNone(repository.get_run(ids[0]))
        self.assertTrue(repository.get_run(ids[0], True)["records"])
        self.widget(app.button, "取消删除").click().run()
        self.assertIsNotNone(repository.get_run(ids[0]))
        self.assertNotIn("确认删除", [button.label for button in app.button])
        self.widget(app.button, "删除历史 " + ids[0]).click().run()
        self.widget(app.button, "确认删除").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertIsNone(repository.get_run(ids[0]))
        self.assertEqual(app.session_state["selected_history_ids"], [ids[1]])
        with closing(sqlite3.connect(repository.path)) as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM draw_records WHERE run_id=?", (ids[0],)
            ).fetchone()[0], 0)
        self.assertTrue(all(not isinstance(value, HistoryRepository)
                            for value in app.session_state.filtered_state.values()))

    def test_history_reuse_restores_full_configuration_and_initial_five_star_pity(self):
        raw = load_pool_config().to_dict()
        raw["up_share"] = 0.6
        raw["six_star_characters"][0]["name"] = "历史UP"
        rule = Rule1(config=PoolConfig.from_dict(raw))
        payload = result_payload(
            simulate(rule, 2, seed=42, initial_five_star_pity=7), rule, 0.25
        )
        repository = self.repository()
        run_id = repository.save_run(payload, trace_enabled=True)
        app = self.load()
        self.widget(app.multiselect, "选择历史运行").set_value([run_id]).run()

        self.widget(app.button, "复用参数 " + run_id).click().run()

        self.assertEqual(self.widget(app.number_input, FIVE_STAR_PITY_LABEL).value, 7)
        self.assertEqual(self.widget(app.number_input, "UP占比").value, 0.6)
        characters = next(item.value for item in app.dataframe
                          if item.key == "pool_character_editor")
        self.assertEqual(characters.iloc[0]["角色名称"], "历史UP")

    def test_history_date_range_pagination_and_schema_warning(self):
        repository, ids = self.seed_history()
        app = self.load()
        self.widget(app.date_input, "历史开始日期（UTC）").set_value(date(2026, 9, 11))
        self.widget(app.date_input, "历史结束日期（UTC）").set_value(date(2026, 9, 11)).run()
        self.assertEqual(app.dataframe[0].value["运行 ID"].tolist(), [ids[1]])
        self.widget(app.date_input, "历史结束日期（UTC）").set_value(date(2026, 9, 10)).run()
        self.assertTrue(any("开始日期不能晚于结束日期" in item.value for item in app.error))
        payload = repository.get_run(ids[2])
        newest = [repository.save_run(payload, False) for _ in range(19)][::-1]
        app = self.load()
        self.assertEqual(app.dataframe[0].value["运行 ID"].tolist(), newest + [ids[2]])
        self.widget(app.number_input, "历史页码").set_value(2).run()
        self.assertEqual(app.dataframe[0].value["运行 ID"].tolist(), [ids[1], ids[0]])
        self.widget(app.number_input, "历史页码").set_value(3).run()
        self.assertTrue(any("没有历史记录" in item.value for item in app.info))
        with closing(sqlite3.connect(repository.path)) as connection, connection:
            connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute("UPDATE simulation_runs SET schema_version=1 WHERE id=?",
                               (newest[0],))
        self.widget(app.number_input, "历史页码").set_value(1).run()
        self.widget(app.multiselect, "选择历史运行").set_value(newest[:2]).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.metric), 30)
        self.assertTrue(any("统计口径不同" in item.value for item in app.warning))

    def test_history_queries_draw_records_only_for_selected_trace_runs(self):
        _, ids = self.seed_history()
        calls = []
        original_get_run = HistoryRepository.get_run

        def track_get_run(repository, run_id, include_records=False):
            calls.append((run_id, include_records))
            return original_get_run(repository, run_id, include_records)

        app = self.load()
        with patch.object(HistoryRepository, "get_run", new=track_get_run):
            self.widget(app.multiselect, "选择历史运行").set_value([ids[0], ids[1]]).run()

        self.assertEqual(dict(calls), {ids[0]: True, ids[1]: False})
        self.assertEqual(len(calls), 2)

    def test_history_retired_rule_reuse_is_safe_and_missing_selection_clears(self):
        repository, ids = self.seed_history()
        app = self.load()
        self.widget(app.multiselect, "选择历史运行").set_value([ids[0]]).run()
        self.assertEqual(len(app.metric), 15)
        self.widget(app.button, "复用参数 " + ids[0]).click().run()
        self.assertTrue(any("不支持此历史规则" in item.value for item in app.warning))
        self.assertEqual(self.widget(app.number_input, "主池抽数").value, 100)
        self.assertEqual(list(self.root.glob("jobs/*/state.json")), [])
        repository.delete_run(ids[0])
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state["selected_history_ids"], [])
        self.assertEqual(len(app.metric), 0)

    def start_small(self, app, *, pity=29, trace=True):
        self.widget(app.number_input, "主池抽数").set_value(2)
        self.widget(app.number_input, PITY_LABEL).set_value(pity)
        self.widget(app.text_input, "随机种子（留空自动生成）").set_value("42")
        if not self.widget(app.toggle, "Trace").disabled:
            self.widget(app.toggle, "Trace").set_value(trace)
        self.widget(app.button, "开始模拟").click().run()
        self.assertEqual(len(app.exception), 0)
        return app

    def prepare(self, status="queued"):
        self.repository()
        # Startup reconciliation has already happened before this test creates a live job.
        self.load()
        parameters = RunParameters(
            "rule1", 2, 1, 29, 42, True, pool_config=load_pool_config().to_dict()
        )
        state = JobState(str(uuid4()), status, parameters.to_dict(), 1, 2,
                         duration_seconds=2.0)
        job_dir = self.root / "jobs" / state.job_id
        write_json(job_dir / "parameters.json", parameters.to_dict())
        write_json(job_dir / "state.json", state.to_dict())
        app = self.load()
        app.session_state["current_job_id"] = state.job_id
        app.run()
        self.assertEqual(len(app.exception), 0)
        return app, job_dir

    def wait_for_status(self, manager, job_id, status, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = manager.get(job_id)
            if state is not None and state.status == status:
                return state
            time.sleep(0.01)
        self.fail(f"job did not reach {status}: {manager.get(job_id)}")

    def test_process_startup_reconciles_only_its_job_root_once(self):
        parameters = RunParameters("rule1", 10_000, 10_000, 29, 42, False)
        database = self.root / "history_v2.sqlite3"
        manager = JobManager(self.root / "jobs", database)
        unrelated = JobManager(self.root / "unrelated-jobs", self.root / "unrelated.sqlite3")
        self.addCleanup(manager.reconcile_after_restart)
        self.addCleanup(unrelated.reconcile_after_restart)
        stale = manager.start(parameters)
        outside = unrelated.start(parameters)
        self.wait_for_status(manager, stale.job_id, "running")
        self.wait_for_status(unrelated, outside.job_id, "running")

        app = self.load()

        self.assertEqual(manager.get(stale.job_id).status, "failed")
        self.assertEqual(unrelated.get(outside.job_id).status, "running")
        fresh = manager.start(parameters)
        self.wait_for_status(manager, fresh.job_id, "running")
        app.run()
        self.assertEqual(manager.get(fresh.job_id).status, "running")

    def test_completed_shows_metrics_download_and_saves_once_without_session_payload(self):
        app = self.start_small(self.load())
        self.assertEqual(len(app.metric), 15)
        self.assertEqual(len(app.get("download_button")), 2)
        self.assertTrue(any("模拟已完成" in item.value for item in app.success))
        rows = self.repository().list_runs({}, 10, 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["main_draws"], rows[0]["seed"]), (2, 42))
        self.assertEqual(len(self.repository().get_run(rows[0]["id"], True)["records"]), 12)
        self.assertLess(rows[0]["mean_count_error"], 0)
        self.assertLess(rows[0]["mean_count_relative_error"], 0)
        app.run()
        self.assertEqual(len(self.repository().list_runs({}, 10, 0)), 1)
        self.assertEqual(set(app.session_state.filtered_state), {
            "current_job_id", "selected_history_ids", "rule_name", "draws", "trials",
            "initial_pity", "seed_text", "trace", "initial_five_star_pity",
            "pool_up_share", "pool_five_star_probability",
            "pool_five_star_pity_enabled", "pool_five_star_hard_pity",
            "pool_character_rows", "pool_reward_rows", "pool_character_editor",
            "pool_reward_editor", "pool_config_upload",
        })
        self.assertFalse(self.widget(app.button, "开始模拟").disabled)

    def test_trace_cannot_leak_from_previous_single_trial_toggle(self):
        app = self.load()
        self.widget(app.toggle, "Trace").set_value(True).run()
        self.widget(app.number_input, "实验轮数").set_value(2).run()
        self.start_small(app)
        rows = self.repository().list_runs({}, 10, 0)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["trace_enabled"])
        self.assertEqual(self.repository().get_run(rows[0]["id"], True)["records"], [])

    def test_running_shows_progress_elapsed_and_disables_start(self):
        app, job_dir = self.prepare("running")
        self.assertTrue(self.widget(app.button, "开始模拟").disabled)
        self.assertEqual(app.get("progress")[0].proto.value, 50)
        self.assertTrue(any("2.0" in item.value for item in app.caption))
        self.assertFalse(self.widget(app.button, "停止模拟").disabled)
        self.assertEqual(len(app.metric), 0)

    def test_new_session_tracks_and_can_stop_instance_active_job(self):
        for status in ("queued", "running"):
            with self.subTest(status=status):
                _, job_dir = self.prepare(status)
                app = self.load()
                self.assertTrue(self.widget(app.button, "开始模拟").disabled)
                self.assertEqual(app.session_state["current_job_id"], job_dir.name)
                self.assertEqual(app.get("progress")[0].proto.value, 50)
                self.widget(app.button, "停止模拟").click().run()
                self.assertEqual(len(app.exception), 0)
                self.assertTrue((job_dir / "cancel.request").exists())
                manager = JobManager(job_dir.parent, self.root / "history_v2.sqlite3")
                self.assertEqual(manager.get(job_dir.name).status, status)
                manager.reconcile_after_restart()

    def test_session_with_old_result_follows_another_sessions_active_job(self):
        app = self.start_small(self.load())
        previous_id = app.session_state["current_job_id"]
        _, job_dir = self.prepare("running")
        app.run()
        self.assertTrue(self.widget(app.button, "开始模拟").disabled)
        self.assertEqual(app.session_state["current_job_id"], job_dir.name)
        self.assertNotEqual(previous_id, job_dir.name)
        self.assertEqual(len(app.metric), 0)
        self.assertIn("停止模拟", [button.label for button in app.button])

    def test_sync_ui_honors_shared_start_validation_before_writing_job(self):
        original_start = JobManager.start

        def reject_at_admission(manager, parameters, **kwargs):
            return original_start(manager, replace(parameters, draws=0), **kwargs)

        app = self.load()
        with (patch.object(JobManager, "start", new=reject_at_admission),
              self.assertLogs(level="ERROR")):
            self.start_small(app)
        self.assertEqual([item.value for item in app.error], ["模拟任务启动失败"])
        self.assertEqual(list(self.root.glob("jobs/*/state.json")), [])
        self.assertEqual(len(app.metric), 0)

    def test_stop_only_requests_cancel_then_terminal_has_no_history_or_result(self):
        app, job_dir = self.prepare()
        self.assertIn("停止模拟", [button.label for button in app.button])
        self.widget(app.button, "停止模拟").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue((job_dir / "cancel.request").exists())
        manager = JobManager(job_dir.parent, self.root / "history_v2.sqlite3")
        self.assertEqual(manager.get(job_dir.name).status, "queued")
        self.assertEqual(self.repository().list_runs({}, 10, 0), [])
        run(job_dir, self.root / "history_v2.sqlite3")
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("模拟已取消" in item.value for item in app.info))
        self.assertEqual(len(app.metric), 0)
        self.assertEqual(len(app.get("download_button")), 1)
        self.assertEqual(self.repository().list_runs({}, 10, 0), [])
        self.assertIsNone(manager.get_result(job_dir.name))
        self.assertFalse(self.widget(app.button, "开始模拟").disabled)

    def test_initial_pity_is_rejected_before_job_start_and_its_help_explains_both_meanings(self):
        app = self.load()
        input_field = self.widget(app.number_input, PITY_LABEL)
        self.assertEqual(
            input_field.help,
            "该值同时初始化主池保底位置与累计主池抽数；累计抽数决定首次30抽赠送是已领取还是会在本次模拟中触发。",
        )
        input_field.set_value(80)
        self.widget(app.button, "开始模拟").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual([item.value for item in app.error], ["初始保底必须在 0 到 79 之间"])
        self.assertEqual(self.widget(app.number_input, PITY_LABEL).value, 80)
        self.assertEqual(list(self.root.glob("jobs/*/state.json")), [])
        self.assertEqual(self.repository().list_runs({}, 10, 0), [])

    def test_failed_shows_only_safe_summary_without_history_or_result(self):
        app, _ = self.prepare("failed")
        self.assertEqual([item.value for item in app.error], ["模拟任务失败"])
        self.assertEqual(len(app.metric), 0)
        self.assertEqual(len(app.get("download_button")), 1)
        self.assertEqual(self.repository().list_runs({}, 10, 0), [])

    def test_repository_failure_keeps_result_download_and_safe_warning(self):
        self.repository()
        with closing(sqlite3.connect(self.root / "history_v2.sqlite3")) as connection:
            connection.executescript("""
                CREATE TRIGGER fail_save BEFORE INSERT ON simulation_runs
                BEGIN SELECT RAISE(ABORT, 'private database failure'); END;
            """)
        with self.assertLogs("dashboard.worker", level="ERROR"):
            app = self.start_small(self.load())
        self.assertEqual(len(app.metric), 15)
        self.assertEqual(len(app.get("download_button")), 2)
        self.assertEqual([item.value for item in app.warning], ["历史保存失败"])
        self.assertEqual(self.repository().list_runs({}, 10, 0), [])

    def test_production_rejects_sync_mode_before_business_or_database(self):
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "production",
                                    "APP_AUTH_MODE": "oidc",
                                    "ALLOWED_EMAILS": "allowed@example.com"}):
            app = self.load()
        self.assertEqual([item.value for item in app.error],
                         ["生产环境禁止 DASHBOARD_SYNC_JOBS=1"])
        self.assertEqual(len(app.number_input), 0)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unauthenticated_never_renders_business_or_touches_database(self):
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "production",
                                    "APP_AUTH_MODE": "oidc", "DASHBOARD_SYNC_JOBS": "0",
                                    "ALLOWED_EMAILS": "allowed@example.com"}), \
             patch.object(st, "secrets", AttrDict({"auth": {
                 "redirect_uri": "https://dashboard.example.invalid/oauth2callback",
                 "cookie_secret": "x" * 32,
                 "client_id": "test-client-id",
                 "client_secret": "test-client-secret",
                 "server_metadata_url": "https://identity.example.invalid/metadata",
             }})):
            app = self.load()
        self.assertEqual([button.label for button in app.button], ["登录"])
        self.assertEqual(len(app.title), 0)
        self.assertEqual(len(app.number_input), 0)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_script_entrypoint_resolves_packages_without_cwd_on_import_path(self):
        check = subprocess.run(
            [sys.executable, "-I", "-c", """
import sys
import streamlit as st
from streamlit.testing.v1 import AppTest
st.config.set_option('server.address', '127.0.0.1')
app = AppTest.from_file(sys.argv[1]).run()
assert not app.exception, [error.message for error in app.exception]
assert app.title[0].value == '抽奖概率实验室'
""", str(APP)], cwd=self.root, text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_fragment_terminal_transition_refreshes_sidebar_and_result(self):
        app, job_dir = self.prepare()
        original_get = JobManager.get
        reads = 0

        def complete_on_poll(manager, job_id):
            nonlocal reads
            if job_id == job_dir.name:
                reads += 1
                if reads == 2:
                    run(job_dir, self.root / "history_v2.sqlite3")
            return original_get(manager, job_id)

        with patch.object(JobManager, "get", new=complete_on_poll):
            app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.metric), 15)
        self.assertFalse(self.widget(app.button, "开始模拟").disabled)
        self.assertEqual(len(app.get("progress")), 0)
        self.assertEqual(len(self.repository().list_runs({}, 10, 0)), 1)

    def test_invalid_seed_is_safe_and_preserved_without_a_job(self):
        app = self.load()
        self.widget(app.text_input, "随机种子（留空自动生成）").set_value("private-not-an-int")
        self.widget(app.button, "开始模拟").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual([item.value for item in app.error], ["随机种子必须为整数"])
        self.assertEqual(self.widget(app.text_input, "随机种子（留空自动生成）").value,
                         "private-not-an-int")
        self.assertEqual(list(self.root.glob("jobs/*/state.json")), [])


if __name__ == "__main__":
    unittest.main()
