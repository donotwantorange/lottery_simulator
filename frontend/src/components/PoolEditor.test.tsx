import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { useState } from "react";
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
  return { onChange, ...render(<MemoryRouter><PoolEditor value={value} rule={rule} rules={rules}
    kind="private" visibility="hidden" canEdit={true} canCreatePublic={false} editing={false}
    poolOwnerId="user-a" onChange={onChange} onKind={vi.fn()} onVisibility={vi.fn()}
    onRuleMapping={vi.fn()} onCancelRuleMapping={vi.fn()} /></MemoryRouter>) };
}

function StatefulPoolEditor({ initial, rule, onValidityChange }: {
  initial: PoolDocument;
  rule: Rule;
  onValidityChange: (valid: boolean) => void;
}) {
  const [value, setValue] = useState(initial);
  return <MemoryRouter><PoolEditor value={value} rule={rule} rules={[rule]}
    kind="private" visibility="hidden" canEdit={true} canCreatePublic={false} editing={false}
    poolOwnerId="user-a" onChange={setValue} onKind={vi.fn()} onVisibility={vi.fn()}
    onRuleMapping={vi.fn()} onCancelRuleMapping={vi.fn()} onValidityChange={onValidityChange} /></MemoryRouter>;
}

function StatefulMappingEditor({ initial, previous, next, onValidityChange }: {
  initial: PoolDocument;
  previous: Rule;
  next: Rule;
  onValidityChange: (valid: boolean) => void;
}) {
  const [value, setValue] = useState(initial);
  const rule = value.rule_ref.id === next.id ? next : previous;
  return <MemoryRouter><PoolEditor value={value} rule={rule} rules={[previous, next]}
    kind="private" visibility="hidden" canEdit={true} canCreatePublic={false} editing={true}
    savedRuleId={previous.id} poolOwnerId="user-a" onChange={setValue} onKind={vi.fn()} onVisibility={vi.fn()}
    onRuleMapping={vi.fn()} onCancelRuleMapping={vi.fn()} onValidityChange={onValidityChange} /></MemoryRouter>;
}

it("shows a dynamic read-only rule summary and explains weight ratios", () => {
  const rule = makeRule();
  const pool = makePoolDocument();
  const { container } = renderEditor(pool, [rule]);
  expect(screen.getByText(/查看所选规则/)).toBeInTheDocument();
  expect(screen.getByText(/权重1和2表示组内概率比例1:2/)).toBeInTheDocument();
  expect(screen.queryByLabelText("六星基础概率")).not.toBeInTheDocument();
  expect(container.querySelectorAll(".pool-rarity")).toHaveLength(rule.document.rarities.length);
});

it("shows the actual type of a public pool in read-only mode without enabling changes", () => {
  const rule = makeRule();
  const { container } = render(<MemoryRouter><PoolEditor value={makePoolDocument()} rule={rule} rules={[rule]} kind="public" visibility="public"
    canEdit={false} canCreatePublic={false} editing={false} poolOwnerId={null} onChange={vi.fn()}
    onKind={vi.fn()} onVisibility={vi.fn()} onRuleMapping={vi.fn()} onCancelRuleMapping={vi.fn()} /></MemoryRouter>);
  expect(screen.getByText("公共池")).toBeInTheDocument();
  expect(screen.queryByLabelText("池类型")).not.toBeInTheDocument();
  expect(container.querySelectorAll(".pool-readonly input, .pool-readonly select")).toHaveLength(0);
});

it("explains the highest-tier first-UP target independently of character weights", () => {
  const rule = makeRule();
  rule.document.big_pity.enabled = true;
  const pool = makePoolDocument();
  const highest = [...rule.document.rarities].sort((a, b) => b.rank - a.rank)[0];
  const roster = pool.rarity_pools.find((item) => item.rarity_id === highest.id)!;
  roster.characters = [
    { id: "ordinary", rarity_id: highest.id, name: "普通角色", weight: 1, is_up: false, is_limited: false },
    { id: "first-up", rarity_id: highest.id, name: "排序第一UP", weight: 2, is_up: true, is_limited: true },
    { id: "heavier-up", rarity_id: highest.id, name: "权重更高UP", weight: 99, is_up: true, is_limited: true },
  ];
  renderEditor(pool, [rule]);
  expect(screen.getByText(/大保底目标：排序第一UP（规则使用最高稀有度中排序第一的UP）/)).toBeInTheDocument();
  expect(screen.getByText("按这一档角色名单从上到下选择第一个标记UP的角色，与权重大小无关。")).toBeInTheDocument();
  expect(screen.getByText(/按最高档名单顺序选中/)).toBeInTheDocument();
});

it("falls back to a lower-tier first UP for periodic gifts when big pity is disabled", () => {
  const rule = makeRule();
  rule.document.big_pity.enabled = false;
  rule.document.grant.enabled = true;
  rule.document.grant.target = "first_up";
  const pool = makePoolDocument();
  const sorted = [...rule.document.rarities].sort((a, b) => b.rank - a.rank);
  pool.rarity_pools.find((item) => item.rarity_id === sorted[0].id)!.characters = [
    { id: "ordinary", rarity_id: sorted[0].id, name: "最高档普通角色", weight: 1, is_up: false, is_limited: false },
  ];
  pool.rarity_pools.find((item) => item.rarity_id === sorted[1].id)!.characters = [
    { id: "lower-up", rarity_id: sorted[1].id, name: "低档UP目标", weight: 1, is_up: true, is_limited: true },
  ];
  renderEditor(pool, [rule]);
  expect(screen.getByText("周期赠送目标：低档UP目标")).toBeInTheDocument();
  expect(screen.queryByText(/大保底目标：/)).toBeNull();
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
  render(<MemoryRouter><PoolEditor value={pool} rule={rule} rules={[rule]} kind="private" visibility="hidden"
    canEdit={true} canCreatePublic={false} editing={false} poolOwnerId="user-a" onChange={onChange}
    onKind={vi.fn()} onVisibility={vi.fn()} onRuleMapping={vi.fn()} onCancelRuleMapping={vi.fn()}
    onValidityChange={onValidityChange} /></MemoryRouter>);
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
  const { rerender } = render(<MemoryRouter><PoolEditor value={pool} rule={previous} rules={[previous, next]}
    kind="private" visibility="hidden" canEdit={true} canCreatePublic={false} editing={true} savedRuleId={previous.id}
    poolOwnerId="user-a" onChange={onChange} onKind={vi.fn()} onVisibility={vi.fn()}
    onRuleMapping={onRuleMapping} onCancelRuleMapping={vi.fn()} /></MemoryRouter>);

  fireEvent.change(screen.getByLabelText("绑定规则"), { target: { value: next.id } });
  const map = screen.getByLabelText(`${removed.name}（旧档）`);
  fireEvent.change(map, { target: { value: added.id } });
  fireEvent.click(screen.getByRole("button", { name: "应用映射并切换" }));
  const changed = onChange.mock.calls.at(-1)?.[0] as PoolDocument;
  expect(changed.rule_ref).toEqual({ id: next.id, name: next.name });
  expect(changed.rarity_pools.find((roster) => roster.rarity_id === added.id)?.characters[0].id).toBe(characterId);
  expect(onRuleMapping).toHaveBeenCalledWith({ [removed.id]: added.id }, false);
  rerender(<MemoryRouter><PoolEditor value={changed} rule={next} rules={[previous, next]} kind="private" visibility="hidden"
    canEdit={true} canCreatePublic={false} editing={true} savedRuleId={previous.id} poolOwnerId="user-a"
    onChange={onChange} onKind={vi.fn()} onVisibility={vi.fn()} onRuleMapping={onRuleMapping} onCancelRuleMapping={vi.fn()} /></MemoryRouter>);
  expect(screen.getByText(/映射结果需先保存/)).toBeInTheDocument();
});

it("removes a deleted character's invalid weight and keeps the remaining roster valid", async () => {
  const rule = makeRule();
  rule.document.big_pity.enabled = false;
  rule.document.grant.enabled = false;
  const pool = makePoolDocument();
  const roster = pool.rarity_pools.find((item) => item.characters.length > 0)!;
  roster.characters = roster.characters.slice(0, 2);
  roster.up_enabled = false;
  const onValidityChange = vi.fn();
  render(<StatefulPoolEditor initial={pool} rule={rule} onValidityChange={onValidityChange} />);

  const weight = screen.getAllByLabelText("角色权重")[0];
  fireEvent.change(weight, { target: { value: "0" } });
  fireEvent.blur(weight);
  expect(screen.getByText("权重必须是大于0的有限数值。")).toBeInTheDocument();
  await waitFor(() => expect(onValidityChange).toHaveBeenLastCalledWith(false));

  const deleteButton = screen.getAllByRole("button", { name: "删除" })[0];
  fireEvent.click(deleteButton);
  await waitFor(() => expect(onValidityChange).toHaveBeenLastCalledWith(true));
  expect(screen.queryByText("权重必须是大于0的有限数值。")).toBeNull();
});

it("keeps weight validation independent from name edits and other invalid characters", async () => {
  const rule = makeRule();
  rule.document.big_pity.enabled = false;
  rule.document.grant.enabled = false;
  const pool = makePoolDocument();
  const roster = pool.rarity_pools.find((item) => item.characters.length > 0)!;
  roster.characters = roster.characters.slice(0, 2);
  roster.up_enabled = false;
  const onValidityChange = vi.fn();
  render(<StatefulPoolEditor initial={pool} rule={rule} onValidityChange={onValidityChange} />);

  const weights = screen.getAllByLabelText("角色权重");
  fireEvent.change(weights[0], { target: { value: "0" } });
  fireEvent.blur(weights[0]);
  fireEvent.change(screen.getAllByLabelText("角色名称")[0], { target: { value: "" } });
  expect(screen.getByText("角色名称不能为空。")).toBeInTheDocument();
  fireEvent.change(screen.getAllByLabelText("角色名称")[0], { target: { value: "改过的名字" } });
  expect(screen.getByText("权重必须是大于0的有限数值。")).toBeInTheDocument();
  await waitFor(() => expect(onValidityChange).toHaveBeenLastCalledWith(false));

  fireEvent.change(screen.getAllByLabelText("角色权重")[1], { target: { value: "0" } });
  fireEvent.blur(screen.getAllByLabelText("角色权重")[1]);
  fireEvent.click(screen.getAllByRole("button", { name: "删除" })[0]);
  await waitFor(() => expect(onValidityChange).toHaveBeenLastCalledWith(false));
  expect(screen.getByText("权重必须是大于0的有限数值。")).toBeInTheDocument();
  const remainingWeight = screen.getAllByLabelText("角色权重")[0];
  fireEvent.change(remainingWeight, { target: { value: "3" } });
  fireEvent.blur(remainingWeight);
  await waitFor(() => expect(onValidityChange).toHaveBeenLastCalledWith(true));
});

it("clears invalid weight drafts when a rule mapping removes their character", async () => {
  const previous = makeRule("旧规则");
  previous.document.big_pity.enabled = false;
  previous.document.grant.enabled = false;
  const nextDocument = structuredClone(previous.document);
  nextDocument.id = "mapped-rule-id";
  nextDocument.name = "新规则";
  const removed = nextDocument.rarities.at(-1)!;
  nextDocument.rarities = nextDocument.rarities.filter((rarity) => rarity.id !== removed.id);
  const added = { ...removed, id: "mapped-rarity-id", name: "新档", rank: removed.rank };
  nextDocument.rarities.push(added);
  nextDocument.bonus.rarities = nextDocument.bonus.rarities.filter((rarity) => rarity.id !== removed.id);
  nextDocument.bonus.rarities.push(added);
  const next: Rule = { ...previous, id: nextDocument.id, name: nextDocument.name, document: nextDocument };
  const pool = makePoolDocument();
  const roster = pool.rarity_pools.find((item) => item.rarity_id === removed.id)!;
  roster.characters = [roster.characters[0]];
  roster.up_enabled = false;
  const onValidityChange = vi.fn();
  render(<StatefulMappingEditor initial={pool} previous={previous} next={next} onValidityChange={onValidityChange} />);

  fireEvent.change(screen.getByLabelText("角色权重"), { target: { value: "0" } });
  fireEvent.blur(screen.getByLabelText("角色权重"));
  expect(screen.getByText("权重必须是大于0的有限数值。")).toBeInTheDocument();
  await waitFor(() => expect(onValidityChange).toHaveBeenLastCalledWith(false));

  fireEvent.change(screen.getByLabelText("绑定规则"), { target: { value: next.id } });
  fireEvent.change(screen.getByLabelText(removed.name + "（旧档）"), { target: { value: "__clear__" } });
  fireEvent.click(screen.getByRole("checkbox", { name: "确认清空所选旧档数据" }));
  fireEvent.click(screen.getByRole("button", { name: "应用映射并切换" }));
  expect(screen.queryByText("权重必须是大于0的有限数值。")).toBeNull();
  await waitFor(() => expect(onValidityChange).toHaveBeenLastCalledWith(true));
});

it("hides UP share while the group is off but keeps character UP flags editable", () => {
  const rule = makeRule();
  const pool = makePoolDocument();
  const roster = pool.rarity_pools.find((item) => item.characters.length > 0)!;
  roster.up_enabled = false;
  roster.characters = [roster.characters.find((character) => character.is_up)!];
  renderEditor(pool, [rule]);
  expect(screen.queryByLabelText("UP占比（%）")).toBeNull();
  expect(screen.getAllByText(/角色的UP标记用于分类和自动目标/)).toHaveLength(rule.document.rarities.length);
  const up = screen.getByRole("checkbox", { name: "UP" });
  expect(up).toBeChecked();
  expect(up).toBeEnabled();
});

it("keeps invalid UP text accessible after closing and discards only that unfinished input", async () => {
  const rule = makeRule();
  rule.document.big_pity.enabled = false;
  rule.document.grant.enabled = false;
  const pool = makePoolDocument();
  const roster = pool.rarity_pools[0];
  roster.up_enabled = true;
  const onValidityChange = vi.fn();
  render(<StatefulPoolEditor initial={pool} rule={rule} onValidityChange={onValidityChange} />);
  const share = screen.getAllByLabelText("UP占比（%）")[0];
  fireEvent.change(share, { target: { value: "" } });
  expect(share).toHaveValue("");
  await waitFor(() => expect(onValidityChange).toHaveBeenLastCalledWith(false));
  fireEvent.click(screen.getAllByRole("checkbox", { name: "启用UP概率分组" })[0]);
  expect(document.getElementById(`pool-up-share-${roster.rarity_id}`)).toBeNull();
  expect(screen.getByText("UP占比有未完成的参数修改。")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "展开修正" }));
  expect(document.getElementById(`pool-up-share-${roster.rarity_id}`)).toHaveValue("");
  fireEvent.click(screen.getByRole("button", { name: "放弃未完成输入，恢复上次合法值" }));
  expect(screen.queryByText("UP占比有未完成的参数修改。")).toBeNull();
  await waitFor(() => expect(onValidityChange).toHaveBeenLastCalledWith(true));
});

it("keeps a blank reward amount invalid until its reward is deleted", async () => {
  const rule = makeRule();
  rule.document.big_pity.enabled = false;
  rule.document.grant.enabled = false;
  const pool = makePoolDocument();
  const onValidityChange = vi.fn();
  render(<StatefulPoolEditor initial={pool} rule={rule} onValidityChange={onValidityChange} />);
  const reward = screen.getAllByText(/数量/).find((label) => label.querySelector("input"))?.querySelector("input") as HTMLInputElement;
  fireEvent.change(reward, { target: { value: "" } });
  expect(reward).toHaveValue("");
  await waitFor(() => expect(onValidityChange).toHaveBeenLastCalledWith(false));
  fireEvent.click(screen.getAllByRole("button", { name: "删除奖励" })[0]);
  expect(screen.queryByText("请输入大于或等于0的有限数值。")).toBeNull();
  await waitFor(() => expect(onValidityChange).toHaveBeenLastCalledWith(true));
});

it("shows no target controls when both mechanisms are off and only a selector for a chosen periodic target", () => {
  const rule = makeRule();
  rule.document.big_pity.enabled = false;
  rule.document.grant.enabled = false;
  renderEditor(makePoolDocument(), [rule]);
  expect(screen.queryByLabelText("周期赠送角色")).toBeNull();
  expect(screen.queryByText(/机制目标绑定/)).toBeNull();

  rule.document.grant.enabled = true;
  rule.document.grant.target = "pool_selected";
  renderEditor(makePoolDocument(), [rule]);
  expect(screen.getByLabelText("周期赠送角色")).toBeInTheDocument();
  expect(screen.queryByText(/自动目标按最高档到低档/)).toBeNull();
});
