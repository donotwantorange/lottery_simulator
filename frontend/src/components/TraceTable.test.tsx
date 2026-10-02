import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { ProcessEventDrawRecord, ProcessEventGrantRecord, RunResult } from "../api/types";
import { TraceTable } from "./TraceTable";

const { apiRequest } = vi.hoisted(() => ({ apiRequest: vi.fn() }));
vi.mock("../api/client", () => ({ apiRequest, errorMessage: (error: Error) => error.message }));
vi.mock("./DownloadForm", () => ({ DownloadForm: () => <div>JSONL下载</div> }));

const r4 = "00000000-0000-4000-8000-000000000004";
const r6 = "00000000-0000-4000-8000-000000000006";
const characterId = "10000000-0000-4000-8000-000000000006";
const result = {
  trace_enabled: true,
  parameters: { draws: "2", trials: "2", seed: "1", trace: true, initial_main_draws: "0", initial_small_pity: {}, initial_big_pity: { target_obtained: false, misses: "0" } },
  rule_snapshot: { rarities: [{ id: r4, name: "R", rank: 0 }, { id: r6, name: "SSR", rank: 1 }] },
  pool_snapshot: { rarity_labels: { [r4]: "R", [r6]: "SSR" },
    rarity_pools: [{ rarity_id: r4, characters: [] }, { rarity_id: r6, characters: [{ id: characterId, name: "限定角色" }] }], rewards: [] },
} as unknown as RunResult;

const drawEvent: ProcessEventDrawRecord = {
  event_format_version: 3, trial_index: "1", event_index: "1", main_draws_completed: "0",
  mechanism_id: "first_bonus", event_type: "draw", draw_index: "1", source: "bonus", source_index: "1",
  draw_result: {
    outcome: { rarity_id: r6, character_id: characterId, character_name: "限定角色", is_up: true,
      is_limited: true, rewards: {}, pity_status: { soft_active: [], hard_active: [], big_forced: false } },
    probabilities: { [r4]: 0.2, [r6]: 0.8 }, character_probability: 1,
    state_before: { small_pity: {}, big_misses: "0", big_active: false },
    state_after: { small_pity: {}, big_misses: "0", big_active: false },
  },
  main_state_before: { small_pity: {}, big_misses: "0", big_active: false },
  main_state_after: { small_pity: {}, big_misses: "0", big_active: false },
};

const grantEvent: ProcessEventGrantRecord = {
  event_format_version: 3, trial_index: "1", event_index: "2", main_draws_completed: "2",
  mechanism_id: "periodic_grant", event_type: "character_grant", draw_index: null, source: null, source_index: null,
  grant: { character_id: characterId, rarity_id: r6, character_name: "限定角色", is_up: true,
    is_limited: true, quantity: "2", trigger_main_draw: "2" },
};

afterEach(() => { cleanup(); apiRequest.mockReset(); });

it("uses dynamic rarity and character IDs in Trace filters", async () => {
  apiRequest.mockResolvedValue({ items: [drawEvent], total: "1", page: 1, page_size: 100 });
  render(<TraceTable base="runs/run-1" runId="run-1" result={result} />);
  expect((await screen.findAllByText("SSR"))[0]).toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "稀有度" }), { target: { value: r6 } });
  fireEvent.change(screen.getByRole("combobox", { name: "来源" }), { target: { value: "bonus" } });
  fireEvent.change(screen.getByRole("combobox", { name: "角色" }), { target: { value: characterId } });
  await waitFor(() => expect(apiRequest).toHaveBeenLastCalledWith(
    expect.stringContaining(`source=bonus&rarity_id=${r6}&character_id=${characterId}`), expect.anything(), expect.anything(),
  ));
});

it("renders grants without draw-only data and disables source position filters", async () => {
  apiRequest.mockResolvedValue({ items: [grantEvent], total: "1", page: 1, page_size: 100 });
  render(<TraceTable base="runs/run-1" runId="run-1" result={result} />);
  fireEvent.change(screen.getByRole("combobox", { name: "稀有度" }), { target: { value: r6 } });
  fireEvent.change(screen.getByRole("combobox", { name: "来源" }), { target: { value: "bonus" } });
  fireEvent.change(screen.getByRole("textbox", { name: "来源抽次起" }), { target: { value: "5" } });
  fireEvent.change(screen.getByRole("combobox", { name: "事件类型" }), { target: { value: "character_grant" } });
  expect(await screen.findByText("直接赠送角色")).toBeInTheDocument();
  expect(screen.getAllByText("2")[0]).toBeInTheDocument();
  expect(screen.getAllByText("不适用").length).toBeGreaterThan(0);
  expect(screen.getByRole("textbox", { name: "来源抽次起" })).toBeDisabled();
  expect(screen.getByRole("combobox", { name: "来源" })).toBeDisabled();
  await waitFor(() => expect(apiRequest).toHaveBeenLastCalledWith(
    expect.stringContaining(`event_type=character_grant&rarity_id=${r6}`), expect.anything(), expect.anything(),
  ));
  expect(apiRequest.mock.calls.at(-1)?.[0]).not.toContain("source=bonus");
  expect(apiRequest.mock.calls.at(-1)?.[0]).not.toContain("source_from=5");
});
