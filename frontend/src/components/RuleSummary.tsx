import type { PoolDocument, Rule } from "../api/types";

interface Props { rule: Rule; pool: PoolDocument }

export function RuleSummary({ rule, pool }: Props) {
  const byRank = [...rule.document.rarities].sort((a, b) => b.rank - a.rank);
  const rosters = new Map(pool.rarity_pools.map((item) => [item.rarity_id, item]));
  const allCharacters = byRank.flatMap((rarity) => rosters.get(rarity.id)?.characters ?? []);
  const firstUp = allCharacters.find((item) => item.is_up);
  const highest = byRank[0];
  const big = rule.document.big_pity.enabled
    ? rule.document.big_pity.target === "first_up" && highest
      ? rosters.get(highest.id)?.characters.find((item) => item.is_up)
      : undefined
    : undefined;
  const grant = !rule.document.grant.enabled ? undefined
    : rule.document.grant.target === "first_up" ? firstUp
      : allCharacters.find((item) => item.id === pool.mechanism_targets.periodic_grant);

  return <section className="editor-section" aria-labelledby="rule-summary-title">
    <div className="section-heading"><div><h3 id="rule-summary-title">规则摘要</h3>
      <p className="muted">角色、奖励与目标保存在池；概率与保底由绑定规则决定。</p></div>
      <a className="secondary-button" href="/rules/">查看规则</a></div>
    <dl className="pool-rule-summary">
      <dt>规则 / 修订</dt><dd>{rule.name} · {rule.revision}</dd>
      <dt>基础概率</dt><dd>{byRank.slice().reverse().map((rarity) =>
        `${rarity.name} ${(rarity.base_probability * 100).toFixed(3)}%`).join(" · ")}</dd>
      <dt>大保底目标</dt><dd>{rule.document.big_pity.enabled ? big?.name ?? "未解析：需绑定最高档UP角色" : "已关闭"}</dd>
      <dt>首次赠送</dt><dd>{rule.document.bonus.enabled
        ? `主抽第${rule.document.bonus.at_main_draw}抽触发，另抽${rule.document.bonus.draws}次（独立保底）`
        : "已关闭"}</dd>
      <dt>周期直接赠送</dt><dd>{rule.document.grant.enabled
        ? `每${rule.document.grant.period}抽赠送${rule.document.grant.quantity}名：${grant?.name ?? "未解析，请选择目标角色"}`
        : "已关闭"}</dd>
    </dl>
  </section>;
}
