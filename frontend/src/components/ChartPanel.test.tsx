import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { RunResult } from "../api/types";
import { ChartPanel } from "./ChartPanel";

const { apiRequest } = vi.hoisted(() => ({ apiRequest: vi.fn() }));
vi.mock("../api/client", () => ({ apiRequest, errorMessage: (error: Error) => error.message }));
vi.mock("vega-embed", () => ({ default: () => Promise.resolve({ finalize: () => undefined }) }));

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
