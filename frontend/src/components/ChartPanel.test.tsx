import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { RunResult } from "../api/types";
import { ChartPanel } from "./ChartPanel";

const { apiRequest } = vi.hoisted(() => ({ apiRequest: vi.fn() }));
vi.mock("../api/client", () => ({ apiRequest, errorMessage: (error: Error) => error.message }));
vi.mock("vega-embed", () => ({ default: () => {
  const view = { width: () => view, height: () => view, resize: () => view, runAsync: async () => view };
  return Promise.resolve({ finalize: () => undefined, view });
} }));
vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });

const r4 = "00000000-0000-4000-8000-000000000004";
const r5 = "00000000-0000-4000-8000-000000000005";
const r6 = "00000000-0000-4000-8000-000000000006";
const result = {
  parameters: { draws: "10", trials: "3" },
  rule_snapshot: { rarities: [{ id: r4, name: "R", rank: 0 }, { id: r5, name: "SR", rank: 1 }, { id: r6, name: "SSR", rank: 2 }], bonus: { draws: 2 } },
  trace_enabled: true,
  pool_snapshot: { rarity_labels: { [r4]: "R", [r5]: "SR", [r6]: "SSR" } },
} as unknown as RunResult;

afterEach(() => { cleanup(); apiRequest.mockReset(); });

it("uses renamed rarity labels for single, multiple and empty selections without posting a simulation", async () => {
  apiRequest.mockResolvedValue({ spec: null, rows: [], chart_approximate: false, rarity_labels: {} });
  render(<ChartPanel base="jobs/job-1" result={result} mode="position" />);

  const rarity4 = screen.getByRole("checkbox", { name: "R" });
  const rarity5 = screen.getByRole("checkbox", { name: "SR" });
  const rarity6 = screen.getByRole("checkbox", { name: "SSR" });
  await waitFor(() => expect(latestQuery().rarity_id).toEqual([r4, r5, r6]));

  fireEvent.click(rarity5);
  fireEvent.click(rarity6);
  await waitFor(() => expect(latestQuery().rarity_id).toEqual([r4]));
  fireEvent.click(rarity6);
  await waitFor(() => expect(latestQuery().rarity_id).toEqual([r4, r6]));

  fireEvent.change(screen.getByRole("combobox", { name: "位置来源" }), { target: { value: "bonus" } });
  await waitFor(() => expect(latestQuery()).toMatchObject({ source: "bonus", rarity_id: [r4, r6] }));
  fireEvent.click(rarity4);
  await waitFor(() => expect(latestQuery().rarity_id).toEqual([r6]));
  const callsBeforeEmpty = apiRequest.mock.calls.length;
  fireEvent.click(rarity6);

  expect(await screen.findByRole("status")).toHaveTextContent("请至少选择一种稀有度");
  expect(apiRequest).toHaveBeenCalledTimes(callsBeforeEmpty);
  expect(apiRequest.mock.calls.every(([path, options]) =>
    String(path).includes("/charts/?") && (options?.method ?? "GET") === "GET",
  )).toBe(true);
});

function latestQuery(): { source: string; rarity_id: string[] } {
  const [path] = apiRequest.mock.calls.at(-1) ?? [];
  const params = new URL(String(path), "http://localhost").searchParams;
  return { source: params.get("source") ?? "", rarity_id: params.getAll("rarity_id") };
}

it("shows precise zero values and denominator in a paged table without another request", async () => {
  apiRequest.mockResolvedValue({ spec: { data: { values: [] } }, chart_approximate: false,
    rarity_labels: { [r4]: "R", [r5]: "SR", [r6]: "SSR" }, rows: Array.from({ length: 51 }, (_, index) => ({
      position: String(index + 1), window_position: index, observations: "10", r0_count: "8", r0_rate: .8,
      r1_count: "2", r1_rate: .2, r2_count: "0", r2_rate: 0,
    })) });
  render(<ChartPanel base="runs/run-1" result={result} mode="position" />);
  fireEvent.click(await screen.findByText("查看数值表（51个抽次）"));
  const table = screen.getByRole("table");
  expect(within(table).getAllByRole("row")).toHaveLength(51);
  expect(within(table).getAllByText("0 / 0.00%")).toHaveLength(50);
  expect(within(table).getAllByText("8 / 80.00%")).toHaveLength(50);
  const calls = apiRequest.mock.calls.length;
  fireEvent.click(screen.getByRole("button", { name: "下一页" }));
  expect(within(table).getAllByRole("row")).toHaveLength(2);
  expect(within(table).getByRole("rowheader", { name: "51" })).toBeInTheDocument();
  expect(apiRequest).toHaveBeenCalledTimes(calls);
});

it("shows an empty range instead of a misleading blank chart", async () => {
  apiRequest.mockResolvedValue({ spec: { data: { values: [] } }, rows: [], chart_approximate: false, rarity_labels: {} });
  render(<ChartPanel base="runs/run-1" result={result} mode="position" />);
  expect(await screen.findByRole("status")).toHaveTextContent("所选范围没有逐抽数据");
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

it("supports a newly added rarity by stable ID", async () => {
  const r7 = "00000000-0000-4000-8000-000000000007";
  const extended = { ...result, rule_snapshot: { ...result.rule_snapshot,
    rarities: [...result.rule_snapshot.rarities, { id: r7, name: "UR", rank: 3 }] },
    pool_snapshot: { ...result.pool_snapshot, rarity_labels: { ...result.pool_snapshot.rarity_labels, [r7]: "UR" } },
  } as RunResult;
  apiRequest.mockResolvedValue({ spec: null, rows: [], chart_approximate: false,
    rarity_labels: { ...extended.pool_snapshot.rarity_labels } });
  render(<ChartPanel base="runs/run-1" result={extended} mode="position" />);
  expect(screen.getByRole("checkbox", { name: "UR" })).toBeInTheDocument();
  await waitFor(() => expect(latestQuery().rarity_id).toContain(r7));
});

it("keeps position and observation counts exact above the safe integer limit", async () => {
  apiRequest.mockResolvedValue({ chart_approximate: true, spec: { data: { values: [] } },
    rarity_labels: { [r4]: "R", [r5]: "SR", [r6]: "SSR" }, rows: [{ position: "9007199254740993", window_position: 0,
      observations: "9007199254740994", r0_count: "9007199254740993", r0_rate: 1,
      r1_count: "1", r1_rate: 0, r2_count: "0", r2_rate: 0 }] });
  render(<ChartPanel base="runs/run-1" result={result} mode="position" />);
  expect(await screen.findByText(/计数轴超出浏览器精确数值范围/)).toBeInTheDocument();
  fireEvent.click(screen.getByText("查看数值表（1个抽次）"));
  const table = screen.getByRole("table");
  expect(within(table).getByText("9,007,199,254,740,993")).toBeInTheDocument();
  expect(within(table).getByText("9,007,199,254,740,994")).toBeInTheDocument();
});
