import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";
import type { Rule } from "../api/types";
import { makePoolDocument, makeRuleDocument } from "../test-fixtures";
import { RuleSummary } from "./RuleSummary";

afterEach(cleanup);

it("shows the pool's rarity names and enabled rule parameters with the selected rule link", () => {
  const document = makeRuleDocument();
  document.big_pity.enabled = true;
  document.big_pity.hard_pity = 90;
  document.big_pity.after_obtain = "reset_after_obtain";
  document.bonus.enabled = true;
  document.bonus.at_main_draw = 30;
  document.bonus.draws = 10;
  document.grant.enabled = true;
  document.grant.period = 120;
  document.grant.quantity = 2;
  document.grant.target = "first_up";
  const rule = { id: document.id, name: "规则A", original_author: "作者", algorithm: document.algorithm,
    kind: "private", visibility: "hidden", owner_id: "user-a", owner_name: "用户A", revision: 7,
    reference_count: 0, structure_locked: false, document } as Rule;
  const pool = makePoolDocument();
  pool.rarity_labels[document.rarities[0].id] = "自定义低档";
  const sorted = [...document.rarities].sort((a, b) => b.rank - a.rank);
  pool.rarity_pools.find((roster) => roster.rarity_id === sorted[0].id)!.characters = [
    { id: "top-up", rarity_id: sorted[0].id, name: "最高档UP", weight: 1, is_up: true, is_limited: true },
  ];
  pool.rarity_pools.find((roster) => roster.rarity_id === sorted[1].id)!.characters = [
    { id: "lower-up", rarity_id: sorted[1].id, name: "较低档UP", weight: 1, is_up: true, is_limited: true },
  ];
  pool.mechanism_targets.periodic_grant = "ignored-for-auto-target";

  const { container } = render(<MemoryRouter><RuleSummary rule={rule} pool={pool} /></MemoryRouter>);

  expect(screen.getByRole("link", { name: "查看所选规则" })).toHaveAttribute("href", `/rules/${encodeURIComponent(document.id)}/`);
  const details = [...container.querySelectorAll("dd")].map((item) => item.textContent ?? "");
  expect(details[1]).toContain("自定义低档");
  expect(details[2]).toContain("自定义低档");
  expect(details[3]).toContain("第90次主抽必得目标；最高档UP，按最高档名单顺序选中");
  expect(details[3]).toContain("命中目标后重新计数");
  expect(details[4]).toContain("主抽第30次时执行10次赠送抽");
  expect(details[5]).toContain("每120次主抽直接赠送2名角色；最高档UP；自动目标按最高档到低档寻找第一个UP");
});

it("shows only off states for disabled mechanisms and disabled pity parameters", () => {
  const document = makeRuleDocument();
  document.rarities.forEach((rarity) => { rarity.soft_enabled = false; rarity.hard_enabled = false; });
  document.big_pity.enabled = false;
  document.bonus.enabled = false;
  document.grant.enabled = false;
  const rule = { id: document.id, name: "关闭项规则", original_author: "作者", algorithm: document.algorithm,
    kind: "public", visibility: "public", owner_id: null, owner_name: null, revision: 1,
    reference_count: 0, structure_locked: false, document } as Rule;

  render(<MemoryRouter><RuleSummary rule={rule} pool={makePoolDocument()} /></MemoryRouter>);

  expect(screen.getByText("全部关闭")).toBeInTheDocument();
  expect(screen.getAllByText("已关闭")).toHaveLength(3);
  expect(screen.queryByText(/软保底起点/)).toBeNull();
  expect(screen.queryByText(/第\d+次主抽/)).toBeNull();
});
