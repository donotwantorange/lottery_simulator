import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { RunResult, TraceRecord } from "../api/types";
import { TraceTable } from "./TraceTable";

const { apiRequest } = vi.hoisted(() => ({ apiRequest: vi.fn() }));
vi.mock("../api/client", () => ({ apiRequest, errorMessage: (error: Error) => error.message }));
vi.mock("./DownloadForm", () => ({ DownloadForm: () => <div>Trace下载</div> }));

const result = {
  trials: 1,
  pool_config: {
    rarity_labels: { "4": "R", "5": "SR", "6": "SSR" },
    four_star_characters: [], five_star_characters: [],
    six_star_characters: [{ name: "限定角色", is_up: true, is_limited: true, up_weight: null }],
    rewards: [],
  },
} as unknown as RunResult;

const record = {
  trial_index: 1, draw_index: 1, source: "bonus", source_index: 1, main_draws_completed: 0, bonus_event: null,
  main_state_before: { misses_since_six_star: 0, misses_since_five_or_higher: 0 },
  main_state_after: { misses_since_six_star: 0, misses_since_five_or_higher: 0 },
  draw_result: {
    outcome: { rarity: 6, character_name: "限定角色", is_up: true, is_limited: true, rewards: {}, five_star_pity_triggered: false, six_star_hard_pity_triggered: false },
    probabilities: { four_star: 0.1, five_star: 0.1, six_star: 0.8 },
    state_before: { misses_since_six_star: 0, misses_since_five_or_higher: 0 },
    state_after: { misses_since_six_star: 0, misses_since_five_or_higher: 0 },
  },
} as TraceRecord;

afterEach(() => { cleanup(); apiRequest.mockReset(); });

it("shows renamed rarity labels and sends stable internal rarity filters for bonus-pool trace", async () => {
  apiRequest.mockResolvedValue({ items: [record], total: 1, page: 1, page_size: 100 });
  render(<TraceTable base="runs/run-1" runId="run-1" result={result} />);

  expect(await screen.findByText("SSR")).toBeInTheDocument();
  expect(screen.getAllByText("赠送")).toHaveLength(2);
  fireEvent.change(screen.getByRole("combobox", { name: "稀有度" }), { target: { value: "6" } });
  fireEvent.change(screen.getByRole("combobox", { name: "来源" }), { target: { value: "bonus" } });
  await waitFor(() => expect(apiRequest).toHaveBeenLastCalledWith(
    expect.stringContaining("source=bonus&rarity=6"), expect.anything(), expect.anything(),
  ));
  expect(screen.getByRole("combobox", { name: "稀有度" })).toHaveValue("6");
});
