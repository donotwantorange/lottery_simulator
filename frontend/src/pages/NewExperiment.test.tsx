import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { NewExperiment } from "./NewExperiment";

const { apiRequest, MockApiError, authUser } = vi.hoisted(() => {
  class MockApiError extends Error {
    constructor(readonly status: number, _code: string, message: string) { super(message); }
  }
  return { apiRequest: vi.fn(), MockApiError, authUser: { id: "user-1", username: "alice", role: "user", must_change_password: false } };
});
let submitFailure: unknown;
vi.mock("../api/client", () => ({
  apiRequest,
  ApiError: MockApiError,
  errorMessage: (error: unknown) => error instanceof Error ? error.message : "请求失败",
}));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({
  user: authUser, sessionGeneration: 0,
}) }));

const pool = {
  id: "pool-1", name: "测试池", kind: "private", visibility: "hidden", owner_id: "user-1", owner_name: "alice",
  original_author: "作者", rule_name: "rule1", rarity_labels: { "4": "四星", "5": "五星", "6": "六星" },
  pool_config: { up_share: 0.5, five_star: { base_probability: 0.08, pity_enabled: true, hard_pity: 10 },
    six_star_characters: [], four_star_characters: [], five_star_characters: [], rewards: [] }, revision: 7, updated_at: "2026-09-01T00:00:00Z",
};

describe("NewExperiment", () => {
  afterEach(cleanup);

  beforeEach(() => {
    Object.assign(authUser, { id: "user-1", username: "alice", role: "user", must_change_password: false });
    submitFailure = new TypeError("network lost");
    apiRequest.mockReset();
    apiRequest.mockImplementation((path: string, options?: RequestInit) => {
      if (path.startsWith("pools/?")) return Promise.resolve({ items: [pool], total: 1, page: 1, page_size: 200 });
      if (path.startsWith("experiment-configs/?")) return Promise.resolve({ items: [], total: 0, page: 1, page_size: 200 });
      if (path === "experiment-configs/import/preview/") return Promise.resolve({
        document: { format_version: 1, name: "大整数配置", pool_ref: { id: "pool-1", name: "测试池" },
          parameters: { draws: "10", trials: "2", initial_pity: "0", initial_five_star_pity: "0", seed: "900719925474099312345678901234567890", trace: false } },
        resolution: { status: "matched", candidates: [{ id: "pool-1", name: "测试池", revision: 7, kind: "private", visibility: "hidden", owner_id: "user-1", owner_name: "alice", original_author: "作者" }] },
      });
      if (path.startsWith("jobs/mine/")) return Promise.resolve({ items: [], total: 0, page: 1, page_size: 50 });
      if (path === "jobs/" && options?.method === "POST") return Promise.reject(submitFailure);
      throw new Error(`Unexpected API request: ${path}`);
    });
  });

  it("does not retry an uncertain submit or auto-select among same-parameter tasks after an early empty mine list", async () => {
    let mineQueries = 0;
    const sameParametersJobs = ["job-from-this-tab", "job-from-another-tab"].map((job_id) => ({
      job_id, accepted_at: "2026-09-01T00:00:00Z", status: "running", phase: "simulate", draws: "10", trials: "1",
      trace: false, pool_name_snapshot: "测试池", run_id: null,
    }));
    apiRequest.mockImplementation((path: string, options?: RequestInit) => {
      if (path.startsWith("pools/?")) return Promise.resolve({ items: [pool], total: 1, page: 1, page_size: 200 });
      if (path.startsWith("experiment-configs/?")) return Promise.resolve({ items: [], total: 0, page: 1, page_size: 200 });
      if (path === "jobs/" && options?.method === "POST") return Promise.reject(submitFailure);
      if (path.startsWith("jobs/mine/")) {
        mineQueries += 1;
        return Promise.resolve(mineQueries === 1
          ? { items: [], total: 0, page: 1, page_size: 50 }
          : { items: sameParametersJobs, total: 2, page: 1, page_size: 50 });
      }
      throw new Error(`Unexpected API request: ${path}`);
    });
    render(<MemoryRouter><NewExperiment /></MemoryRouter>);
    await screen.findByRole("option", { name: /测试池/ });
    fireEvent.change(screen.getByLabelText("角色池"), { target: { value: "pool-1" } });
    fireEvent.click(screen.getByRole("button", { name: "开始模拟" }));
    await screen.findByText(/提交结果未确认/);
    await screen.findByText(/本人任务列表为空/);
    fireEvent.click(screen.getByRole("button", { name: "再次查询本人任务" }));
    await waitFor(() => expect(apiRequest.mock.calls.filter(([path, options]) => path === "jobs/" && options?.method === "POST")).toHaveLength(1));
    expect(await screen.findByText("job-from-this-tab")).toBeInTheDocument();
    expect(screen.getByText("job-from-another-tab")).toBeInTheDocument();
    expect(screen.getAllByRole("row").filter((row) => row.getAttribute("aria-selected") === "false")).toHaveLength(2);
    expect(screen.queryByText(/人工核对项/)).not.toBeInTheDocument();
    expect(apiRequest.mock.calls.filter(([path]) => path.startsWith("jobs/mine/")).length).toBe(2);
  });

  it("wraps raw experiment JSON for preview without rounding a large file integer", async () => {
    render(<MemoryRouter><NewExperiment /></MemoryRouter>);
    await screen.findByRole("option", { name: /测试池/ });
    const raw = '{"format_version":1,"name":"大整数配置","pool_ref":{"id":"pool-1","name":"测试池"},"parameters":{"draws":10,"trials":2,"initial_pity":0,"initial_five_star_pity":0,"seed":900719925474099312345678901234567890,"trace":false}}';
    const file = new File([raw], "experiment.json", { type: "application/json" });
    Object.defineProperty(file, "text", { value: async () => raw });
    fireEvent.change(screen.getByLabelText("导入JSON"), { target: { files: [file] } });
    await waitFor(() => {
      const call = apiRequest.mock.calls.find(([path]) => path === "experiment-configs/import/preview/");
      expect(call?.[1]?.body).toBe(`{"document":${raw}}`);
    });
  });

  it("treats a gateway error as uncertain and queries mine without retrying the submit", async () => {
    submitFailure = new ApiError(502, "gateway", "gateway response lost after forwarding");
    render(<MemoryRouter><NewExperiment /></MemoryRouter>);
    await screen.findByRole("option", { name: /测试池/ });
    fireEvent.change(screen.getByLabelText("角色池"), { target: { value: "pool-1" } });
    fireEvent.click(screen.getByRole("button", { name: "开始模拟" }));
    await screen.findByText(/提交结果未确认/);
    await screen.findByText(/本人任务列表为空/);
    expect(apiRequest.mock.calls.filter(([path, options]) => path === "jobs/" && options?.method === "POST")).toHaveLength(1);
    expect(apiRequest.mock.calls.filter(([path]) => path.startsWith("jobs/mine/")).length).toBe(1);
  });

  it("does not offer another user's hidden pool while an admin edits that user's config", async () => {
    Object.assign(authUser, { id: "admin-id", username: "root", role: "admin" });
    const ownedHidden = { ...pool, id: "owned-hidden", name: "alice隐藏池", owner_id: "user-1", visibility: "hidden" };
    const foreignHidden = { ...pool, id: "foreign-hidden", name: "bob隐藏池", owner_id: "user-2", visibility: "hidden" };
    apiRequest.mockImplementation((path: string, options?: RequestInit) => {
      if (path.startsWith("pools/?")) return Promise.resolve({ items: [pool, ownedHidden, foreignHidden], total: 3, page: 1, page_size: 200 });
      if (path.startsWith("experiment-configs/?")) return Promise.resolve({ items: [{
        id: "config-1", owner_id: "user-1", owner_name: "alice", owner_is_admin: false, name: "Alice配置",
        pool_ref: { id: "owned-hidden", name: "alice隐藏池", available: true },
        parameters: { draws: "10", trials: "1", initial_pity: "0", initial_five_star_pity: "0", seed: "1", trace: false },
        revision: 1, created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z",
      }], total: 1, page: 1, page_size: 200 });
      if (path === "jobs/" && options?.method === "POST") return Promise.resolve({ job_id: "job-1" });
      if (path.startsWith("jobs/mine/")) return Promise.resolve({ items: [], total: 0, page: 1, page_size: 50 });
      throw new Error(`Unexpected API request: ${path}`);
    });
    render(<MemoryRouter initialEntries={["/experiments/new/?config=config-1"]}><NewExperiment /></MemoryRouter>);

    await screen.findAllByRole("option", { name: /alice隐藏池/ });
    const configPool = screen.getByLabelText("配置绑定角色池");
    expect(within(configPool).getByRole("option", { name: /测试池/ })).toBeInTheDocument();
    expect(within(configPool).queryByRole("option", { name: /bob隐藏池/ })).not.toBeInTheDocument();

    const simulationPool = screen.getByLabelText("本次模拟角色池");
    expect(simulationPool).toHaveValue("owned-hidden");
    fireEvent.change(simulationPool, { target: { value: "foreign-hidden" } });
    expect(within(configPool).getByRole("option", { name: /alice隐藏池/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "开始模拟" }));
    await waitFor(() => expect(apiRequest.mock.calls.some(([path, options]) => path === "jobs/" && options?.method === "POST")).toBe(true));
    const submitted = apiRequest.mock.calls.find(([path, options]) => path === "jobs/" && options?.method === "POST")![1];
    expect(JSON.parse(submitted.body as string)).toMatchObject({ pool_id: "foreign-hidden", expected_revision: 7 });
    expect(apiRequest.mock.calls.some(([path, options]) => path === "experiment-configs/config-1/" && options?.method === "PATCH")).toBe(false);
  });
});
