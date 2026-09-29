import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { History } from "./History";

const { apiRequest } = vi.hoisted(() => ({ apiRequest: vi.fn() }));
vi.mock("../api/client", () => ({ apiRequest, ApiError: class extends Error {}, errorMessage: (error: Error) => error.message }));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ user: { id: "user-a" }, sessionGeneration: 1 }) }));
vi.mock("./Results", () => ({ ResultView: () => <p>历史结果视图</p> }));

afterEach(() => { cleanup(); apiRequest.mockReset(); });

const savedResult = {
  id: "run-1", rule_name: "rule1", rule_version: "2.0", main_draws: 10, bonus_draws: 0, total_draws: 10,
  trials: 2, seed: "1", initial_pity: 0, initial_five_star_pity: 0, trace_enabled: true, record_count: 20,
  duration_seconds: 1, mean_six_stars: 1, theoretical_expected_count: 1, mean_count_relative_error: 0,
  pool_id_snapshot: "pool-1", pool_revision_snapshot: 7, pool_name_snapshot: "测试池",
  pool_config: { rarity_labels: { "4": "四星", "5": "五星", "6": "六星" }, up_share: 0.5,
    five_star: { base_probability: 0.08, pity_enabled: true, hard_pity: 10 },
    six_star_characters: [], four_star_characters: [], five_star_characters: [], rewards: [] },
};

function historyList() {
  return { items: [{ id: "run-1", created_at: "2026-09-01T00:00:00Z", rule_name: "rule1", pool_name_snapshot: "测试池", draws: "10", trials: "2", record_count: "20" }], total: 1, page: 1, page_size: 20 };
}

it("filters the history list by rule and trace and opens a selected snapshot", async () => {
  apiRequest.mockImplementation((path: string) => {
    if (path.startsWith("runs/?")) return Promise.resolve({
      items: [{ id: "run-1", created_at: "2026-09-01T00:00:00Z", rule_name: "rule1", pool_name_snapshot: "测试池", draws: "10", trials: "2", record_count: "20" }],
      total: 1, page: 1, page_size: 20,
    });
    if (path === "runs/run-1/") return Promise.resolve({
      id: "run-1", rule_name: "rule1", rule_version: "2.0", main_draws: 10, bonus_draws: 0, total_draws: 10,
      trials: 2, seed: "1", initial_pity: 0, initial_five_star_pity: 0, trace_enabled: true, record_count: 20,
      duration_seconds: 1, mean_six_stars: 1, theoretical_expected_count: 1, mean_count_relative_error: 0,
      pool_config: { up_share: 0, five_star: { base_probability: 0, pity_enabled: false, hard_pity: 0 },
        six_star_characters: [], four_star_characters: [], five_star_characters: [], rewards: [] },
    });
    return Promise.resolve({});
  });
  render(<MemoryRouter><History /></MemoryRouter>);

  await screen.findByRole("button", { name: "查看" });
  fireEvent.change(screen.getByRole("textbox", { name: "规则名称" }), { target: { value: "rule1" } });
  fireEvent.change(screen.getByRole("combobox", { name: "Trace" }), { target: { value: "true" } });
  await waitFor(() => expect(apiRequest).toHaveBeenLastCalledWith("runs/?page=1&page_size=20&rule_name=rule1&trace=true", expect.anything(), expect.anything()));

  fireEvent.click(screen.getByRole("button", { name: "查看" }));
  expect(await screen.findByText("历史结果视图")).toBeInTheDocument();
  expect(apiRequest).toHaveBeenCalledWith("runs/run-1/", expect.anything(), expect.anything());
});

it("requires explicit rerun confirmation and rejects a pool revision changed during confirmation", async () => {
  let poolReads = 0;
  apiRequest.mockImplementation((path: string) => {
    if (path.startsWith("runs/?")) return Promise.resolve(historyList());
    if (path === "runs/run-1/") return Promise.resolve(savedResult);
    if (path === "pools/pool-1/") {
      poolReads += 1;
      return Promise.resolve({ id: "pool-1", name: "测试池", revision: poolReads === 1 ? 8 : 9,
        rarity_labels: { "4": "四星", "5": "五星", "6": "六星" } });
    }
    return Promise.resolve({});
  });
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<MemoryRouter initialEntries={["/history/?run=run-1"]}><History /></MemoryRouter>);

  fireEvent.click(await screen.findByRole("button", { name: "按当前角色池重跑" }));
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
  expect(await screen.findByRole("alert")).toHaveTextContent("确认期间角色池修订已变化");
  expect(apiRequest.mock.calls.some(([path, options]) => path === "jobs/" && options?.method === "POST")).toBe(false);
});

it("does not delete a history record before the separate confirmation action", async () => {
  apiRequest.mockImplementation((path: string) => path.startsWith("runs/?") ? Promise.resolve(historyList())
    : path === "runs/run-1/" ? Promise.resolve(savedResult) : Promise.resolve({}));
  render(<MemoryRouter initialEntries={["/history/?run=run-1"]}><History /></MemoryRouter>);

  fireEvent.click(await screen.findByRole("button", { name: "删除历史" }));
  expect(await screen.findByText(/确认删除这条历史记录及其 Trace/)).toBeInTheDocument();
  expect(apiRequest.mock.calls.some(([path, options]) => path === "runs/run-1/" && options?.method === "DELETE")).toBe(false);
});
