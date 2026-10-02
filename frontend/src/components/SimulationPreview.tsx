import type { SimulationPreview as PreviewResult } from "../api/types";

interface Props { value: PreviewResult | null; }

export function SimulationPreview({ value }: Props) {
  if (!value) return <p className="muted">检查输入后显示本次模拟的确定性计数预览。</p>;
  const { per_trial: each, total } = value.counts;
  return <div className="readonly-summary" aria-label="模拟预览">
    <span>规则</span><strong>{value.rule_source.name} · 修订 {value.rule_source.revision}</strong>
    <span>角色池</span><strong>{value.pool_source.name} · 修订 {value.pool_source.revision}</strong>
    <span>每轮主抽 / 赠送抽 / 总抽数</span><strong>{each.main_draws} / {each.bonus_draws} / {each.total_draws}</strong>
    <span>全实验主抽 / 赠送抽 / 总抽数</span><strong>{total.main_draws} / {total.bonus_draws} / {total.total_draws}</strong>
    <span>直接赠送角色 / Trace事件</span><strong>{total.granted_characters} / {total.trace_events}</strong>
    <span>下一次周期赠送位置</span><strong>{value.next_triggers.periodic_grant_main_draw ?? "未启用"}</strong>
    {value.next_triggers.first_bonus_main_draw !== null && <><span>首次赠送位置</span><strong>{value.next_triggers.first_bonus_main_draw}</strong></>}
  </div>;
}
