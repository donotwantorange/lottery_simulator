import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { Results } from "./Results";

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
    draws: "10", trials: "2", trace: false, pool_name_snapshot: "测试池", run_id: null, owner_id: "u1",
    completed_units: "1", total_units: "20", phase_completed: "1", phase_total: "20", error: null,
    persistence_error: null, history_saved: false, cancel_requested: false, duration_seconds: null,
    parameters: { draws: "10", trials: "2", initial_pity: "0", initial_five_star_pity: "0", seed: "1", trace: false },
    pool_source: { id: "pool-1", revision: 1, name: "测试池", original_author: "作者" } };
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
