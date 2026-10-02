import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { Results, ResultView } from "./Results";
import type { RunResult } from "../api/types";

const { apiRequest, MockApiError } = vi.hoisted(() => {
  class MockApiError extends Error { constructor(readonly status: number) { super("历史任务不存在"); } }
  return { apiRequest: vi.fn(), MockApiError };
});
vi.mock("../api/client", () => ({ apiRequest, ApiError: MockApiError, errorMessage: (error: Error) => error.message }));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ user: { id: "u1" }, sessionGeneration: 0 }) }));
vi.mock("../components/ChartPanel", () => ({ ChartPanel: () => null }));

afterEach(() => { cleanup(); apiRequest.mockReset(); vi.restoreAllMocks(); });

it("stops polling when a job returns 404", async () => {
  const timers = vi.spyOn(globalThis, "setTimeout");
  apiRequest.mockImplementation((path: string) => path.startsWith("jobs/mine/")
    ? Promise.resolve({ items: [], total: 0, page: 1, page_size: 50 })
    : Promise.reject(new MockApiError(404)));
  render(<MemoryRouter initialEntries={["/results/?job=missing"]}><Results /></MemoryRouter>);
  await screen.findByRole("alert");
  expect(apiRequest.mock.calls.filter(([path]) => path === "jobs/missing/")).toHaveLength(1);
  expect(timers.mock.calls.some(([, delay]) => delay === 2_000 || delay === 10_000)).toBe(false);
});

it("sends one explicit cancellation request for an active task", async () => {
  const job = { job_id: "job-1", accepted_at: "2026-09-01T00:00:00Z", status: "running", phase: "simulate",
    draws: "10", trials: "2", trace: false, pool_name_snapshot: "测试池", rule_name_snapshot: "规则", run_id: null, owner_id: "u1",
    completed_units: "1", total_units: "20", phase_completed: "1", phase_total: "20", error: null,
    persistence_error: null, history_saved: false, cancel_requested: false, duration_seconds: null,
    cleanup_error: null,
    parameters: { draws: "10", trials: "2", initial_main_draws: "0", initial_small_pity: {}, initial_big_pity: { target_obtained: false, misses: "0" }, seed: "1", trace: false },
    initial_context: { rule_id: "rule-1", rarity_ids: ["rarity-6"], big_mode: null, big_target_id: null },
    pool_source: { id: "pool-1", revision: 1, name: "测试池", original_author: "作者" },
    rule_source: { id: "rule-1", revision: 1, name: "规则", author: "作者" } };
  apiRequest.mockImplementation((path: string, options?: RequestInit) => {
    if (path.startsWith("jobs/mine/")) return Promise.resolve({ items: [job], total: 1, page: 1, page_size: 50 });
    if (path === "jobs/job-1/cancel/" && options?.method === "POST") return Promise.resolve({ ...job, cancel_requested: true });
    return Promise.resolve(job);
  });
  render(<MemoryRouter initialEntries={["/results/?job=job-1"]}><Results /></MemoryRouter>);

  fireEvent.click(await screen.findByRole("button", { name: "停止任务" }));
  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("jobs/job-1/cancel/", { method: "POST" }));
  expect(screen.getByRole("button", { name: "停止任务" })).toBeDisabled();
  expect(apiRequest.mock.calls.filter(([path, options]) => path === "jobs/job-1/cancel/" && options?.method === "POST")).toHaveLength(1);
});

it("shows the cleanup failure at the reported task phase", async () => {
  const job = { job_id: "job-1", accepted_at: "2026-09-01T00:00:00Z", status: "cancelled", phase: null,
    draws: "10", trials: "2", trace: true, pool_name_snapshot: "测试池", rule_name_snapshot: "规则", run_id: null,
    owner_id: "u1", completed_units: "5", total_units: "20", phase_completed: null, phase_total: null,
    error: null, persistence_error: null, history_saved: false, cancel_requested: true, duration_seconds: 1,
    cleanup_error: "临时任务目录清理失败", parameters: {}, initial_context: {}, pool_source: {}, rule_source: {} };
  apiRequest.mockImplementation((path: string) => path.startsWith("jobs/mine/")
    ? Promise.resolve({ items: [job], total: 1, page: 1, page_size: 50 }) : Promise.resolve(job));
  render(<MemoryRouter initialEntries={["/results/?job=job-1"]}><Results /></MemoryRouter>);
  expect(await screen.findByText(/临时任务文件清理待处理：临时任务目录清理失败/)).toBeInTheDocument();
});

it("refreshes the selected task status in the recent-task list", async () => {
  const job = { job_id: "job-1", accepted_at: "2026-09-01T00:00:00Z", status: "completed", phase: null,
    draws: "1", trials: "1", trace: false, pool_name_snapshot: "测试池", rule_name_snapshot: "规则", run_id: null,
    owner_id: "u1", completed_units: "1", total_units: "1", phase_completed: null, phase_total: null,
    error: null, persistence_error: null, history_saved: false, cancel_requested: false, duration_seconds: 1,
    cleanup_error: null, parameters: { draws: "1", trials: "1", seed: "1", trace: false, initial_main_draws: "0", initial_small_pity: {}, initial_big_pity: { target_obtained: false, misses: "0" } },
    initial_context: { rule_id: "rule-1", rarity_ids: ["rarity-1"], big_mode: null, big_target_id: null },
    pool_source: { id: "pool-1", revision: 1, name: "测试池", original_author: "作者" }, rule_source: { id: "rule-1", revision: 1, name: "规则", author: "作者" } };
  const result = { parameters: job.parameters, counts: { main_draws: "1", bonus_draws: "0", total_draws: "1", grant_triggers: "0", granted_characters: "0", trace_events: "0" },
    seed: "1", duration_seconds: 1, trace_enabled: false, event_count: "0", rule_snapshot: { name: "规则", rarities: [{ id: "rarity-1", name: "R", rank: 0 }] },
    pool_snapshot: { name: "测试池", rarity_labels: { "rarity-1": "R" } }, pool_source: { revision: 1 }, rule_source: { revision: 1 },
    simulation: { acquisitions: { character_count: 0 } }, theoretical: { acquisitions: { character_count: 0 } } } as unknown as RunResult;
  apiRequest.mockImplementation((path: string) => path.startsWith("jobs/mine/")
    ? Promise.resolve({ items: [{ job_id: "job-1", accepted_at: job.accepted_at, status: "queued", phase: "simulate", draws: "1", trials: "1", trace: false,
      pool_name_snapshot: "测试池", rule_name_snapshot: "规则", run_id: null }], total: 1, page: 1, page_size: 50 })
    : path === "jobs/job-1/" ? Promise.resolve(job) : Promise.resolve(result));
  render(<MemoryRouter initialEntries={["/results/?job=job-1"]}><Results /></MemoryRouter>);
  await waitFor(() => expect((screen.getByLabelText("本人最近任务") as HTMLSelectElement).selectedOptions[0]).toHaveTextContent("completed"));
  expect(screen.getByText(/状态：completed/)).toBeInTheDocument();
});

it("keeps a huge seed exact and labels zero-theory relative error unavailable", () => {
  const result = {
    parameters: { draws: "9007199254740993", trials: "1", seed: "12345678901234567890", trace: false,
      initial_main_draws: "0", initial_small_pity: {}, initial_big_pity: { target_obtained: false, misses: "0" } },
    counts: { main_draws: "9007199254740993", bonus_draws: "0", total_draws: "9007199254740993", grant_triggers: "0", granted_characters: "0", trace_events: "0" },
    seed: "12345678901234567890", duration_seconds: 1, trace_enabled: false, event_count: "0",
    rule_snapshot: { name: "动态规则", rarities: [{ id: "rarity-new", name: "新档", rank: 1 }] },
    pool_snapshot: { name: "测试池", rarity_labels: { "rarity-new": "新档" } },
    pool_source: { revision: 3 }, rule_source: { revision: 4 },
    simulation: { acquisitions: { character_count: 0 } }, theoretical: { acquisitions: { character_count: 0 } },
  } as unknown as RunResult;
  render(<ResultView base="jobs/job-1" result={result} />);
  expect(screen.getByText(/随机种子 12345678901234567890/)).toBeInTheDocument();
  expect(screen.getAllByText("9,007,199,254,740,993")[0]).toBeInTheDocument();
  expect(screen.getByText("不可用")).toBeInTheDocument();
  expect(screen.getByText(/未启用过程明细/)).toBeInTheDocument();
});
