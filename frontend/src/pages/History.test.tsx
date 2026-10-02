import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { History } from "./History";

const { apiRequest } = vi.hoisted(() => ({ apiRequest: vi.fn() }));
vi.mock("../api/client", () => ({ apiRequest, ApiError: class extends Error {}, errorMessage: (error: Error) => error.message }));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ user: { id: "user-a" }, sessionGeneration: 1 }) }));
vi.mock("./Results", () => ({ ResultView: () => <p>历史结果视图</p> }));

afterEach(() => { cleanup(); apiRequest.mockReset(); vi.restoreAllMocks(); });

const context = { rule_id: "rule-1", rarity_ids: ["rarity-4", "rarity-6"], big_mode: "disable_after_obtain", big_target_id: "char-1" };
const parameters = { draws: "10", trials: "2", seed: "1", trace: true, initial_main_draws: "0",
  initial_small_pity: {}, initial_big_pity: { target_obtained: false, misses: "0" } };
const savedResult = {
  result_format_version: 4, event_format_version: 3, rule_version: "3.0", sampling_version: 2,
  rng_algorithm: "python.random.Random", python_implementation: "CPython", python_version: "3.13.0",
  duration_seconds: 1, seed: "1", parameters, counts: { main_draws: "20", bonus_draws: "0", total_draws: "20", grant_triggers: "0", granted_characters: "0", trace_events: "20" },
  trace_enabled: true, event_count: "20",
  rule_snapshot: { format_version: 1, id: "rule-1", name: "规则A", original_author: "作者", algorithm: "dynamic_probability",
    rarities: [{ id: "rarity-4", name: "R", rank: 0, base_probability: .9, soft_enabled: false, soft_start: 1, soft_step: 0, hard_enabled: false, hard_pity: 1 },
      { id: "rarity-6", name: "SSR", rank: 1, base_probability: .1, soft_enabled: false, soft_start: 1, soft_step: 0, hard_enabled: true, hard_pity: 10 }],
    big_pity: { enabled: true, hard_pity: 80, target: "first_up", after_obtain: "disable_after_obtain" }, bonus: { enabled: false, at_main_draw: 30, draws: 10, rarities: [] }, grant: { enabled: false, period: 100, quantity: 1, target: "first_up" } },
  pool_snapshot: { format_version: 3, id: "pool-1", name: "测试池", original_author: "作者", rule_ref: { id: "rule-1", name: "规则A" },
    rarity_pools: [{ rarity_id: "rarity-4", characters: [], up_enabled: false, up_share: 0 }, { rarity_id: "rarity-6", characters: [], up_enabled: false, up_share: 0 }],
    rarity_labels: { "rarity-4": "R", "rarity-6": "SSR" }, rewards: [], mechanism_targets: {} },
  initial_context: context, targets: { big_pity: null, periodic_grant: null },
  simulation: { draws: { main: {}, bonus: {}, total: {} }, grants: {}, acquisitions: {} },
  theoretical: { draws: { main: {}, bonus: {}, total: {} }, grants: {}, acquisitions: {} },
  id: "run-1", owner_id: "user-a", created_at: "2026-09-01T00:00:00Z",
  pool_id_snapshot: "pool-1", pool_revision_snapshot: 7, pool_name_snapshot: "测试池", pool_original_author_snapshot: "作者",
  rule_id_snapshot: "rule-1", rule_revision_snapshot: 2, rule_name_snapshot: "规则A", rule_original_author_snapshot: "作者",
};
const list = { items: [{ id: "run-1", owner_id: "user-a", created_at: "2026-09-01T00:00:00Z", rule_name: "规则A", pool_name_snapshot: "测试池", original_author_snapshot: "作者", rule_id_snapshot: "rule-1", rule_revision_snapshot: 2, pool_id_snapshot: "pool-1", pool_revision_snapshot: 7, draws: "10", trials: "2", seed: "1", trace: true, event_count: "20" }], total: 1, page: 1, page_size: 20 };
const pool = (revision: number) => ({ id: "pool-1", name: "测试池", revision, document: savedResult.pool_snapshot,
  rule_ref: { id: "rule-1", name: "规则A", revision: 3 } });
const rule = { id: "rule-1", name: "规则A", original_author: "作者", algorithm: "dynamic_probability", kind: "public", visibility: "public", owner_id: null, owner_name: null, revision: 3, reference_count: 1, structure_locked: true, document: savedResult.rule_snapshot };
const preview = { parameters, current_context: context, counts: { per_trial: {}, total: {} }, next_triggers: { first_bonus_main_draw: null, periodic_grant_main_draw: null }, pool_source: { id: "pool-1", name: "测试池", revision: 8 }, rule_source: { id: "rule-1", name: "规则A", revision: 3 } };

it("filters history and opens the saved dynamic snapshots", async () => {
  apiRequest.mockImplementation((path: string) => path.startsWith("runs/?") ? Promise.resolve(list)
    : path === "runs/run-1/" ? Promise.resolve(savedResult) : Promise.resolve({}));
  render(<MemoryRouter><History /></MemoryRouter>);
  await screen.findByRole("button", { name: "查看" });
  fireEvent.change(screen.getByRole("textbox", { name: "规则名称" }), { target: { value: "规则A" } });
  fireEvent.change(screen.getByRole("combobox", { name: "Trace" }), { target: { value: "true" } });
  await waitFor(() => expect(apiRequest).toHaveBeenLastCalledWith("runs/?page=1&page_size=20&rule_name=%E8%A7%84%E5%88%99A&trace=true", expect.anything(), expect.anything()));
  fireEvent.click(screen.getByRole("button", { name: "查看" }));
  expect(await screen.findByText("历史快照")).toBeInTheDocument();
  expect(screen.getByText(/规则：规则A · 修订 2/)).toBeInTheDocument();
  expect(screen.getByText("历史结果视图")).toBeInTheDocument();
});

it("compares both revisions and initial context before submitting a rerun", async () => {
  let poolReads = 0;
  apiRequest.mockImplementation((path: string) => {
    if (path.startsWith("runs/?")) return Promise.resolve(list);
    if (path === "runs/run-1/") return Promise.resolve(savedResult);
    if (path === "pools/pool-1/") { poolReads += 1; return Promise.resolve(pool(poolReads === 1 ? 8 : 9)); }
    if (path === "rules/rule-1/") return Promise.resolve(rule);
    if (path === "jobs/preview/") return Promise.resolve(preview);
    return Promise.resolve({});
  });
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<MemoryRouter initialEntries={["/history/?run=run-1"]}><History /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "按当前角色池重跑" }));
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
  expect(await screen.findByRole("alert")).toHaveTextContent("确认期间角色池或规则已变化");
  expect(apiRequest.mock.calls.some(([path, options]) => path === "jobs/" && options?.method === "POST")).toBe(false);
});

it("requires explicit reset confirmation when the historical target context changed", async () => {
  const changed = { ...savedResult, parameters: { ...parameters, initial_main_draws: "5" } };
  const currentContext = { ...context, big_target_id: "char-new" };
  const currentPreview = { ...preview, current_context: currentContext };
  const bodies: Array<Record<string, unknown>> = [];
  apiRequest.mockImplementation((path: string, options?: RequestInit) => {
    if (path.startsWith("runs/?")) return Promise.resolve(list);
    if (path === "runs/run-1/") return Promise.resolve(changed);
    if (path === "pools/pool-1/") return Promise.resolve(pool(8));
    if (path === "rules/rule-1/") return Promise.resolve(rule);
    if (path === "jobs/preview/") { bodies.push(JSON.parse(String(options?.body))); return Promise.resolve(currentPreview); }
    if (path === "jobs/" && options?.method === "POST") { bodies.push(JSON.parse(String(options.body))); return Promise.resolve({ job_id: "job-new" }); }
    return Promise.resolve({});
  });
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<MemoryRouter initialEntries={["/history/?run=run-1"]}><History /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "按当前角色池重跑" }));
  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("jobs/", expect.objectContaining({ method: "POST", body: expect.any(String) })));
  expect(confirm).toHaveBeenCalledTimes(2);
  expect(confirm.mock.calls[0][0]).toContain("重置为零");
  expect((bodies[1].parameters as typeof parameters).initial_main_draws).toBe("0");
  expect((bodies[2].parameters as typeof parameters).initial_main_draws).toBe("0");
  expect(bodies[2].initial_context).toEqual(currentContext);
  expect(changed.parameters.initial_main_draws).toBe("5");
});

it("does not delete history before separate confirmation", async () => {
  apiRequest.mockImplementation((path: string) => path.startsWith("runs/?") ? Promise.resolve(list)
    : path === "runs/run-1/" ? Promise.resolve(savedResult) : Promise.resolve({}));
  render(<MemoryRouter initialEntries={["/history/?run=run-1"]}><History /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "删除历史" }));
  expect(await screen.findByText(/确认删除这条历史记录及其 Trace/)).toBeInTheDocument();
  expect(apiRequest.mock.calls.some(([path, options]) => path === "runs/run-1/" && options?.method === "DELETE")).toBe(false);
});
