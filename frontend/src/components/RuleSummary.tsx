import { Link } from "react-router-dom";
import type { PoolDocument, Rule } from "../api/types";
import { formatProbability, softPityText, SOFT_PITY_CONSTRAINT } from "../formatters";

interface Props { rule: Rule; pool: PoolDocument }

export function RuleSummary({ rule, pool }: Props) {
  const byRank = [...rule.document.rarities].sort((a, b) => b.rank - a.rank);
  const rosters = new Map(pool.rarity_pools.map((item) => [item.rarity_id, item]));
  const rarityName = (rarityId: string, fallback: string) => pool.rarity_labels[rarityId]?.trim() || fallback;
  const allCharacters = byRank.flatMap((rarity) => rosters.get(rarity.id)?.characters ?? []);
  const firstUp = allCharacters.find((item) => item.is_up);
  const highest = byRank[0];
  const bigTarget = rule.document.big_pity.enabled && rule.document.big_pity.target === "first_up" && highest
    ? rosters.get(highest.id)?.characters.find((item) => item.is_up)
    : undefined;
  const grantTarget = !rule.document.grant.enabled ? undefined
    : rule.document.grant.target === "first_up" ? firstUp
      : allCharacters.find((item) => item.id === pool.mechanism_targets.periodic_grant);
  const enabledPity = byRank.flatMap((rarity) => {
    const settings = rule.document.rarities.find((item) => item.id === rarity.id)!;
    const soft = softPityText({ ...settings, name: rarityName(rarity.id, rarity.name) }, rarity.id === highest.id);
    const hard = settings.hard_enabled ? `硬保底第${settings.hard_pity}抽` : "硬保底未启用";
    return [`${rarityName(rarity.id, rarity.name)}：${soft}；${hard}`];
  });
  const smallPity = enabledPity.every((line) => line.endsWith("软保底未启用；硬保底未启用"))
    ? "全部关闭"
    : enabledPity.join(" · ");
  const afterObtain = rule.document.big_pity.after_obtain === "reset_after_obtain"
    ? "命中目标后重新计数"
    : "本轮命中目标后关闭";
  const grantTargetText = rule.document.grant.target === "first_up"
    ? `${grantTarget?.name ?? "未解析UP目标"}；自动目标按最高档到低档寻找第一个UP`
    : `${grantTarget?.name ?? "未解析指定角色"}；使用池指定角色`;

  return <section className="editor-section" aria-labelledby="rule-summary-title">
    <div className="section-heading"><div><h3 id="rule-summary-title">规则摘要</h3>
      <p className="muted">角色、奖励与目标保存在池；概率与保底由绑定规则决定。</p></div>
      <Link className="secondary-button" to={`/rules/${encodeURIComponent(rule.id)}/`}>查看所选规则</Link></div>
    <dl className="pool-rule-summary">
      <dt>规则 / 修订</dt><dd>{rule.name} · {rule.revision}</dd>
      <dt>基础概率</dt><dd>{byRank.slice().reverse().map((rarity) =>
        `${rarityName(rarity.id, rarity.name)} ${formatProbability(rarity.base_probability)}`).join(" · ")}</dd>
      <dt>小保底</dt><dd>{smallPity}</dd>
      {byRank.some((item) => item.soft_enabled) && <><dt>软保底约束</dt><dd>{SOFT_PITY_CONSTRAINT}</dd></>}
      <dt>大保底目标</dt><dd>{rule.document.big_pity.enabled
        ? `第${rule.document.big_pity.hard_pity}次主抽必得目标；${bigTarget?.name ?? "未解析：需绑定最高档UP角色"}，按最高档名单顺序选中；${afterObtain}`
        : "已关闭"}</dd>
      <dt>首次赠送</dt><dd>{rule.document.bonus.enabled
        ? `主抽第${rule.document.bonus.at_main_draw}次时执行${rule.document.bonus.draws}次赠送抽`
        : "已关闭"}</dd>
      <dt>周期赠送</dt><dd>{rule.document.grant.enabled
        ? `每${rule.document.grant.period}次主抽直接赠送${rule.document.grant.quantity}名角色；${grantTargetText}`
        : "已关闭"}</dd>
    </dl>
  </section>;
}
