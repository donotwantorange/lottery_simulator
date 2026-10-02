import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { PoolDocument, Rule } from "../api/types";
import { makePoolDocument, makeRuleDocument } from "../test-fixtures";
import { PoolEditor } from "./PoolEditor";

afterEach(cleanup);

function makeRule(name = "zmd"): Rule {
  const document = makeRuleDocument();
  document.name = name;
  return { id: document.id, name, original_author: "默认作者", algorithm: document.algorithm,
    kind: "public", visibility: "public", owner_id: null, owner_name: null, revision: 1,
    reference_count: 0, structure_locked: false, document };
}

function renderEditor(value: PoolDocument, rules: Rule[], onChange = vi.fn()) {
  const rule = rules.find((item) => item.id === value.rule_ref.id);
  return { onChange, ...render(<PoolEditor value={value} rule={rule} rules={rules}
    kind="private" visibility="hidden" canEdit={true} canCreatePublic={false} editing={false}
    poolOwnerId="user-a" onChange={onChange} onKind={vi.fn()} onVisibility={vi.fn()}
    onRuleMapping={vi.fn()} onCancelRuleMapping={vi.fn()} />) };
}

it("shows a dynamic read-only rule summary and explains weight ratios", () => {
  const rule = makeRule();
  const pool = makePoolDocument();
  const { container } = renderEditor(pool, [rule]);
  expect(screen.getByText(/查看规则/)).toBeInTheDocument();
  expect(screen.getByText(/权重1和2表示组内概率比例1:2/)).toBeInTheDocument();
  expect(screen.queryByLabelText("六星基础概率")).not.toBeInTheDocument();
  expect(container.querySelectorAll(".pool-rarity")).toHaveLength(rule.document.rarities.length);
});

it("renders a fourth rarity from the rule and retains invalid weight text until corrected", async () => {
  const rule = makeRule();
  const pool = makePoolDocument();
  const added = { ...rule.document.rarities[0], id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    name: "七星", rank: rule.document.rarities.length, base_probability: 0.001 };
  rule.document.rarities[0].base_probability -= added.base_probability;
  rule.document.rarities.push(added);
  if (rule.document.bonus.enabled) {
    rule.document.bonus.rarities[0].base_probability -= added.base_probability;
    rule.document.bonus.rarities.push({ ...added });
  }
  pool.rarity_pools.push({ rarity_id: added.id, characters: [{ id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    rarity_id: added.id, name: "七星角色", weight: 1, is_up: true, is_limited: true }], up_enabled: false, up_share: 0 });
  pool.rewards.forEach((reward) => { reward.amounts[added.id] = 0; });
  const onChange = vi.fn();
  const onValidityChange = vi.fn();
  render(<PoolEditor value={pool} rule={rule} rules={[rule]} kind="private" visibility="hidden"
    canEdit={true} canCreatePublic={false} editing={false} poolOwnerId="user-a" onChange={onChange}
    onKind={vi.fn()} onVisibility={vi.fn()} onRuleMapping={vi.fn()} onCancelRuleMapping={vi.fn()}
    onValidityChange={onValidityChange} />);
  expect(screen.getByRole("heading", { name: "七星" })).toBeInTheDocument();

  const weight = screen.getAllByLabelText("角色权重")[0];
  fireEvent.change(weight, { target: { value: "0" } });
  expect(onValidityChange).toHaveBeenLastCalledWith(false);
  fireEvent.blur(weight);
  expect(screen.getByText("权重必须是大于0的有限数值。")).toBeInTheDocument();
  expect(onChange).not.toHaveBeenCalled();
  fireEvent.change(weight, { target: { value: "2" } });
  fireEvent.blur(weight);
  expect(onChange).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(onValidityChange).toHaveBeenLastCalledWith(true));
});

it("keeps the same character ID and applies an explicit rarity mapping", () => {
  const previous = makeRule("旧规则");
  const targetDocument = makeRuleDocument();
  targetDocument.id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
  targetDocument.name = "新规则";
  const removed = targetDocument.rarities.pop()!;
  const added = { ...removed, id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", name: "新档", rank: 2 };
  targetDocument.rarities.push(added);
  targetDocument.bonus.rarities = targetDocument.bonus.rarities.filter((rarity) => rarity.id !== removed.id);
  targetDocument.bonus.rarities.push({ ...added });
  const next: Rule = { ...previous, id: targetDocument.id, name: "新规则", document: targetDocument, revision: 2 };
  const pool = makePoolDocument();
  const sourceRoster = pool.rarity_pools.find((roster) => roster.rarity_id === removed.id)!;
  const characterId = sourceRoster.characters[0].id;
  const onChange = vi.fn();
  const onRuleMapping = vi.fn();
  const { rerender } = render(<PoolEditor value={pool} rule={previous} rules={[previous, next]}
    kind="private" visibility="hidden" canEdit={true} canCreatePublic={false} editing={true} savedRuleId={previous.id}
    poolOwnerId="user-a" onChange={onChange} onKind={vi.fn()} onVisibility={vi.fn()}
    onRuleMapping={onRuleMapping} onCancelRuleMapping={vi.fn()} />);

  fireEvent.change(screen.getByLabelText("绑定规则"), { target: { value: next.id } });
  const map = screen.getByLabelText(`${removed.name}（旧档）`);
  fireEvent.change(map, { target: { value: added.id } });
  fireEvent.click(screen.getByRole("button", { name: "应用映射并切换" }));
  const changed = onChange.mock.calls.at(-1)?.[0] as PoolDocument;
  expect(changed.rule_ref).toEqual({ id: next.id, name: next.name });
  expect(changed.rarity_pools.find((roster) => roster.rarity_id === added.id)?.characters[0].id).toBe(characterId);
  expect(onRuleMapping).toHaveBeenCalledWith({ [removed.id]: added.id }, false);
  rerender(<PoolEditor value={changed} rule={next} rules={[previous, next]} kind="private" visibility="hidden"
    canEdit={true} canCreatePublic={false} editing={true} savedRuleId={previous.id} poolOwnerId="user-a"
    onChange={onChange} onKind={vi.fn()} onVisibility={vi.fn()} onRuleMapping={onRuleMapping} onCancelRuleMapping={vi.fn()} />);
  expect(screen.getByText(/映射结果需先保存/)).toBeInTheDocument();
});
