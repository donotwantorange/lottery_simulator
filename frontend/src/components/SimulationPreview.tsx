import type { SimulationPreview as PreviewResult } from "../api/types";
import { formatCount } from "../formatters";

interface Props { value: PreviewResult | null; }

export function SimulationPreview({ value }: Props) {
  if (!value) return <p className="muted">检查输入后显示本次模拟的确定性计数预览。</p>;
  const { per_trial: each, total } = value.counts;
  const start = BigInt(value.parameters.initial_main_draws);
  const end = start + BigInt(value.parameters.draws);
  const trigger = (position: string | null) => position === null ? "未启用或已触发" :
    `累计主抽第 ${formatCount(position)} 抽；${BigInt(position) <= end ? "本次可触发" : "本次不会触发"}`;
  const groups = [{ title: "每轮", counts: each }, { title: "全部轮次", counts: total }];
  return <div aria-label="模拟预览" className="page-stack">
    <p className="muted">规则：{value.rule_source.name}；角色池：{value.pool_source.name}。<small>规则修订 {value.rule_source.revision}，池修订 {value.pool_source.revision}</small></p>
    {groups.map(({ title, counts }) => <section key={title} className="readonly-summary" aria-label={`${title}计数`}>
      <h3>{title}</h3>
      <span>主抽</span><strong>{formatCount(counts.main_draws)}</strong>
      <span>赠送抽</span><strong>{formatCount(counts.bonus_draws)}</strong>
      <span>总抽</span><strong>{formatCount(counts.total_draws)}</strong>
      <span>直接赠送角色</span><strong>{formatCount(counts.granted_characters)}</strong>
      <span>明细事件数</span><strong>{formatCount(counts.trace_events)}</strong>
    </section>)}
    <p>首次赠送抽取：{trigger(value.next_triggers.first_bonus_main_draw)}</p>
    <p>下一次周期赠送：{trigger(value.next_triggers.periodic_grant_main_draw)}</p>
  </div>;
}
