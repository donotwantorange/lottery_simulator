import type { InitialContext, ExperimentParameters, PoolDocument, RuleDocument } from "../api/types";

interface Props {
  rule: RuleDocument;
  pool: PoolDocument;
  value: ExperimentParameters;
  savedContext: InitialContext | null;
  onChange(value: ExperimentParameters): void;
  onConfirm(context: InitialContext): void;
}

export function currentInitialContext(rule: RuleDocument, pool: PoolDocument): InitialContext {
  const highest = [...rule.rarities].sort((a, b) => b.rank - a.rank)[0];
  const firstUp = (pool.rarity_pools.find((item) => item.rarity_id === highest?.id)?.characters ?? [])
    .find((character) => character.is_up)?.id ?? null;
  const bigTarget = rule.big_pity.target === "first_up" ? firstUp : pool.mechanism_targets.big_pity ?? null;
  return { rule_id: rule.id, rarity_ids: [...rule.rarities].sort((a, b) => a.rank - b.rank).map((item) => item.id),
    big_mode: rule.big_pity.enabled ? rule.big_pity.after_obtain : null, big_target_id: rule.big_pity.enabled ? bigTarget : null };
}

function sameContext(a: InitialContext | null, b: InitialContext) {
  return Boolean(a && a.rule_id === b.rule_id && a.big_mode === b.big_mode && a.big_target_id === b.big_target_id
    && a.rarity_ids.length === b.rarity_ids.length && a.rarity_ids.every((id, index) => id === b.rarity_ids[index]));
}

export function InitialConditions({ rule, pool, value, savedContext, onChange, onConfirm }: Props) {
  const context = currentInitialContext(rule, pool);
  const targetName = (id: string | null) => pool.rarity_pools.flatMap((item) => item.characters).find((character) => character.id === id)?.name ?? "未解析";
  const targetChanged = savedContext?.big_target_id !== context.big_target_id;
  const nonzero = value.initial_main_draws !== "0" || Object.values(value.initial_small_pity).some((count) => count !== "0")
    || value.initial_big_pity.target_obtained || value.initial_big_pity.misses !== "0";
  const contextChanged = savedContext ? !sameContext(savedContext, context) : nonzero;
  const tracked = [...rule.rarities].sort((a, b) => a.rank - b.rank).filter((item) => item.soft_enabled || item.hard_enabled);
  const trackedIds = new Set(tracked.map((item) => item.id));
  const staleSmallPity = Object.entries(value.initial_small_pity).filter(([id]) => !trackedIds.has(id));
  const disabledBigState = !rule.big_pity.enabled && (value.initial_big_pity.target_obtained || value.initial_big_pity.misses !== "0");
  const bigEnabled = rule.big_pity.enabled;
  const update = (values: Partial<ExperimentParameters>) => onChange({ ...value, ...values });
  return <>
    {nonzero && <p className="muted">当前非零初始状态：H={value.initial_main_draws}；小保底 {tracked.map((item) => `${item.name} ${value.initial_small_pity[item.id] ?? "0"}`).join("、") || "无"}；大保底目标{value.initial_big_pity.target_obtained ? "已获得" : "未获得"}。</p>}
    {contextChanged && <div role="status" className="import-preview">
      <p>初始条件上下文已变化{targetChanged ? `：目标从“${targetName(savedContext?.big_target_id ?? null)}”变为“${targetName(context.big_target_id)}”` : "（规则、稀有度顺序或大保底模式变化）"}。请确认并重新校验。</p>
      <button type="button" onClick={() => onConfirm(context)}>确认使用当前上下文</button>
    </div>}
    <details className="position-values">
    <summary>高级：初始条件</summary>
    <p className="muted">历史抽数H表示开始前已完成的主池抽数。非零初始状态会按当前规则和目标校验。</p>
    <div className="field-grid">
      <label>历史累计主抽数<input inputMode="numeric" value={value.initial_main_draws} onChange={(event) => update({ initial_main_draws: event.target.value })} /></label>
      {tracked.map((rarity) => <label key={rarity.id}>{rarity.name}未获得计数<input inputMode="numeric" value={value.initial_small_pity[rarity.id] ?? "0"}
        onChange={(event) => update({ initial_small_pity: { ...value.initial_small_pity, [rarity.id]: event.target.value } })} /></label>)}
      {bigEnabled ? <>
        <label className="inline-check"><input type="checkbox" disabled={rule.big_pity.after_obtain === "reset_after_obtain" && !value.initial_big_pity.target_obtained} checked={value.initial_big_pity.target_obtained}
          onChange={(event) => update({ initial_big_pity: { ...value.initial_big_pity, target_obtained: event.target.checked,
            misses: rule.big_pity.after_obtain === "disable_after_obtain" && event.target.checked ? "0" : value.initial_big_pity.misses } })} />历史已获得大保底目标“{targetName(context.big_target_id)}”</label>
        {rule.big_pity.after_obtain === "reset_after_obtain" && <p className="muted">循环模式不能设置历史已获得目标标记。</p>}
        <label>大保底未命中计数<input inputMode="numeric" disabled={rule.big_pity.after_obtain === "disable_after_obtain"}
          value={rule.big_pity.after_obtain === "disable_after_obtain" ? (value.initial_big_pity.target_obtained ? "0" : value.initial_main_draws) : value.initial_big_pity.misses}
          onChange={(event) => update({ initial_big_pity: { ...value.initial_big_pity, misses: event.target.value } })} /></label>
      </> : <div><p className="muted">大保底已关闭，但已载入的初始标记仍会校验。清除它们后才能提交。</p>{disabledBigState && <button type="button" onClick={() => update({ initial_big_pity: { target_obtained: false, misses: "0" } })}>清除已关闭大保底状态</button>}</div>}
      {staleSmallPity.map(([id, count]) => <p key={id} className="muted">存在当前规则未使用的初始计数（{id}: {count}）。
        <button type="button" onClick={() => { const next = { ...value.initial_small_pity }; delete next[id]; update({ initial_small_pity: next }); }}>移除</button></p>)}
    </div>
    </details>
  </>;
}
