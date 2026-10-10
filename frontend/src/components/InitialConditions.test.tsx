import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { makeExperimentParameters, makePoolDocument, makeRuleDocument } from "../test-fixtures";
import { InitialConditions } from "./InitialConditions";

describe("InitialConditions", () => {
  it("keeps legal zero for a known disabled rarity and exposes an unknown zero outside the fold", () => {
    const rule = makeRuleDocument();
    const pool = makePoolDocument();
    const rarity = rule.rarities[0];
    rarity.soft_enabled = false;
    rarity.hard_enabled = false;
    const value = { ...makeExperimentParameters(), initial_small_pity: { [rarity.id]: "0" } };
    const { rerender } = render(<InitialConditions rule={rule} pool={pool} value={value} savedContext={null} onChange={vi.fn()} onConfirm={vi.fn()} />);
    expect(screen.queryByText(/有待处理设置/)).not.toBeInTheDocument();
    rerender(<InitialConditions rule={rule} pool={pool} value={{ ...value, initial_small_pity: { ...value.initial_small_pity, "removed-id": "0" } }} savedContext={null} onChange={vi.fn()} onConfirm={vi.fn()} />);
    expect(screen.getByText(/有待处理设置/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "清除这项旧计数" })).toBeVisible();
  });

  it("uses first confirmation wording for nonzero state and keeps cycle conflicts actionable", () => {
    const rule = makeRuleDocument();
    const pool = makePoolDocument();
    rule.big_pity.after_obtain = "reset_after_obtain";
    const value = { ...makeExperimentParameters(), initial_main_draws: "7", initial_big_pity: { target_obtained: true, misses: "3" } };
    const onChange = vi.fn();
    render(<InitialConditions rule={rule} pool={pool} value={value} savedContext={null} onChange={onChange} onConfirm={vi.fn()} />);
    expect(screen.getByText(/请确认这些初始条件对应当前规则和目标/)).toBeInTheDocument();
    expect(screen.queryByText(/目标从“未解析”/)).not.toBeInTheDocument();
    expect(screen.getByText(/循环模式只使用连续未命中次数/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "清除旧目标标记" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ initial_big_pity: { target_obtained: false, misses: "3" } }));
  });
});
