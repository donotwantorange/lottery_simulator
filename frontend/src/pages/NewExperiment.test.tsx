import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import defaultPool from "../../../configs/pools/default.json";
import defaultRule from "../../../configs/rules/zmd.json";
import { makePoolDocument } from "../test-fixtures";
import { NewExperiment } from "./NewExperiment";

const { apiRequest, authUser } = vi.hoisted(() => ({
  apiRequest: vi.fn(), authUser: { id: "user-1", username: "alice", role: "user", must_change_password: false },
}));
vi.mock("../api/client", () => ({ apiRequest, ApiError: class extends Error { status = 400; }, errorMessage: (error: unknown) => error instanceof Error ? error.message : "请求失败" }));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ user: authUser, sessionGeneration: 0 }) }));

const pool = {
  id: defaultPool.id, name: "默认角色池", kind: "public", visibility: "public", owner_id: null, owner_name: null,
  original_author: "项目默认配置", rule_ref: { id: defaultRule.id, name: defaultRule.name, revision: 1 },
  document: makePoolDocument(), revision: 4, updated_at: "2026-09-30T00:00:00Z",
};
const counts = { main_draws: "100", bonus_draws: "0", total_draws: "100", grant_triggers: "0", granted_characters: "0", trace_events: "0" };
const preview = { parameters: {}, current_context: { rule_id: defaultRule.id, rarity_ids: defaultRule.rarities.map((item) => item.id), big_mode: "disable_after_obtain", big_target_id: "1635b5c7-f5b2-46e6-b9bf-fa40b352376a" },
  counts: { per_trial: counts, total: counts }, next_triggers: { first_bonus_main_draw: null, periodic_grant_main_draw: "240" },
  pool_source: { id: pool.id, name: pool.name, revision: 4 }, rule_source: { id: defaultRule.id, name: "zmd", revision: 1 } };

describe("NewExperiment", () => {
  afterEach(cleanup);
  beforeEach(() => {
    apiRequest.mockReset();
    apiRequest.mockImplementation((path: string) => {
      if (path.startsWith("pools/?")) return Promise.resolve({ items: [pool], total: 1, page: 1, page_size: 200 });
      if (path.startsWith("experiment-configs/?")) return Promise.resolve({ items: [], total: 0, page: 1, page_size: 200 });
      if (path === `rules/${defaultRule.id}/`) return Promise.resolve({ ...defaultRule, kind: "public", visibility: "public", owner_id: null, owner_name: null, revision: 1, reference_count: 1, structure_locked: true, document: defaultRule });
      if (path === "jobs/preview/") return Promise.resolve(preview);
      if (path === "jobs/") return Promise.resolve({ job_id: "job-1" });
      if (path === "experiment-configs/" ) return Promise.resolve({ id: "saved-1", owner_id: "user-1", owner_name: "alice", owner_is_admin: false, name: "已保存", pool_ref: { id: pool.id, name: pool.name, available: true }, parameters: { draws: "100", trials: "1000", seed: null, trace: false, initial_main_draws: "0", initial_small_pity: {}, initial_big_pity: { target_obtained: false, misses: "0" } }, initial_context: null, current_context: null, validation_errors: [], needs_confirmation: false, revision: 1, created_at: "", updated_at: "" });
      if (path === "experiment-configs/import/preview/") return Promise.resolve({ document: { format_version: 2, name: "导入", pool_ref: { id: pool.id, name: pool.name }, parameters: { draws: "100", trials: "1000", seed: null, trace: false, initial_main_draws: "0", initial_small_pity: {}, initial_big_pity: { target_obtained: false, misses: "0" } }, initial_context: null }, resolution: { status: "matched", candidates: [{ id: pool.id, name: pool.name, revision: 4, rule: { revision: 1 } }] } });
      throw new Error(`Unexpected API request: ${path}`);
    });
  });

  it("previews before accepting and then submits exactly once", async () => {
    render(<MemoryRouter><NewExperiment /></MemoryRouter>);
    await screen.findByRole("option", { name: "默认角色池" });
    fireEvent.change(screen.getByLabelText("角色池"), { target: { value: pool.id } });
    await waitFor(() => expect(apiRequest.mock.calls.some(([path]) => path === `rules/${defaultRule.id}/`)).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "开始模拟" }));
    await screen.findByLabelText("模拟预览");
    expect(apiRequest.mock.calls.filter(([path]) => path === "jobs/")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "开始模拟" }));
    await waitFor(() => expect(apiRequest.mock.calls.filter(([path]) => path === "jobs/")).toHaveLength(1));
  });

  it("locks parameters while preview is pending so the preview snapshot cannot race input changes", async () => {
    let resolvePreview: (value: typeof preview) => void = () => undefined;
    apiRequest.mockImplementation((path: string) => {
      if (path.startsWith("pools/?")) return Promise.resolve({ items: [pool], total: 1, page: 1, page_size: 200 });
      if (path.startsWith("experiment-configs/?")) return Promise.resolve({ items: [], total: 0, page: 1, page_size: 200 });
      if (path === `rules/${defaultRule.id}/`) return Promise.resolve({ ...defaultRule, revision: 1, document: defaultRule });
      if (path === "jobs/preview/") return new Promise((resolve) => { resolvePreview = resolve; });
      throw new Error(`Unexpected API request: ${path}`);
    });
    render(<MemoryRouter><NewExperiment /></MemoryRouter>);
    await screen.findByRole("option", { name: "默认角色池" });
    fireEvent.change(screen.getByLabelText("角色池"), { target: { value: pool.id } });
    await waitFor(() => expect(apiRequest.mock.calls.some(([path]) => path === `rules/${defaultRule.id}/`)).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "开始模拟" }));
    await waitFor(() => expect(apiRequest.mock.calls.some(([path]) => path === "jobs/preview/")).toBe(true));
    expect(screen.getByLabelText("每轮主池抽数")).toBeDisabled();
    expect(screen.getByRole("button", { name: "正在处理…" })).toBeDisabled();
    resolvePreview(preview);
    await screen.findByLabelText("模拟预览");
    expect(apiRequest.mock.calls.some(([path]) => path === "jobs/")).toBe(false);
  });

  it("requires explicit context confirmation when an obtained UP target changes", async () => {
    const changedPool = structuredClone(pool);
    const poolDocument = changedPool.document as ReturnType<typeof makePoolDocument>;
    const highest = poolDocument.rarity_pools.find((item) => item.rarity_id === defaultRule.rarities[2].id)!;
    highest.characters[0].is_up = false;
    highest.characters[1].is_up = true;
    const oldContext = { rule_id: defaultRule.id, rarity_ids: defaultRule.rarities.map((item) => item.id), big_mode: "disable_after_obtain", big_target_id: highest.characters[0].id };
    apiRequest.mockImplementation((path: string) => {
      if (path.startsWith("pools/?")) return Promise.resolve({ items: [changedPool], total: 1, page: 1, page_size: 200 });
      if (path.startsWith("experiment-configs/?")) return Promise.resolve({ items: [{ id: "config-1", owner_id: "user-1", owner_name: "alice", owner_is_admin: false,
        name: "有已获得目标", pool_ref: { id: changedPool.id, name: changedPool.name, available: true },
        parameters: { draws: "10", trials: "1", seed: "17", trace: false, initial_main_draws: "20", initial_small_pity: {}, initial_big_pity: { target_obtained: true, misses: "0" } },
        initial_context: oldContext, current_context: oldContext, validation_errors: [], needs_confirmation: false, revision: 1, created_at: "", updated_at: "" }], total: 1, page: 1, page_size: 200 });
      if (path === `rules/${defaultRule.id}/`) return Promise.resolve({ ...defaultRule, kind: "public", visibility: "public", revision: 1, document: defaultRule });
      throw new Error(`Unexpected API request: ${path}`);
    });
    render(<MemoryRouter initialEntries={["/experiments/new/?config=config-1"]}><NewExperiment /></MemoryRouter>);
    await screen.findByText(/目标从“UP-A”变为“限定-B”/);
    fireEvent.click(screen.getByRole("button", { name: "开始模拟" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/目标已变化/);
    expect(apiRequest.mock.calls.some(([path]) => path === "jobs/preview/")).toBe(false);
    expect(apiRequest.mock.calls.some(([path]) => path === "jobs/")).toBe(false);
  });

  it("keeps large seed text in raw imported JSON and saving a config never starts a job", async () => {
    render(<MemoryRouter><NewExperiment /></MemoryRouter>);
    await screen.findByRole("option", { name: "默认角色池" });
    fireEvent.change(screen.getByLabelText("角色池"), { target: { value: pool.id } });
    await waitFor(() => expect(apiRequest.mock.calls.some(([path]) => path === `rules/${defaultRule.id}/`)).toBe(true));
    await waitFor(() => expect(screen.getByRole("button", { name: "保存配置" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "保存配置" }));
    await waitFor(() => expect(apiRequest.mock.calls.some(([path, options]) => path === "experiment-configs/" && options?.method === "POST")).toBe(true));
    expect(apiRequest.mock.calls.some(([path]) => path === "jobs/")).toBe(false);

    const raw = `{"format_version":2,"name":"大种子","pool_ref":{"id":"${pool.id}","name":"默认角色池"},"parameters":{"draws":1,"trials":1,"seed":9007199254740993123456789,"trace":false,"initial_main_draws":0,"initial_small_pity":{},"initial_big_pity":{"target_obtained":false,"misses":0}},"initial_context":null}`;
    const file = new File([raw], "experiment.json", { type: "application/json" });
    Object.defineProperty(file, "text", { value: async () => raw });
    fireEvent.change(screen.getByLabelText("导入JSON"), { target: { files: [file] } });
    await waitFor(() => expect(apiRequest.mock.calls.some(([path]) => path === "experiment-configs/import/preview/")).toBe(true));
    const call = apiRequest.mock.calls.find(([path]) => path === "experiment-configs/import/preview/");
    expect(call?.[1]?.body).toBe(`{"document":${raw}}`);
  });

  it("does not retry an uncertain job POST until the user checks and explicitly starts a new task", async () => {
    let mineQueries = 0;
    let jobPosts = 0;
    apiRequest.mockImplementation((path: string) => {
      if (path.startsWith("pools/?")) return Promise.resolve({ items: [pool], total: 1, page: 1, page_size: 200 });
      if (path.startsWith("experiment-configs/?")) return Promise.resolve({ items: [], total: 0, page: 1, page_size: 200 });
      if (path === `rules/${defaultRule.id}/`) return Promise.resolve({ ...defaultRule, revision: 1, document: defaultRule });
      if (path === "jobs/preview/") return Promise.resolve(preview);
      if (path === "jobs/") { jobPosts++; return Promise.reject(new Error("gateway response lost")); }
      if (path.startsWith("jobs/mine/")) { mineQueries++; return Promise.resolve({ items: [], total: 0, page: 1, page_size: 50 }); }
      throw new Error(`Unexpected API request: ${path}`);
    });
    render(<MemoryRouter><NewExperiment /></MemoryRouter>);
    await screen.findByRole("option", { name: "默认角色池" });
    fireEvent.change(screen.getByLabelText("角色池"), { target: { value: pool.id } });
    await waitFor(() => expect(apiRequest.mock.calls.some(([path]) => path === `rules/${defaultRule.id}/`)).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "开始模拟" }));
    await screen.findByLabelText("模拟预览");
    fireEvent.click(screen.getByRole("button", { name: "开始模拟" }));
    await screen.findByRole("heading", { name: "提交结果未确认" });
    expect(jobPosts).toBe(1);
    expect(mineQueries).toBe(1);
    expect(screen.getByRole("button", { name: "开始模拟" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "已核对，开始新任务" }));
    expect(jobPosts).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "开始模拟" }));
    await screen.findByLabelText("模拟预览");
    expect(jobPosts).toBe(1);
  });
});
