import { useCallback, useEffect, useMemo, useState } from "react";
import type { RuleDocument, RuleRarityDocument } from "../api/types";

interface Props {
  value: RuleDocument;
  onChange(value: RuleDocument): void;
  structureLocked: boolean;
  disabled?: boolean;
  onValidityChange?(valid: boolean): void;
}

interface NumberFieldProps {
  id: string;
  label: string;
  value: number;
  min?: number;
  max?: number;
  integer?: boolean;
  positive?: boolean;
  unit?: "percent" | "points";
  disabled?: boolean;
  onValidity(id: string, valid: boolean): void;
  onCommit(value: number): void;
  hint?: string;
}

function orderedNamesValid(rarities: RuleRarityDocument[]) {
  const names = rarities.map((item) => item.name.trim());
  return names.every(Boolean) && new Set(names).size === names.length;
}

const safeCount = (value: number, min = 1) => Number.isSafeInteger(value) && value >= min;

function NumberField({ id, label, value, min = 0, max, integer = false, positive = false, unit, disabled, onValidity, onCommit, hint }: NumberFieldProps) {
  const formatted = unit ? String(value * 100) : String(value);
  const [text, setText] = useState(formatted);
  const [error, setError] = useState("");
  useEffect(() => { setText(formatted); setError(""); onValidity(id, true); }, [formatted, disabled, id, onValidity]);
  function commit() {
    const raw = text.trim();
    const parsed = Number(raw);
    const next = unit ? parsed / 100 : parsed;
    if (!/^[+]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(raw) || !Number.isFinite(parsed) || (integer && (!Number.isSafeInteger(parsed) || !Number.isInteger(parsed))) || parsed < min || (positive && parsed <= 0) || (max !== undefined && parsed > max)) {
      setError(integer ? "请输入范围内的安全整数。" : positive ? "请输入大于0的有限数值。" : `请输入${min}至${max ?? "有限范围"}之间的有限数值。`);
      onValidity(id, false);
      return;
    }
    setError("");
    onCommit(next);
    onValidity(id, true);
  }
  return <label>{label}<input type="text" inputMode="decimal" aria-label={label} disabled={disabled} value={text}
    aria-invalid={Boolean(error)} onChange={(event) => { setText(event.target.value); setError(""); onValidity(id, false); }} onBlur={commit} />
    {error && <small className="form-error" role="alert">{error}</small>}
    {hint && <small className="muted">{hint}</small>}
  </label>;
}

const defaultRarity = (id: string, rank: number): RuleRarityDocument => ({
  id, name: "新稀有度", rank, base_probability: 0, soft_enabled: false, soft_start: 1,
  soft_step: 0, hard_enabled: false, hard_pity: 1,
});

export function RuleEditor({ value, onChange, structureLocked, disabled = false, onValidityChange }: Props) {
  const [validity, setValidity] = useState<Record<string, boolean>>({});
  const setValid = useCallback((id: string, valid: boolean) => setValidity((current) => current[id] === valid ? current : { ...current, [id]: valid }), []);
  const namesValid = orderedNamesValid(value.rarities);
  const bonusStructureValid = !value.bonus.enabled || (value.bonus.rarities.length === value.rarities.length && value.rarities.every((rarity) => {
    const bonus = value.bonus.rarities.find((item) => item.id === rarity.id);
    return Boolean(bonus && bonus.rank === rarity.rank);
  }));
  const locked = disabled || structureLocked;
  const orderedRarities = useMemo(() => [...value.rarities].sort((a, b) => a.rank - b.rank), [value.rarities]);
  const softExample = orderedRarities.find((item) => item.soft_enabled);
  const softExampleProbability = softExample ? Math.min(100, (softExample.base_probability + softExample.soft_step) * 100) : undefined;
  const sum = useMemo(() => value.rarities.reduce((total, item) => total + item.base_probability, 0), [value.rarities]);
  const bonusSum = useMemo(() => value.bonus.rarities.reduce((total, item) => total + item.base_probability, 0), [value.bonus.rarities]);
  const probabilitiesValid = [...value.rarities, ...value.bonus.rarities].every((item) => Number.isFinite(item.base_probability) && item.base_probability >= 0 && item.base_probability <= 1 && Number.isFinite(item.soft_step) && item.soft_step >= 0)
    && value.rarities.every((item) => !item.soft_enabled || item.soft_step > 0)
    && (!value.bonus.enabled || value.bonus.rarities.every((item) => !item.soft_enabled || item.soft_step > 0));
  const countsValid = [...value.rarities, ...value.bonus.rarities].every((item) => safeCount(item.rank, 0) && safeCount(item.soft_start) && safeCount(item.hard_pity))
    && safeCount(value.big_pity.hard_pity) && safeCount(value.bonus.at_main_draw) && safeCount(value.bonus.draws)
    && safeCount(value.grant.period) && safeCount(value.grant.quantity);
  const sumsValid = Math.abs(sum - 1) <= 1e-12 && (!value.bonus.enabled || Math.abs(bonusSum - 1) <= 1e-12);
  useEffect(() => onValidityChange?.(Object.values(validity).every(Boolean) && namesValid && bonusStructureValid && probabilitiesValid && countsValid && sumsValid), [onValidityChange, validity, namesValid, bonusStructureValid, probabilitiesValid, countsValid, sumsValid]);
  const change = (update: (draft: RuleDocument) => void) => {
    const next = structuredClone(value);
    update(next);
    onChange(next);
  };
  function updateRarity(id: string, update: (rarity: RuleRarityDocument) => void) {
    change((draft) => {
      const rarity = draft.rarities.find((item) => item.id === id)!;
      update(rarity);
    });
  }
  function reorder(id: string, direction: -1 | 1) {
    change((draft) => {
      const rarities = [...draft.rarities].sort((a, b) => a.rank - b.rank);
      const index = rarities.findIndex((item) => item.id === id);
      const target = index + direction;
      if (target < 0 || target >= rarities.length) return;
      [rarities[index], rarities[target]] = [rarities[target], rarities[index]];
      rarities.forEach((item, rank) => { item.rank = rank; });
      draft.rarities = rarities;
      if (draft.bonus.enabled) {
        const bonusById = new Map(draft.bonus.rarities.map((item) => [item.id, item]));
        draft.bonus.rarities = rarities.map((main) => ({ ...(bonusById.get(main.id) ?? main), rank: main.rank }));
      }
    });
  }
  function addRarity() {
    const id = crypto.randomUUID();
    change((draft) => {
      const rarity = defaultRarity(id, Math.max(-1, ...draft.rarities.map((item) => item.rank)) + 1);
      let suffix = draft.rarities.length + 1;
      while (draft.rarities.some((item) => item.name === `新稀有度${suffix}`)) suffix++;
      rarity.name = `新稀有度${suffix}`;
      draft.rarities.push(rarity);
      if (draft.bonus.enabled) draft.bonus.rarities.push({ ...rarity });
    });
  }
  function removeRarity(id: string) {
    change((draft) => {
      draft.rarities = [...draft.rarities].sort((a, b) => a.rank - b.rank).filter((item) => item.id !== id).map((item, rank) => ({ ...item, rank }));
      if (draft.bonus.enabled) {
        const bonusById = new Map(draft.bonus.rarities.filter((item) => item.id !== id).map((item) => [item.id, item]));
        draft.bonus.rarities = draft.rarities.map((main) => ({ ...(bonusById.get(main.id) ?? main), rank: main.rank }));
      }
    });
    setValidity((current) => Object.fromEntries(Object.entries(current).filter(([key]) => !key.includes(id))));
  }
  function changeBonus(update: (bonus: RuleDocument["bonus"]) => void) { change((draft) => update(draft.bonus)); }
  function field(id: string, label: string, current: number, assign: (n: number) => void, options: Omit<NumberFieldProps, "id" | "label" | "value" | "onValidity" | "onCommit"> = {}) {
    return <NumberField key={id} id={id} label={label} value={current} disabled={disabled} onValidity={setValid} onCommit={assign} {...options} />;
  }

  return <div className="stack-form">
    {structureLocked && <p className="muted">此规则已有引用，不能增删或调整稀有度结构；请复制为新规则后修改。</p>}
    <section className="editor-section"><h3>稀有度及高低顺序</h3>
      <p className="muted">从上到下，稀有度等级逐渐升高；最上方最低，最下方最高。顺序决定保底中的高低比较，基础概率另行填写。</p>
      {orderedRarities.map((rarity, index) => <div className="field-grid" key={rarity.id}>
        <label>稀有度名称{orderedRarities.length === 1 ? <small className="muted">唯一稀有度</small> : index === 0 ? <small className="muted">最低稀有度</small> : index === orderedRarities.length - 1 ? <small className="muted">最高稀有度</small> : null}<input disabled={disabled} value={rarity.name} onChange={(event) => updateRarity(rarity.id, (item) => { item.name = event.target.value; })} /></label>
        <div className="button-row"><button type="button" aria-label={`${rarity.name}上移`} disabled={locked || index === 0} onClick={() => reorder(rarity.id, -1)}>上移</button><button type="button" aria-label={`${rarity.name}下移`} disabled={locked || index === value.rarities.length - 1} onClick={() => reorder(rarity.id, 1)}>下移</button><button type="button" disabled={locked || value.rarities.length <= 1} onClick={() => removeRarity(rarity.id)}>删除稀有度</button></div>
      </div>)}
      <p className="muted" role="status">主池基础概率合计：{(sum * 100).toFixed(4)}%{Math.abs(sum - 1) > 1e-12 ? "，总和必须为100%。" : "，合计正确。"}{!namesValid && "稀有度名称不能为空且不能重复。"}{!bonusStructureValid && "启用首次赠送时，稀有度ID及顺序必须与主规则一致。"}{!countsValid && "存在超出安全整数范围或非正整数的抽数，无法安全保存。"}{!probabilitiesValid && "概率必须是0至100%之间的有限数值，启用软保底时增幅必须大于0。"}</p>
      <button type="button" className="secondary-button" disabled={locked} onClick={addRarity}>添加稀有度</button>
    </section>
    <section className="editor-section"><h3>基础概率与小保底</h3>
      <p className="muted">基础概率是每次常规抽取的初始概率，各档合计100%；保底触发后概率可能改变。软保底从起点抽次开始增加；增幅单位是百分点，按基础概率直接相加而不是按比例增加。{softExample && softExampleProbability !== undefined ? `当前${softExample.name}基础概率${(softExample.base_probability * 100).toFixed(3)}%，每抽增加${(softExample.soft_step * 100).toFixed(3)}个百分点，示例：${(softExample.base_probability * 100).toFixed(3)}% + ${(softExample.soft_step * 100).toFixed(3)}个百分点 = ${softExampleProbability.toFixed(3)}%（最高100%）。起点为第${softExample.soft_start}抽。` : "起点和增幅按各档参数计算。"}关闭的保底参数保留但不生效。</p>
      {orderedRarities.map((rarity) => <div className="field-grid" key={rarity.id}>
        {field(`main:${rarity.id}:probability`, `${rarity.name}基础概率（百分比）`, rarity.base_probability, (n) => updateRarity(rarity.id, (item) => { item.base_probability = n; }), { unit: "percent", max: 100 })}
        <label className="inline-check"><input type="checkbox" disabled={disabled} checked={rarity.soft_enabled} onChange={(event) => { if (event.target.checked && rarity.soft_step <= 0) setValid(`main:${rarity.id}:soft-step`, false); updateRarity(rarity.id, (item) => { item.soft_enabled = event.target.checked; }); }} />启用软保底</label>
        {field(`main:${rarity.id}:soft-start`, `${rarity.name}软保底起点`, rarity.soft_start, (n) => updateRarity(rarity.id, (item) => { item.soft_start = n; }), { min: 1, integer: true, disabled: disabled || !rarity.soft_enabled })}
        {rarity.soft_enabled && <p className="muted">连续未抽到该档或更高档时，第{rarity.soft_start}抽开始按百分点增加概率。</p>}
        {field(`main:${rarity.id}:soft-step`, `${rarity.name}每抽增幅（百分点）`, rarity.soft_step, (n) => updateRarity(rarity.id, (item) => { item.soft_step = n; }), { unit: "points", positive: rarity.soft_enabled, disabled: disabled || !rarity.soft_enabled })}
        <label className="inline-check"><input type="checkbox" disabled={disabled} checked={rarity.hard_enabled} onChange={(event) => updateRarity(rarity.id, (item) => { item.hard_enabled = event.target.checked; })} />启用硬保底</label>
        {field(`main:${rarity.id}:hard-pity`, `${rarity.name}硬保底抽数`, rarity.hard_pity, (n) => updateRarity(rarity.id, (item) => { item.hard_pity = n; }), { min: 1, integer: true, disabled: disabled || !rarity.hard_enabled })}
        {rarity.hard_enabled && <p className="muted">连续{rarity.hard_pity - 1}次未抽到该档或更高档时，第{rarity.hard_pity}次保证获得该档或更高档；命中后重新计数。</p>}
      </div>)}
    </section>
    <section className="editor-section"><h3>大保底</h3>
      <p className="muted">只统计主池抽中目标：连续{value.big_pity.hard_pity - 1}次主抽未中，第{value.big_pity.hard_pity}次主抽必得目标；赠送抽和直接赠送不改变大保底。</p>
      <label className="inline-check"><input type="checkbox" disabled={disabled} checked={value.big_pity.enabled} onChange={(event) => change((draft) => { draft.big_pity.enabled = event.target.checked; })} />启用大保底</label>
      {!value.big_pity.enabled && <p className="muted">大保底已关闭，抽数和获得后模式不生效。</p>}
      {field("big-pity:count", "大保底抽数", value.big_pity.hard_pity, (n) => change((draft) => { draft.big_pity.hard_pity = n; }), { min: 1, integer: true, disabled: disabled || !value.big_pity.enabled })}
      <label>目标<select disabled={disabled || !value.big_pity.enabled} value={value.big_pity.target} onChange={(event) => change((draft) => { draft.big_pity.target = event.target.value as "first_up"; })}><option value="first_up">最高稀有度中排序第一的UP（由绑定池解析）</option></select></label>
      <label>获得目标后<select disabled={disabled || !value.big_pity.enabled} value={value.big_pity.after_obtain} onChange={(event) => change((draft) => { draft.big_pity.after_obtain = event.target.value as "disable_after_obtain" | "reset_after_obtain"; })}><option value="disable_after_obtain">本轮主池抽中目标后关闭</option><option value="reset_after_obtain">每次主池抽中目标后重新计数</option></select></label>
      {value.big_pity.enabled && <p className="muted">{value.big_pity.after_obtain === "disable_after_obtain" ? "主池抽中目标后，本轮后续大保底关闭；下一轮按初始条件重新开始。" : "主池抽中目标后，未中计数归零，大保底继续有效。"}</p>}
    </section>
    <section className="editor-section"><h3>首次赠送池</h3>
      <p className="muted">主抽累计跨过第{value.bonus.at_main_draw}抽时，额外执行{value.bonus.draws}次赠送抽。赠送池有独立概率和保底，不推进主池抽数或保底；已越过触发位置的初始历史不会补发。</p>
      <label className="inline-check"><input type="checkbox" disabled={disabled} checked={value.bonus.enabled} onChange={(event) => change((draft) => { draft.bonus.enabled = event.target.checked; if (event.target.checked) { const existing = new Map(draft.bonus.rarities.map((item) => [item.id, item])); draft.bonus.rarities = draft.rarities.map((main) => ({ ...(existing.get(main.id) ?? { ...main, base_probability: 0 }), rank: main.rank })); } })} />启用首次赠送</label>
      {!value.bonus.enabled && <p className="muted">首次赠送已关闭，触发位置、赠送抽数和该池概率不生效。</p>}
      {field("bonus:at", "触发主抽位置", value.bonus.at_main_draw, (n) => changeBonus((bonus) => { bonus.at_main_draw = n; }), { min: 1, integer: true, disabled: disabled || !value.bonus.enabled })}
      {field("bonus:draws", "赠送抽数", value.bonus.draws, (n) => changeBonus((bonus) => { bonus.draws = n; }), { min: 1, integer: true, disabled: disabled || !value.bonus.enabled })}
      {value.bonus.rarities.map((rarity) => <div className="field-grid" key={rarity.id}>
        {field(`bonus:${rarity.id}:probability`, `${rarity.name}赠送池概率（百分比）`, rarity.base_probability, (n) => changeBonus((bonus) => { const item = bonus.rarities.find((entry) => entry.id === rarity.id)!; item.base_probability = n; }), { unit: "percent", max: 100, disabled: disabled || !value.bonus.enabled })}
        <label className="inline-check"><input type="checkbox" disabled={disabled || !value.bonus.enabled} checked={rarity.soft_enabled} onChange={(event) => { if (event.target.checked && rarity.soft_step <= 0) setValid(`bonus:${rarity.id}:soft-step`, false); changeBonus((bonus) => { bonus.rarities.find((item) => item.id === rarity.id)!.soft_enabled = event.target.checked; }); }} />启用赠送池软保底</label>
        {field(`bonus:${rarity.id}:soft-start`, `${rarity.name}赠送池软保底起点`, rarity.soft_start, (n) => changeBonus((bonus) => { bonus.rarities.find((item) => item.id === rarity.id)!.soft_start = n; }), { min: 1, integer: true, disabled: disabled || !value.bonus.enabled || !rarity.soft_enabled })}
        {field(`bonus:${rarity.id}:soft-step`, `${rarity.name}赠送池每抽增幅（百分点）`, rarity.soft_step, (n) => changeBonus((bonus) => { bonus.rarities.find((item) => item.id === rarity.id)!.soft_step = n; }), { unit: "points", positive: rarity.soft_enabled, disabled: disabled || !value.bonus.enabled || !rarity.soft_enabled })}
        <label className="inline-check"><input type="checkbox" disabled={disabled || !value.bonus.enabled} checked={rarity.hard_enabled} onChange={(event) => changeBonus((bonus) => { bonus.rarities.find((item) => item.id === rarity.id)!.hard_enabled = event.target.checked; })} />启用赠送池硬保底</label>
        {field(`bonus:${rarity.id}:hard-pity`, `${rarity.name}赠送池硬保底抽数`, rarity.hard_pity, (n) => changeBonus((bonus) => { bonus.rarities.find((item) => item.id === rarity.id)!.hard_pity = n; }), { min: 1, integer: true, disabled: disabled || !value.bonus.enabled || !rarity.hard_enabled })}
      </div>)}
      <p className="muted" role="status">赠送池基础概率合计：{(bonusSum * 100).toFixed(4)}%{value.bonus.enabled && Math.abs(bonusSum - 1) > 1e-12 ? "，总和必须为100%。" : "。"}</p>
    </section>
    <section className="editor-section"><h3>周期直接赠送</h3>
      <p className="muted">每累计{value.grant.period}次主抽直接获得{value.grant.quantity}名角色，不执行抽取，不增加抽数或奖励，也不改变主池保底。自动UP目标按稀有度从高到低寻找第一个UP；指定目标使用绑定池选择的角色。</p>
      <label className="inline-check"><input type="checkbox" disabled={disabled} checked={value.grant.enabled} onChange={(event) => change((draft) => { draft.grant.enabled = event.target.checked; })} />启用周期直接赠送</label>
      {!value.grant.enabled && <p className="muted">周期直接赠送已关闭，周期、数量和目标不生效。</p>}
      {field("grant:period", "触发周期（主抽）", value.grant.period, (n) => change((draft) => { draft.grant.period = n; }), { min: 1, integer: true, disabled: disabled || !value.grant.enabled })}
      {field("grant:quantity", "每次直接赠送数量", value.grant.quantity, (n) => change((draft) => { draft.grant.quantity = n; }), { min: 1, integer: true, disabled: disabled || !value.grant.enabled })}
      <label>赠送目标<select disabled={disabled || !value.grant.enabled} value={value.grant.target} onChange={(event) => change((draft) => { draft.grant.target = event.target.value as "first_up" | "pool_selected"; })}><option value="first_up">等级最高档中排序第一的UP（向低档回退）</option><option value="pool_selected">绑定池指定角色</option></select></label>
    </section>
    <section className="editor-section"><h3>规则说明摘要</h3><p className="muted">这里决定怎么抽。修改共享规则后，引用它的池在下一次模拟使用新设置。目标角色将在绑定池中解析。</p></section>
  </div>;
}
