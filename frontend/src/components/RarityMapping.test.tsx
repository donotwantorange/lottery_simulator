import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Rule } from "../api/types";
import { makeRuleDocument } from "../test-fixtures";
import { RarityMapping } from "./RarityMapping";

afterEach(cleanup);

function makeRules(): [Rule, Rule, string, string] {
  const previousDocument = makeRuleDocument();
  const removed = previousDocument.rarities.at(-1)!;
  const retained = previousDocument.rarities[0];
  const nextDocument = structuredClone(previousDocument);
  nextDocument.rarities = nextDocument.rarities.filter((rarity) => rarity.id !== removed.id);
  nextDocument.rarities.push({ ...removed, id: "new-rarity-id", name: "新档名", rank: removed.rank });
  nextDocument.bonus.rarities = nextDocument.bonus.rarities.filter((rarity) => rarity.id !== removed.id);
  nextDocument.bonus.rarities.push({ ...removed, id: "new-rarity-id", name: "新档名", rank: removed.rank });
  const previous = { id: previousDocument.id, name: "旧规则", original_author: "作者", algorithm: previousDocument.algorithm,
    kind: "public", visibility: "public", owner_id: null, owner_name: null, revision: 1,
    reference_count: 1, structure_locked: true, document: previousDocument } as Rule;
  const next = { ...previous, id: "new-rule-id", name: "新规则", revision: 2, document: nextDocument };
  return [previous, next, removed.name, retained.name];
}

it("explains same-ID retention and the effects of mapping an old rarity to a new name", () => {
  const [previous, next, removedName, retainedName] = makeRules();
  const { rerender } = render(<RarityMapping previous={previous} next={next} mapping={{}}
    onChange={vi.fn()} clearUnmapped={false} onClearUnmapped={vi.fn()} />);

  expect(screen.getByText(new RegExp(`${retainedName} → ${retainedName}：按相同ID保留名单、显示名和奖励`))).toBeInTheDocument();
  expect(screen.getByText(new RegExp(`${removedName} → 尚未选择映射目标或清空`))).toBeInTheDocument();
  const choice = screen.getByLabelText(`${removedName}（旧档）`);
  fireEvent.change(choice, { target: { value: "new-rarity-id" } });
  rerender(<RarityMapping previous={previous} next={next} mapping={{ [previous.document.rarities.at(-1)!.id]: "new-rarity-id" }}
    onChange={vi.fn()} clearUnmapped={false} onClearUnmapped={vi.fn()} />);
  expect(screen.getByText(new RegExp(`${removedName} → 新档名：名单、显示名和奖励迁移`))).toBeInTheDocument();
  expect(screen.queryByLabelText(/确认清空/)).toBeNull();
});

it("asks for clear confirmation only after selecting null for a removed rarity", () => {
  const [previous, next, removedName] = makeRules();
  const onChange = vi.fn();
  const { rerender } = render(<RarityMapping previous={previous} next={next} mapping={{}}
    onChange={onChange} clearUnmapped={false} onClearUnmapped={vi.fn()} />);

  expect(screen.queryByLabelText(/确认清空/)).toBeNull();
  fireEvent.change(screen.getByLabelText(`${removedName}（旧档）`), { target: { value: "__clear__" } });
  const cleared = { [previous.document.rarities.at(-1)!.id]: null };
  expect(onChange).toHaveBeenCalledWith(cleared);
  rerender(<RarityMapping previous={previous} next={next} mapping={cleared}
    onChange={onChange} clearUnmapped={false} onClearUnmapped={vi.fn()} />);
  expect(screen.getByRole("checkbox", { name: "确认清空所选旧档数据" })).toBeInTheDocument();
  expect(screen.getByText(new RegExp(`${removedName} → 清空：该档名单、显示名和奖励将被移除`))).toBeInTheDocument();
});

it("does not offer a removed old ID as a mapping target", () => {
  const [previous, next, removedName] = makeRules();
  render(<RarityMapping previous={previous} next={next} mapping={{}}
    onChange={vi.fn()} clearUnmapped={false} onClearUnmapped={vi.fn()} />);
  const choices = screen.getByLabelText(`${removedName}（旧档）`);
  expect(choices.querySelector(`option[value="${previous.document.rarities.at(-1)!.id}"]`)).toBeNull();
});
