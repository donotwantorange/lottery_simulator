import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import type { SimulationPreview as Preview } from "../api/types";
import { SimulationPreview } from "./SimulationPreview";
afterEach(cleanup);

it("keeps each number in its own labelled row and title outside the grid", () => {
  const counts = { main_draws: "100", bonus_draws: "10", total_draws: "110", granted_characters: "0", trace_events: "110" };
  const value = { counts: { per_trial: counts, total: counts }, parameters: { initial_main_draws: "0", draws: "100" },
    rule_source: { name: "mrfz", revision: 1 }, pool_source: { name: "zmd默认角色池", revision: 1 },
    next_triggers: { first_bonus_main_draw: null, periodic_grant_main_draw: null } } as unknown as Preview;
  render(<SimulationPreview value={value} />);
  for (const title of ["每轮", "全部轮次"]) {
    const section = screen.getByRole("region", { name: `${title}计数` });
    expect(within(section).getByRole("heading", { name: title }).parentElement).toBe(section);
    for (const [label, number] of [["主抽", "100"], ["赠送抽", "10"], ["总抽", "110"]]) {
      const row = within(section).getByText(label).parentElement!;
      expect(within(row).getByText(number)).toBeInTheDocument();
    }
  }
});
