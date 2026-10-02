import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeRuleDocument } from "../test-fixtures";
import type { RuleDocument } from "../api/types";
import { RuleEditor } from "./RuleEditor";

afterEach(cleanup);

function renderRuleEditor(props: ComponentProps<typeof RuleEditor>) {
  return render(<RuleEditor {...props} />);
}

describe("RuleEditor", () => {
  it("shows the structure lock guidance, probability units, and data-driven first-increase example", () => {
    const rule = makeRuleDocument();
    const example = rule.rarities.find((item) => item.soft_enabled)!;
    renderRuleEditor({ value: rule, onChange: vi.fn(), structureLocked: true });

    expect(screen.getByText(/复制为新规则/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "添加稀有度" })).toBeDisabled();
    expect(screen.getAllByText(/百分点/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(new RegExp(`第${example.soft_start - 1}抽不增加，第${example.soft_start}抽开始增加`)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/周期直接赠送已关闭/)).toBeNull();
  });

  it("converts probability text on blur and blocks invalid local text", () => {
    const value = makeRuleDocument();
    let current = value;
    const onChange = vi.fn((next: RuleDocument) => { current = next; });
    const onValidityChange = vi.fn();
    renderRuleEditor({ value, onChange, structureLocked: false, onValidityChange });

    const probability = screen.getByRole("textbox", { name: "六星基础概率（百分比）" });
    fireEvent.change(probability, { target: { value: "1.2" } });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.blur(probability);
    expect(current.rarities.find((item) => item.name === "六星")?.base_probability).toBeCloseTo(0.012);

    fireEvent.change(screen.getByRole("textbox", { name: "六星基础概率（百分比）" }), { target: { value: "0x10" } });
    fireEvent.blur(screen.getByRole("textbox", { name: "六星基础概率（百分比）" }));
    expect(screen.getByRole("alert")).toHaveTextContent("请输入");
    expect(onValidityChange).toHaveBeenLastCalledWith(false);
  });

  it("keeps bonus rarity IDs and rank aligned when main rarities are reordered", () => {
    const rule = makeRuleDocument();
    rule.bonus.enabled = false;
    rule.bonus.rarities = [];
    let current = rule;
    const editor = { current: null as ReturnType<typeof renderRuleEditor> | null };
    const onChange = (next: RuleDocument) => {
      current = next;
      editor.current?.rerender(<RuleEditor value={current} onChange={onChange} structureLocked={false} />);
    };
    editor.current = renderRuleEditor({ value: current, onChange, structureLocked: false });
    const firstId = current.rarities[0].id;
    fireEvent.click(screen.getByRole("button", { name: "四星下移" }));
    expect(current.bonus.rarities).toHaveLength(0);
    fireEvent.click(screen.getByRole("checkbox", { name: "启用首次赠送" }));
    expect(current.rarities.findIndex((item) => item.id === firstId)).toBe(1);
    expect(current.bonus.rarities.map((item) => [item.id, item.rank])).toEqual(current.rarities.map((item) => [item.id, item.rank]));
  });

  it("disables fields for closed mechanisms and keeps bonus soft and hard pity editable when enabled", () => {
    const rule = makeRuleDocument();
    rule.bonus.enabled = false;
    rule.grant.enabled = false;
    renderRuleEditor({ value: rule, onChange: vi.fn(), structureLocked: false });
    expect(screen.getByRole("textbox", { name: "四星软保底起点" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "触发主抽位置" })).toBeDisabled();
    expect(screen.getByText(/周期直接赠送已关闭/)).toBeTruthy();

    cleanup();
    rule.bonus.enabled = true;
    rule.bonus.rarities.find((item) => item.name === "六星")!.hard_enabled = true;
    renderRuleEditor({ value: rule, onChange: vi.fn(), structureLocked: false });
    expect(screen.getByRole("textbox", { name: "六星赠送池硬保底抽数" })).toBeEnabled();
    expect(screen.getByRole("textbox", { name: "六星赠送池每抽增幅（百分点）" })).toBeDisabled();
  });

  it("blocks saving counts that cannot be represented as safe integers", () => {
    const rule = makeRuleDocument();
    rule.grant.period = Number.MAX_SAFE_INTEGER + 1;
    const onValidityChange = vi.fn();
    renderRuleEditor({ value: rule, onChange: vi.fn(), structureLocked: false, onValidityChange });
    expect(screen.getByText(/超出安全整数范围/)).toBeTruthy();
    expect(onValidityChange).toHaveBeenLastCalledWith(false);
  });
});
