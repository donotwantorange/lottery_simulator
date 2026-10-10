import { useEffect, useMemo, useState } from "react";
import type { RuleDocument, RuleRarityDocument } from "../api/types";
import { FormFeedback, ReadonlyValue, type FieldIssue } from "./FormFeedback";
import { useNumberDrafts, type NumberDraft } from "../hooks/useEditorDraft";

interface Props {
  value: RuleDocument;
  onChange(value: RuleDocument): void;
  structureLocked: boolean;
  disabled?: boolean;
  onValidityChange?(valid: boolean): void;
  onPendingChange?(pending: boolean): void;
  revealField?: string | null;
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
  draft?: NumberDraft;
  updateDraft(id: string, draft: NumberDraft): void;
  onCommit(value: number): void;
  hint?: string;
}

function orderedNamesValid(rarities: RuleRarityDocument[]) {
  const names = rarities.map((item) => item.name.trim());
  return names.every(Boolean) && new Set(names).size === names.length;
}

const safeCount = (value: number, min = 1) => Number.isSafeInteger(value) && value >= min;

function NumberField({ id, label, value, min = 0, max, integer = false, positive = false, unit, disabled, draft, updateDraft, onCommit, hint }: NumberFieldProps) {
  const formatted = unit ? String(value * 100) : String(value);
  const text = draft?.text ?? formatted;
  const error = draft?.error ?? "";
  function commit() {
    const raw = text.trim();
    const parsed = Number(raw);
    const next = unit ? parsed / 100 : parsed;
    if (!/^[+]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(raw) || !Number.isFinite(parsed) || (integer && (!Number.isSafeInteger(parsed) || !Number.isInteger(parsed))) || parsed < min || (positive && parsed <= 0) || (max !== undefined && parsed > max)) {
      updateDraft(id, { text, lastLegal: value, error: integer ? "请输入范围内的安全整数。" : positive ? "请输入大于0的有限数值。" : `请输入${min}至${max ?? "有限范围"}之间的有限数值。` });
      return;
    }
    updateDraft(id, { text, lastLegal: next, error: "" });
    onCommit(next);
  }
  return <label>{label}<input id={id} type="text" inputMode="decimal" aria-label={label} disabled={disabled} value={text}
    aria-invalid={Boolean(error)} onChange={(event) => updateDraft(id, { text: event.target.value, lastLegal: value, error: "请完成并修正此输入。" })} onBlur={commit} />
    {error && <small className="form-error" role="alert">{error}</small>}
    {hint && <small className="muted">{hint}</small>}
  </label>;
}

const defaultRarity = (id: string, rank: number): RuleRarityDocument => ({
  id, name: "新稀有度", rank, base_probability: 0, soft_enabled: false, soft_start: 1,
  soft_step: 0, hard_enabled: false, hard_pity: 1,
});

export function RuleEditor({ value, onChange, structureLocked, disabled = false, onValidityChange, onPendingChange, revealField }: Props) {
  const numberDrafts = useNumberDrafts();
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  useEffect(() => {
    if (!revealField) return;
    const prefix = revealField.startsWith("main:") ? revealField.split(":").slice(0, 2).join(":") :
      revealField.startsWith("bonus:") ? "bonus:" : revealField.startsWith("big-pity:") ? "big-pity:" : "grant:";
    setRevealed((current) => ({ ...current, [prefix]: true }));
  }, [revealField]);
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
  useEffect(() => onValidityChange?.(!numberDrafts.hasInvalid && namesValid && bonusStructureValid && probabilitiesValid && countsValid && sumsValid), [onValidityChange, numberDrafts.hasInvalid, namesValid, bonusStructureValid, probabilitiesValid, countsValid, sumsValid]);
  useEffect(() => onPendingChange?.(numberDrafts.hasInvalid), [onPendingChange, numberDrafts.hasInvalid]);
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
    numberDrafts.removeMatching(id);
  }
  function changeBonus(update: (bonus: RuleDocument["bonus"]) => void) { change((draft) => update(draft.bonus)); }
  function toggleBonus(enabled: boolean) {
    if (enabled) {
      const sameIds = value.bonus.rarities.length === value.rarities.length && value.rarities.every((rarity) => value.bonus.rarities.some((bonus) => bonus.id === rarity.id));
      if (!sameIds && !window.confirm("主池稀有度结构已变化。启用赠送池会按稀有度ID保留匹配项，并为新增档建立默认项；不匹配的旧档将移除。继续吗？")) return;
    }
    change((draft) => { draft.bonus.enabled = enabled; if (enabled) {
      const existing = new Map(draft.bonus.rarities.map((item) => [item.id, item]));
      draft.bonus.rarities = draft.rarities.map((main) => ({ ...(existing.get(main.id) ?? { ...main, base_probability: 0 }), rank: main.rank }));
    } });
  }
  function field(id: string, label: string, current: number, assign: (n: number) => void, options: Omit<NumberFieldProps, "id" | "label" | "value" | "draft" | "updateDraft" | "onCommit"> = {}) {
    return <NumberField key={id} id={id} label={label} value={current} disabled={disabled} draft={numberDrafts.fields[id]} updateDraft={numberDrafts.update} onCommit={assign} {...options} />;
  }
  function pending(prefix: string, visible: boolean) {
    const issues = Object.entries(numberDrafts.fields).filter(([id, draft]) => id.startsWith(prefix) && draft.error);
    if (visible || issues.length === 0) return null;
    return <div className="pending-settings"><p className="form-error">有未完成的参数修改（{issues.length}项）。</p>
      <button type="button" onClick={() => setRevealed((current) => ({ ...current, [prefix.startsWith("main:") ? prefix.split(":").slice(0, 2).join(":") : prefix.startsWith("bonus:") ? "bonus:" : prefix]: true }))}>展开修正</button>
      <button type="button" onClick={() => issues.forEach(([id]) => numberDrafts.discard(id))}>放弃未完成输入，恢复上次合法值</button></div>;
  }
  const issues: FieldIssue[] = Object.entries(numberDrafts.fields).filter(([, draft]) => draft.error).map(([id, draft]) => ({ id, label: id, message: draft.error, reveal: () => {
    const prefix = id.startsWith("main:") ? id.split(":").slice(0, 2).join(":") : id.startsWith("bonus:") ? "bonus:" : id.startsWith("big-pity:") ? "big-pity:" : "grant:";
    setRevealed((current) => ({ ...current, [prefix]: true }));
  } }));

  const rarityName = (id: string) => value.rarities.find((item) => item.id === id)?.name ?? id.slice(0, 8);
  const fieldNames: Record<string, string> = { probability: "基础概率", "soft-start": "软保底起点", "soft-step": "每抽增幅", "hard-pity": "硬保底抽数" };
  for (const issue of issues) {
    const [area, rarityId, fieldName] = issue.id.split(":");
    issue.label = area === "main" || area === "bonus" ? `${rarityName(rarityId)}${area === "bonus" ? "赠送池" : ""}${fieldNames[fieldName] ?? fieldName}` :
      area === "big-pity" ? "大保底抽数" : area === "grant" ? (rarityId === "period" ? "触发周期" : "赠送数量") : issue.id;
  }

  return <div className="stack-form">
    <FormFeedback issues={issues} />
    {structureLocked && <p className="muted">此规则已有引用，不能增删或调整稀有度结构；请复制为新规则后修改。</p>}
    <section className="editor-section"><h3>稀有度及高低顺序</h3>
      <p className="muted">从上到下，稀有度等级逐渐升高；最上方最低，最下方最高。顺序决定保底中的高低比较，基础概率另行填写。</p>
      {orderedRarities.map((rarity, index) => <div className="field-grid" key={rarity.id}>
        <p>{rarity.name} <small className="muted">{orderedRarities.length === 1 ? "唯一稀有度" : index === 0 ? "最低稀有度" : index === orderedRarities.length - 1 ? "最高稀有度" : `第${index + 1}档`}</small></p>
        {!structureLocked && <div className="button-row"><button type="button" aria-label={`${rarity.name}上移`} disabled={locked || index === 0} onClick={() => reorder(rarity.id, -1)}>上移</button><button type="button" aria-label={`${rarity.name}下移`} disabled={locked || index === value.rarities.length - 1} onClick={() => reorder(rarity.id, 1)}>下移</button><button type="button" disabled={locked || value.rarities.length <= 1} onClick={() => removeRarity(rarity.id)}>删除稀有度</button></div>}
      </div>)}
      <p className="muted" role="status">主池基础概率合计：{(sum * 100).toFixed(4)}%{Math.abs(sum - 1) > 1e-12 ? "，总和必须为100%。" : "，合计正确。"}{!namesValid && "稀有度名称不能为空且不能重复。"}{!bonusStructureValid && "启用首次赠送时，稀有度ID及顺序必须与主规则一致。"}{!countsValid && "存在超出安全整数范围或非正整数的抽数，无法安全保存。"}{!probabilitiesValid && "概率必须是0至100%之间的有限数值，启用软保底时增幅必须大于0。"}</p>
      {!structureLocked && <button type="button" className="secondary-button" disabled={locked} onClick={addRarity}>添加稀有度</button>}
    </section>
    <section className="editor-section"><h3>基础概率与小保底</h3>
      <p className="muted">基础概率是每次常规抽取的初始概率，各档合计100%；保底触发后概率可能改变。软保底增幅单位是百分点。{softExample && softExampleProbability !== undefined ? `当前${softExample.name}基础概率${(softExample.base_probability * 100).toFixed(3)}%，每抽增加${(softExample.soft_step * 100).toFixed(3)}个百分点，示例：${(softExample.base_probability * 100).toFixed(3)}% + ${(softExample.soft_step * 100).toFixed(3)}个百分点 = ${softExampleProbability.toFixed(3)}%（最高100%）。起点为第${softExample.soft_start}抽。实际概率还受可扣减低档概率及更高档机制约束。` : "启用后按起点和增幅计算。"}关闭的保底参数保留但不生效。</p>
      {orderedRarities.map((rarity) => <div className="field-grid" key={rarity.id}>
        <label>稀有度名称<input disabled={disabled} value={rarity.name} onChange={(event) => updateRarity(rarity.id, (item) => { item.name = event.target.value; })} /></label>
        {field(`main:${rarity.id}:probability`, `${rarity.name}基础概率（百分比）`, rarity.base_probability, (n) => updateRarity(rarity.id, (item) => { item.base_probability = n; }), { unit: "percent", max: 100 })}
        <label className="inline-check"><input type="checkbox" disabled={disabled} checked={rarity.soft_enabled} onChange={(event) => updateRarity(rarity.id, (item) => { item.soft_enabled = event.target.checked; })} />启用软保底</label>
        {pending(`main:${rarity.id}:soft-`, rarity.soft_enabled || !!revealed[`main:${rarity.id}`])}
        {(rarity.soft_enabled || revealed[`main:${rarity.id}`]) && field(`main:${rarity.id}:soft-start`, `${rarity.name}软保底起点`, rarity.soft_start, (n) => updateRarity(rarity.id, (item) => { item.soft_start = n; }), { min: 1, integer: true, disabled })}
        {rarity.soft_enabled && <p className="muted">连续未抽到该档或更高档时，第{rarity.soft_start}抽开始按百分点增加概率。</p>}
        {(rarity.soft_enabled || revealed[`main:${rarity.id}`]) && field(`main:${rarity.id}:soft-step`, `${rarity.name}每抽增幅（百分点）`, rarity.soft_step, (n) => updateRarity(rarity.id, (item) => { item.soft_step = n; }), { unit: "points", positive: rarity.soft_enabled, disabled })}
        <label className="inline-check"><input type="checkbox" disabled={disabled} checked={rarity.hard_enabled} onChange={(event) => updateRarity(rarity.id, (item) => { item.hard_enabled = event.target.checked; })} />启用硬保底</label>
        {pending(`main:${rarity.id}:hard-`, rarity.hard_enabled || !!revealed[`main:${rarity.id}`])}
        {(rarity.hard_enabled || revealed[`main:${rarity.id}`]) && field(`main:${rarity.id}:hard-pity`, `${rarity.name}硬保底抽数`, rarity.hard_pity, (n) => updateRarity(rarity.id, (item) => { item.hard_pity = n; }), { min: 1, integer: true, disabled })}
        {rarity.hard_enabled && <p className="muted">连续{rarity.hard_pity - 1}次未抽到该档或更高档时，第{rarity.hard_pity}次保证获得该档或更高档；命中后重新计数。</p>}
      </div>)}
    </section>
    <section className="editor-section"><h3>大保底</h3>
      <p className="muted">大保底只统计主池抽中目标；赠送抽和直接赠送不改变大保底。{value.big_pity.enabled && `连续${value.big_pity.hard_pity - 1}次主抽未中，第${value.big_pity.hard_pity}次主抽必得目标。`}</p>
      <label className="inline-check"><input type="checkbox" disabled={disabled} checked={value.big_pity.enabled} onChange={(event) => change((draft) => { draft.big_pity.enabled = event.target.checked; })} />启用大保底</label>
      {!value.big_pity.enabled && <p className="muted">大保底已关闭，抽数和获得后模式不生效。</p>}
      {pending("big-pity:", value.big_pity.enabled || !!revealed["big-pity:"])}
      {(value.big_pity.enabled || revealed["big-pity:"]) && <>{field("big-pity:count", "大保底抽数", value.big_pity.hard_pity, (n) => change((draft) => { draft.big_pity.hard_pity = n; }), { min: 1, integer: true, disabled })}
      <label>目标<select disabled={disabled || !value.big_pity.enabled} value={value.big_pity.target} onChange={(event) => change((draft) => { draft.big_pity.target = event.target.value as "first_up"; })}><option value="first_up">最高稀有度中排序第一的UP（由绑定池解析）</option></select></label>
      <label>获得目标后<select disabled={disabled || !value.big_pity.enabled} value={value.big_pity.after_obtain} onChange={(event) => change((draft) => { draft.big_pity.after_obtain = event.target.value as "disable_after_obtain" | "reset_after_obtain"; })}><option value="disable_after_obtain">本轮主池抽中目标后关闭</option><option value="reset_after_obtain">每次主池抽中目标后重新计数</option></select></label></>}
      {value.big_pity.enabled && <p className="muted">{value.big_pity.after_obtain === "disable_after_obtain" ? "主池抽中目标后，本轮后续大保底关闭；下一轮按初始条件重新开始。" : "主池抽中目标后，未中计数归零，大保底继续有效。"}</p>}
    </section>
    <section className="editor-section"><h3>首次赠送池</h3>
      <p className="muted">首次赠送池额外执行赠送抽，有独立概率和保底，不推进主池抽数或保底。{value.bonus.enabled && `主抽累计跨过第${value.bonus.at_main_draw}抽时赠送${value.bonus.draws}抽；已越过触发位置的初始历史不会补发。`}</p>
      <label className="inline-check"><input type="checkbox" disabled={disabled} checked={value.bonus.enabled} onChange={(event) => toggleBonus(event.target.checked)} />启用首次赠送</label>
      {!value.bonus.enabled && <p className="muted">首次赠送已关闭，触发位置、赠送抽数和该池概率不生效。</p>}
      {pending("bonus:", value.bonus.enabled || !!revealed["bonus:"])}
      {(value.bonus.enabled || revealed["bonus:"]) && <>{field("bonus:at", "触发主抽位置", value.bonus.at_main_draw, (n) => changeBonus((bonus) => { bonus.at_main_draw = n; }), { min: 1, integer: true, disabled: disabled || (!value.bonus.enabled && !revealed["bonus:"]) })}
      {field("bonus:draws", "赠送抽数", value.bonus.draws, (n) => changeBonus((bonus) => { bonus.draws = n; }), { min: 1, integer: true, disabled: disabled || (!value.bonus.enabled && !revealed["bonus:"]) })}
      {value.bonus.rarities.map((rarity) => <div className="field-grid" key={rarity.id}>
        {field(`bonus:${rarity.id}:probability`, `${rarity.name}赠送池概率（百分比）`, rarity.base_probability, (n) => changeBonus((bonus) => { const item = bonus.rarities.find((entry) => entry.id === rarity.id)!; item.base_probability = n; }), { unit: "percent", max: 100, disabled: disabled || (!value.bonus.enabled && !revealed["bonus:"]) })}
        <label className="inline-check"><input type="checkbox" disabled={disabled || !value.bonus.enabled} checked={rarity.soft_enabled} onChange={(event) => changeBonus((bonus) => { bonus.rarities.find((item) => item.id === rarity.id)!.soft_enabled = event.target.checked; })} />启用赠送池软保底</label>
        {pending(`bonus:${rarity.id}:soft-`, rarity.soft_enabled || !!revealed["bonus:"])}
        {(rarity.soft_enabled || revealed["bonus:"]) && field(`bonus:${rarity.id}:soft-start`, `${rarity.name}赠送池软保底起点`, rarity.soft_start, (n) => changeBonus((bonus) => { bonus.rarities.find((item) => item.id === rarity.id)!.soft_start = n; }), { min: 1, integer: true, disabled: disabled || (!revealed["bonus:"] && (!value.bonus.enabled || !rarity.soft_enabled)) })}
        {(rarity.soft_enabled || revealed["bonus:"]) && field(`bonus:${rarity.id}:soft-step`, `${rarity.name}赠送池每抽增幅（百分点）`, rarity.soft_step, (n) => changeBonus((bonus) => { bonus.rarities.find((item) => item.id === rarity.id)!.soft_step = n; }), { unit: "points", positive: rarity.soft_enabled, disabled: disabled || (!revealed["bonus:"] && (!value.bonus.enabled || !rarity.soft_enabled)) })}
        <label className="inline-check"><input type="checkbox" disabled={disabled || !value.bonus.enabled} checked={rarity.hard_enabled} onChange={(event) => changeBonus((bonus) => { bonus.rarities.find((item) => item.id === rarity.id)!.hard_enabled = event.target.checked; })} />启用赠送池硬保底</label>
        {pending(`bonus:${rarity.id}:hard-`, rarity.hard_enabled || !!revealed["bonus:"])}
        {(rarity.hard_enabled || revealed["bonus:"]) && field(`bonus:${rarity.id}:hard-pity`, `${rarity.name}赠送池硬保底抽数`, rarity.hard_pity, (n) => changeBonus((bonus) => { bonus.rarities.find((item) => item.id === rarity.id)!.hard_pity = n; }), { min: 1, integer: true, disabled: disabled || (!revealed["bonus:"] && (!value.bonus.enabled || !rarity.hard_enabled)) })}
      </div>)}
      </>}
      <p className="muted" role="status">赠送池基础概率合计：{(bonusSum * 100).toFixed(4)}%{value.bonus.enabled && Math.abs(bonusSum - 1) > 1e-12 ? "，总和必须为100%。" : "。"}</p>
    </section>
    <section className="editor-section"><h3>周期直接赠送</h3>
      <p className="muted">周期直接赠送不执行抽取，不增加抽数或奖励，也不改变主池保底。{value.grant.enabled && `每累计${value.grant.period}次主抽直接获得${value.grant.quantity}名角色。${value.grant.target === "first_up" ? "自动UP目标按稀有度从高到低寻找第一个UP。" : "指定目标使用绑定池选择的角色。"}`}</p>
      <label className="inline-check"><input type="checkbox" disabled={disabled} checked={value.grant.enabled} onChange={(event) => change((draft) => { draft.grant.enabled = event.target.checked; })} />启用周期直接赠送</label>
      {!value.grant.enabled && <p className="muted">周期直接赠送已关闭，周期、数量和目标不生效。</p>}
      {pending("grant:", value.grant.enabled || !!revealed["grant:"])}
      {(value.grant.enabled || revealed["grant:"]) && <>{field("grant:period", "触发周期（主抽）", value.grant.period, (n) => change((draft) => { draft.grant.period = n; }), { min: 1, integer: true, disabled: disabled || !value.grant.enabled })}
      {field("grant:quantity", "每次直接赠送数量", value.grant.quantity, (n) => change((draft) => { draft.grant.quantity = n; }), { min: 1, integer: true, disabled: disabled || !value.grant.enabled })}
      <label>赠送目标<select disabled={disabled || !value.grant.enabled} value={value.grant.target} onChange={(event) => change((draft) => { draft.grant.target = event.target.value as "first_up" | "pool_selected"; })}><option value="first_up">等级最高档中排序第一的UP（向低档回退）</option><option value="pool_selected">绑定池指定角色</option></select></label></>}
    </section>
    <section className="editor-section"><h3>规则说明摘要</h3><p className="muted">这里决定怎么抽。修改共享规则后，引用它的池在下一次模拟使用新设置。目标角色将在绑定池中解析。</p></section>
  </div>;
}

export function RuleReadOnly({ value }: { value: RuleDocument }) {
  const names = new Map(value.rarities.map((item) => [item.id, item.name]));
  return <div className="stack-form rule-readonly">
    <section className="editor-section"><h3>稀有度及高低顺序</h3>
      {[...value.rarities].sort((a, b) => a.rank - b.rank).map((rarity) => <div key={rarity.id} className="readonly-group">
        <h4>{rarity.name}</h4><ReadonlyValue label="基础概率" value={`${rarity.base_probability * 100}%`} />
        <ReadonlyValue label="软保底" value={rarity.soft_enabled ? `第${rarity.soft_start}抽起，每抽增加${rarity.soft_step * 100}个百分点` : "未启用"} />
        <ReadonlyValue label="硬保底" value={rarity.hard_enabled ? `第${rarity.hard_pity}抽获得本档或更高` : "未启用"} />
      </div>)}
    </section>
    <section className="editor-section"><h3>附加机制</h3>
      <ReadonlyValue label="大保底" value={value.big_pity.enabled ? `第${value.big_pity.hard_pity}次主抽必得目标；${value.big_pity.after_obtain === "reset_after_obtain" ? "命中后重新计数" : "本轮命中后关闭"}` : "未启用"} />
      <ReadonlyValue label="首次赠送池" value={value.bonus.enabled ? `第${value.bonus.at_main_draw}次主抽时赠送${value.bonus.draws}抽` : "未启用"} />
      <ReadonlyValue label="周期直接赠送" value={value.grant.enabled ? `每${value.grant.period}次主抽直接赠送${value.grant.quantity}名角色；${value.grant.target === "first_up" ? "自动选择UP目标" : "绑定池指定角色"}` : "未启用"} />
      <details><summary>查看完整保留参数</summary><div className="readonly-group">
        <ReadonlyValue label="大保底抽数" value={value.big_pity.hard_pity} />
        <ReadonlyValue label="首次赠送触发及抽数" value={`${value.bonus.at_main_draw} / ${value.bonus.draws}`} />
        {value.bonus.rarities.map((rarity) => <ReadonlyValue key={rarity.id} label={`${names.get(rarity.id) ?? rarity.id}赠送池`} value={`基础概率${rarity.base_probability * 100}%；软保底${rarity.soft_enabled ? `第${rarity.soft_start}抽起增加${rarity.soft_step * 100}个百分点` : "未启用"}；硬保底${rarity.hard_enabled ? `第${rarity.hard_pity}抽` : "未启用"}`} />)}
        <ReadonlyValue label="周期与数量" value={`${value.grant.period} / ${value.grant.quantity}`} />
      </div></details>
    </section>
  </div>;
}
