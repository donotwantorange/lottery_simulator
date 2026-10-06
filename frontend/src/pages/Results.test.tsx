import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { Results, ResultView } from "./Results";
import type { RunResult } from "../api/types";

const { apiRequest, MockApiError } = vi.hoisted(() => {
  class MockApiError extends Error { constructor(readonly status: number, message = "历史任务不存在") { super(message); } }
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

it.each([
  ["HTTP 500", new MockApiError(500, "暂时不可用")],
  ["network failure", new TypeError("网络暂时不可用")],
])("clears only a recovered %s polling error", async (_kind, failure) => {
  const timers = vi.spyOn(globalThis, "setTimeout");
  const running = { job_id: "job-1", status: "running", completed_units: "1", total_units: "2" };
  let polls = 0;
  apiRequest.mockImplementation((path: string) => path.startsWith("jobs/mine/")
    ? Promise.resolve({ items: [], total: 0, page: 1, page_size: 50 })
    : ++polls === 1 ? Promise.reject(failure) : Promise.resolve(running));
  render(<MemoryRouter initialEntries={["/results/?job=job-1"]}><Results /></MemoryRouter>);
  expect(await screen.findByRole("alert")).toHaveTextContent(failure.message);
  const retry = timers.mock.calls.find(([, delay]) => delay === 2_000)?.[0] as (() => void) | undefined;
  expect(retry).toBeDefined();
  await act(async () => { retry!(); await Promise.resolve(); await Promise.resolve(); });
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByText(/状态：running/)).toBeInTheDocument();
});

it("preserves a cancellation POST error when status polling later succeeds", async () => {
  const timers = vi.spyOn(globalThis, "setTimeout");
  const running = { job_id: "job-1", accepted_at: "2026-09-01T00:00:00Z", status: "running", phase: "simulate",
    draws: "1", trials: "1", trace: false, pool_name_snapshot: "池", rule_name_snapshot: "规则", run_id: null,
    owner_id: "u1", completed_units: "1", total_units: "2", error: null, cleanup_error: null, persistence_error: null,
    history_saved: false, cancel_requested: false, duration_seconds: null, parameters: {}, initial_context: {},
    pool_source: {}, rule_source: {} };
  apiRequest.mockImplementation((path: string) => path.startsWith("jobs/mine/")
    ? Promise.resolve({ items: [running], total: 1, page: 1, page_size: 50 })
    : path === "jobs/job-1/cancel/" ? Promise.reject(new MockApiError(500, "停止请求失败")) : Promise.resolve(running));
  render(<MemoryRouter initialEntries={["/results/?job=job-1"]}><Results /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "停止任务" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("停止请求失败");
  const index = timers.mock.calls.findIndex(([, delay]) => delay === 2_000);
  const retry = timers.mock.calls[index][0] as () => void;
  clearTimeout(timers.mock.results[index].value as ReturnType<typeof setTimeout>);
  await act(async () => { retry(); await Promise.resolve(); await Promise.resolve(); });
  expect(screen.getByRole("alert")).toHaveTextContent("停止请求失败");
  expect(apiRequest.mock.calls.filter(([path]) => path === "jobs/job-1/cancel/")).toHaveLength(1);
});

it("keeps the last valid task visible during a 503 and clears the polling error on recovery", async () => {
  const timers = vi.spyOn(globalThis, "setTimeout");
  const state = { job_id: "job-1", status: "running", completed_units: "4", total_units: "10" };
  let polls = 0;
  apiRequest.mockImplementation((path: string) => path.startsWith("jobs/mine/")
    ? Promise.resolve({ items: [], total: 0, page: 1, page_size: 50 })
    : ++polls === 2 ? Promise.reject(new MockApiError(503, "状态暂不可用")) : Promise.resolve(state));
  render(<MemoryRouter initialEntries={["/results/?job=job-1"]}><Results /></MemoryRouter>);
  await screen.findByText("总进度：4 / 10");
  const retryPoll = async () => {
    const index = timers.mock.calls.reduce((last, [, delay], current) => delay === 2_000 ? current : last, -1);
    expect(index).toBeGreaterThanOrEqual(0);
    const callback = timers.mock.calls[index][0] as () => void;
    clearTimeout(timers.mock.results[index].value as ReturnType<typeof setTimeout>);
    await act(async () => { callback(); await Promise.resolve(); await Promise.resolve(); });
  };
  await retryPoll();
  expect(screen.getByRole("alert")).toHaveTextContent("状态暂不可用");
  expect(screen.getByText("总进度：4 / 10")).toBeInTheDocument();
  await retryPoll();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByText("总进度：4 / 10")).toBeInTheDocument();
});

it("ignores an old task response after switching the selected job", async () => {
  let finishOld!: (value: unknown) => void;
  const oldJob = { job_id: "old-job", status: "running", completed_units: "1", total_units: "2" };
  const newJob = { job_id: "new-job", status: "cancelled", completed_units: "2", total_units: "2" };
  apiRequest.mockImplementation((path: string) => path.startsWith("jobs/mine/")
    ? Promise.resolve({ items: [oldJob, newJob].map((job) => ({ ...job, accepted_at: "2026-09-01T00:00:00Z", draws: "1", trials: "1", trace: false, pool_name_snapshot: job.job_id, rule_name_snapshot: "规则", run_id: null })), total: 2, page: 1, page_size: 50 })
    : path === "jobs/old-job/" ? new Promise((resolve) => { finishOld = resolve; }) : Promise.resolve(newJob));
  render(<MemoryRouter initialEntries={["/results/?job=old-job"]}><Results /></MemoryRouter>);
  await screen.findByRole("option", { name: /new-job/ });
  fireEvent.change(screen.getByLabelText("本人最近任务"), { target: { value: "new-job" } });
  expect(await screen.findByText("状态：cancelled")).toBeInTheDocument();
  await act(async () => { finishOld(oldJob); await Promise.resolve(); });
  expect(screen.getByText("状态：cancelled")).toBeInTheDocument();
  expect(screen.queryByText("状态：running")).toBeNull();
});

it("clears the selected task and result when the job selection is emptied", async () => {
  const completed = { job_id: "old-job", status: "completed", completed_units: "1", total_units: "1", phase: null,
    cancel_requested: false, error: null, cleanup_error: null, persistence_error: null, run_id: null,
    accepted_at: "2026-09-01T00:00:00Z", draws: "1", trials: "1", trace: false, pool_name_snapshot: "旧池", rule_name_snapshot: "旧规则" };
  const result = { parameters: { draws: "1", trials: "1" }, counts: { main_draws: "1", bonus_draws: "0", total_draws: "1", grant_triggers: "0", granted_characters: "0" },
    seed: "1", duration_seconds: 0, trace_enabled: false, event_count: "0",
    rule_snapshot: { name: "旧结果规则", rarities: [{ id: "rarity", name: "R", rank: 0 }] },
    pool_snapshot: { name: "旧结果池", rarity_labels: { rarity: "R" } },
    simulation: { acquisitions: { character_count: 0 } }, theoretical: { acquisitions: { character_count: 0 } } } as unknown as RunResult;
  apiRequest.mockImplementation((path: string) => path.startsWith("jobs/mine/")
    ? Promise.resolve({ items: [completed], total: 1, page: 1, page_size: 50 })
    : path === "jobs/old-job/" ? Promise.resolve(completed) : Promise.resolve(result));
  render(<MemoryRouter initialEntries={["/results/?job=old-job"]}><Results /></MemoryRouter>);
  expect(await screen.findByText(/规则：旧结果规则/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("本人最近任务"), { target: { value: "" } });
  expect(await screen.findByText(/请选择本人任务/)).toBeInTheDocument();
  expect(screen.queryByText(/状态：completed/)).toBeNull();
  expect(screen.queryByText(/规则：旧结果规则/)).toBeNull();
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
    : path === "jobs/job-1/" ? Promise.resolve(job) : path === "jobs/job-1/result/" ? Promise.reject(new Error("结果读取失败")) : Promise.resolve(result));
  render(<MemoryRouter initialEntries={["/results/?job=job-1"]}><Results /></MemoryRouter>);
  await waitFor(() => expect((screen.getByLabelText("本人最近任务") as HTMLSelectElement).selectedOptions[0]).toHaveTextContent("completed"));
  expect(screen.getByText(/状态：completed/)).toBeInTheDocument();
  expect(await screen.findByRole("alert")).toHaveTextContent("结果读取失败");
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
