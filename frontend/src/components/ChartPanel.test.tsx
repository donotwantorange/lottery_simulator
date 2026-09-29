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

const result = {
  main_draws: 10,
  bonus_draws: 2,
  trials: 3,
  trace_enabled: true,
  pool_config: {
    rarity_labels: { "4": "R", "5": "SR", "6": "SSR" },
    four_star_characters: [], five_star_characters: [], six_star_characters: [], rewards: [],
  },
} as unknown as RunResult;

afterEach(() => { cleanup(); apiRequest.mockReset(); });

it("uses renamed rarity labels for single, multiple and empty selections without posting a simulation", async () => {
  apiRequest.mockResolvedValue({ spec: null });
  render(<ChartPanel base="jobs/job-1" result={result} mode="position" />);

  const rarity4 = screen.getByRole("checkbox", { name: "R" });
  const rarity5 = screen.getByRole("checkbox", { name: "SR" });
  const rarity6 = screen.getByRole("checkbox", { name: "SSR" });
  await waitFor(() => expect(latestQuery().rarity).toEqual(["4", "5", "6"]));

  fireEvent.click(rarity5);
  fireEvent.click(rarity6);
  await waitFor(() => expect(latestQuery().rarity).toEqual(["4"]));
  fireEvent.click(rarity6);
  await waitFor(() => expect(latestQuery().rarity).toEqual(["4", "6"]));

  fireEvent.change(screen.getByRole("combobox", { name: "位置来源" }), { target: { value: "bonus" } });
  await waitFor(() => expect(latestQuery()).toMatchObject({ source: "bonus", rarity: ["4", "6"] }));
  fireEvent.click(rarity4);
  await waitFor(() => expect(latestQuery().rarity).toEqual(["6"]));
  const callsBeforeEmpty = apiRequest.mock.calls.length;
  fireEvent.click(rarity6);

  expect(await screen.findByRole("status")).toHaveTextContent("请至少选择一种稀有度");
  expect(apiRequest).toHaveBeenCalledTimes(callsBeforeEmpty);
  expect(apiRequest.mock.calls.every(([path, options]) =>
    String(path).includes("/charts/?") && (options?.method ?? "GET") === "GET",
  )).toBe(true);
});

function latestQuery(): { source: string; rarity: string[] } {
  const [path] = apiRequest.mock.calls.at(-1) ?? [];
  const params = new URL(String(path), "http://localhost").searchParams;
  return { source: params.get("source") ?? "", rarity: params.getAll("rarity") };
}

it("shows precise zero values and denominator in a paged table without another request", async () => {
  apiRequest.mockResolvedValue({ spec: { data: { values: [] } }, rows: Array.from({ length: 51 }, (_, index) => ({
    position: index + 1, observations: 10, four_count: 8, four_rate: .8,
    five_count: 2, five_rate: .2, six_count: 0, six_rate: 0,
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
  apiRequest.mockResolvedValue({ spec: { data: { values: [] } }, rows: [] });
  render(<ChartPanel base="runs/run-1" result={result} mode="position" />);
  expect(await screen.findByRole("status")).toHaveTextContent("所选范围没有逐抽数据");
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});
