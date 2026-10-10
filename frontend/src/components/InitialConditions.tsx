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
  const targetName = (id: string | null) => id === null ? "未设置" : pool.rarity_pools.flatMap((item) => item.characters).find((character) => character.id === id)?.name ?? `原目标已不在当前名单（ID：${id}）`;
  const targetChanged = savedContext !== null && savedContext.big_target_id !== context.big_target_id;
  const nonzero = value.initial_main_draws !== "0" || Object.values(value.initial_small_pity).some((count) => count !== "0")
    || value.initial_big_pity.target_obtained || value.initial_big_pity.misses !== "0";
  const contextChanged = savedContext ? !sameContext(savedContext, context) : nonzero;
  const tracked = [...rule.rarities].sort((a, b) => a.rank - b.rank).filter((item) => item.soft_enabled || item.hard_enabled);
  const rarityName = (id: string, fallback: string) => pool.rarity_labels[id] || fallback;
  const trackedIds = new Set(tracked.map((item) => item.id));
  const knownIds = new Set(rule.rarities.map((item) => item.id));
  const staleSmallPity = Object.entries(value.initial_small_pity).filter(([id, count]) => !knownIds.has(id) || (!trackedIds.has(id) && count !== "0"));
  const disabledBigState = !rule.big_pity.enabled && (value.initial_big_pity.target_obtained || value.initial_big_pity.misses !== "0");
  const cycleObtained = rule.big_pity.enabled && rule.big_pity.after_obtain === "reset_after_obtain" && value.initial_big_pity.target_obtained;
  const disabledMisses = rule.big_pity.enabled && rule.big_pity.after_obtain === "disable_after_obtain" && value.initial_big_pity.misses !== "0";
  const unresolved = staleSmallPity.length > 0 || disabledBigState || cycleObtained || disabledMisses;
  const bigEnabled = rule.big_pity.enabled;
  const update = (values: Partial<ExperimentParameters>) => onChange({ ...value, ...values });
  return <>
    {nonzero && <p className="muted">当前非零初始状态：历史主抽 {value.initial_main_draws}；小保底 {tracked.map((item) => `${rarityName(item.id, item.name)} ${value.initial_small_pity[item.id] ?? "0"}`).join("、") || "无"}；大保底目标{value.initial_big_pity.target_obtained ? "已获得" : "未获得"}。</p>}
    {contextChanged && <div role="status" className="import-preview">
      <p>{savedContext === null ? "请确认这些初始条件对应当前规则和目标。" : targetChanged ? `目标从“${targetName(savedContext.big_target_id)}”变为“${targetName(context.big_target_id)}”；请核对已有初始状态的含义。` : "规则、稀有度顺序或大保底模式变化；请核对已有初始状态。"}</p>
      <button type="button" onClick={() => onConfirm(context)}>确认这些初始条件适用于当前规则</button>
    </div>}
    {unresolved && <div className="import-preview" role="alert"><p>有待处理设置：当前规则无法使用以下初始状态。请修正或明确清除后再预览、保存。</p>
      {staleSmallPity.map(([id, count]) => <p key={id}>{knownIds.has(id) ? `${rarityName(id, id)}的保底已关闭，非零计数 ${count} 当前不适用。` : `旧档位 ${id} 已不在当前规则中，计数 ${count} 当前不适用。`}<button type="button" onClick={() => { const next = { ...value.initial_small_pity }; delete next[id]; update({ initial_small_pity: next }); }}>清除这项旧计数</button></p>)}
      {disabledBigState && <p>大保底已关闭，旧目标标记或非零计数当前不适用。<button type="button" onClick={() => update({ initial_big_pity: { target_obtained: false, misses: "0" } })}>清除旧大保底状态</button></p>}
      {cycleObtained && <p>循环模式只使用连续未命中次数，旧的“已获得目标”标记不适用。<button type="button" onClick={() => update({ initial_big_pity: { ...value.initial_big_pity, target_obtained: false } })}>清除旧目标标记</button></p>}
      {disabledMisses && <p>首次命中后关闭模式的计数由历史主抽推导，旧的手填未命中数不适用。<button type="button" onClick={() => update({ initial_big_pity: { ...value.initial_big_pity, misses: "0" } })}>清除旧未命中数</button></p>}
    </div>}
    <details className="position-values" id="experiment-initial-details" tabIndex={-1}>
    <summary>高级：初始条件</summary>
    <p className="muted">历史抽数 H 是本次开始前已完成的主池抽数，不含赠送抽，也不是连续未出高档次数。非零初始状态会按当前规则和目标校验。</p>
    <div className="field-grid">
      <label>历史累计主抽数<input id="experiment-initial-main-draws" inputMode="numeric" value={value.initial_main_draws} onChange={(event) => update({ initial_main_draws: event.target.value })} /></label>
      {tracked.map((rarity) => <label key={rarity.id}>连续未抽到{rarityName(rarity.id, rarity.name)}或更高的主抽数<input id={`experiment-small-${rarity.id}`} inputMode="numeric" value={value.initial_small_pity[rarity.id] ?? "0"}
        onChange={(event) => update({ initial_small_pity: { ...value.initial_small_pity, [rarity.id]: event.target.value } })} /></label>)}
      {tracked.length > 0 && <p className="muted">抽到本档或更高时计数归零；0 表示下一抽从第 1 抽概率开始。</p>}
      {bigEnabled ? <>
        {rule.big_pity.after_obtain === "disable_after_obtain" ? <>
          <label className="inline-check"><input id="experiment-big-obtained" type="checkbox" checked={value.initial_big_pity.target_obtained}
            onChange={(event) => update({ initial_big_pity: { ...value.initial_big_pity, target_obtained: event.target.checked } })} />历史已获得大保底目标“{targetName(context.big_target_id)}”</label>
          <p className="muted">{value.initial_big_pity.target_obtained ? "本轮大保底不再生效。" : `尚未获得目标；计数由历史主抽数 ${value.initial_main_draws} 推导。`}</p>
        </> : <>
          <label>当前连续未命中大保底目标“{targetName(context.big_target_id)}”的主抽数<input id="experiment-big-misses" inputMode="numeric" value={value.initial_big_pity.misses}
            onChange={(event) => update({ initial_big_pity: { ...value.initial_big_pity, misses: event.target.value } })} /></label>
          <p className="muted">循环模式只使用当前连续未命中次数，命中后重新计数。</p>
        </>}
      </> : <p className="muted">大保底未启用。</p>}
    </div>
    </details>
  </>;
}
