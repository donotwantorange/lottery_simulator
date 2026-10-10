import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { PoolDocument, Rule, RuleDocument } from "../api/types";
import { useNumberDrafts, type NumberDraft } from "../hooks/useEditorDraft";
import { ReadonlyValue } from "./FormFeedback";
import { RarityMapping } from "./RarityMapping";
import { RuleSummary } from "./RuleSummary";

interface Props {
  value: PoolDocument;
  rule: Rule | undefined;
  rules: Rule[];
  kind: "public" | "private";
  visibility: "public" | "hidden";
  canEdit: boolean;
  busy?: boolean;
  canCreatePublic: boolean;
  ownerIsAdmin?: boolean;
  poolOwnerId: string | null;
  editing: boolean;
  savedRuleId?: string;
  onChange(value: PoolDocument): void;
  onKind(value: "public" | "private"): void;
  onVisibility(value: "public" | "hidden"): void;
  onRuleMapping(mapping: Record<string, string | null>, clearUnmapped: boolean): void;
  onCancelRuleMapping(): void;
  onValidityChange?(valid: boolean): void;
  onUnfinishedChange?(unfinished: boolean): void;
}

function newId() { return crypto.randomUUID(); }

function remapDocument(value: PoolDocument, newRule: RuleDocument,
                       mapping: Record<string, string | null>): PoolDocument {
  const nextIds = new Set(newRule.rarities.map((rarity) => rarity.id));
  const resolve = (id: string) => mapping[id] === undefined ? (nextIds.has(id) ? id : null) : mapping[id];
  const rosters = value.rarity_pools.flatMap((roster) => {
    const rarityId = resolve(roster.rarity_id);
    return rarityId ? [{ ...roster, rarity_id: rarityId, characters: roster.characters.map((character) => ({
      ...character, rarity_id: rarityId,
    })) }] : [];
  });
  const present = new Set(rosters.map((roster) => roster.rarity_id));
  for (const rarity of newRule.rarities) if (!present.has(rarity.id)) {
    rosters.push({ rarity_id: rarity.id, characters: [], up_enabled: false, up_share: 0 });
  }
  const rarityLabels: Record<string, string> = {};
  for (const [id, label] of Object.entries(value.rarity_labels)) {
    const target = resolve(id);
    if (target) rarityLabels[target] = label;
  }
  const rewards = value.rewards.map((reward) => {
    const amounts: Record<string, number> = {};
    for (const [id, amount] of Object.entries(reward.amounts)) {
      const target = resolve(id);
      if (target) amounts[target] = amount;
    }
    for (const rarity of newRule.rarities) amounts[rarity.id] ??= 0;
    return { ...reward, amounts };
  });
  const mechanismTargets = { ...value.mechanism_targets };
  if (mechanismTargets.periodic_grant && !rosters.some((roster) =>
    roster.characters.some((character) => character.id === mechanismTargets.periodic_grant))) {
    delete mechanismTargets.periodic_grant;
  }
  return { ...value, rule_ref: { id: newRule.id, name: newRule.name }, rarity_pools: rosters,
    rarity_labels: rarityLabels, rewards, mechanism_targets: mechanismTargets };
}

function poolHasUserData(pool: PoolDocument): boolean {
  return pool.rarity_pools.some((roster) => roster.characters.length > 0) ||
    Object.keys(pool.rarity_labels).length > 0 ||
    pool.rewards.some((reward) => reward.name.trim() || Object.values(reward.amounts).some((amount) => amount !== 0));
}

function initializeForRule(value: PoolDocument, rule: Rule): PoolDocument {
  const rarityIds = rule.document.rarities.map((rarity) => rarity.id);
  return { ...value, rule_ref: { id: rule.id, name: rule.name },
    rarity_pools: rule.document.rarities.map((rarity) => ({ rarity_id: rarity.id, characters: [], up_enabled: false, up_share: 0 })),
    rarity_labels: {},
    rewards: value.rewards.map((reward) => ({ ...reward, amounts: Object.fromEntries(rarityIds.map((id) => [id, 0])) })),
    mechanism_targets: {} };
}

function weightDraftError(text: string): string {
  const value = Number(text);
  return !text.trim() || !Number.isFinite(value) || value <= 0 ? "权重必须是大于0的有限数值。" : "";
}

function nonNegativeDraftError(text: string): string {
  const value = Number(text);
  return !text.trim() || !Number.isFinite(value) || value < 0 ? "请输入大于或等于0的有限数值。" : "";
}

function upShareDraftError(text: string): string {
  const value = Number(text);
  return !text.trim() || !Number.isFinite(value) || value < 0 || value > 100
    ? "UP占比必须是0至100之间的有限数值。" : "";
}

function CharacterRow({ character, disabled, nameError, weightDraft, onChange, onRemove, onMove, onWeightText, onWeightCommit }: {
  character: PoolDocument["rarity_pools"][number]["characters"][number];
  disabled: boolean;
  nameError: string;
  weightDraft?: NumberDraft;
  onChange(patch: Partial<typeof character>): void;
  onRemove(): void;
  onMove(direction: -1 | 1): void;
  onWeightText(text: string): void;
  onWeightCommit(): void;
}) {
  return <tr>
    <td><input id={`pool-character-name-${character.id}`} aria-label="角色名称" required value={character.name} disabled={disabled} aria-invalid={Boolean(nameError)}
      onChange={(event) => onChange({ name: event.target.value })} />
      {nameError && <small className="form-error" role="alert">{nameError}</small>}</td>
    <td><input id={`pool-character-weight-${character.id}`} type="text" required aria-label="角色权重" inputMode="decimal"
      value={weightDraft?.text ?? String(character.weight)} disabled={disabled}
      aria-invalid={Boolean(weightDraft?.error)} onChange={(event) => onWeightText(event.target.value)} onBlur={onWeightCommit} />
      {weightDraft?.error && <small className="form-error" role="alert">{weightDraft.error}</small>}</td>
    <td><label className="inline-check"><input type="checkbox" disabled={disabled} checked={character.is_up}
      onChange={(event) => onChange({ is_up: event.target.checked, is_limited: event.target.checked || character.is_limited })} />UP</label></td>
    <td><label className="inline-check"><input type="checkbox" disabled={disabled || character.is_up}
      checked={character.is_limited} onChange={(event) => onChange({ is_limited: event.target.checked })} />限定</label></td>
    <td><div className="pool-row-actions"><button type="button" aria-label="上移角色" disabled={disabled} onClick={() => onMove(-1)}>↑</button>
      <button type="button" aria-label="下移角色" disabled={disabled} onClick={() => onMove(1)}>↓</button>
      <button type="button" className="danger-button" disabled={disabled} onClick={onRemove}>删除</button></div></td>
  </tr>;
}

function ReadOnlyPool({ value, rule, kind, visibility }: { value: PoolDocument; rule?: Rule; kind: "public" | "private"; visibility: "public" | "hidden" }) {
  const byRank = [...(rule?.document.rarities ?? [])].sort((a, b) => b.rank - a.rank);
  const rosters = new Map(value.rarity_pools.map((item) => [item.rarity_id, item]));
  const allCharacters = byRank.flatMap((rarity) => rosters.get(rarity.id)?.characters ?? []);
  const firstUp = allCharacters.find((item) => item.is_up);
  const highest = byRank[0];
  const bigTarget = rule?.document.big_pity.enabled && highest
    ? rosters.get(highest.id)?.characters.find((item) => item.is_up)
    : undefined;
  const grantTarget = rule?.document.grant.enabled
    ? rule.document.grant.target === "first_up" ? firstUp
      : allCharacters.find((item) => item.id === value.mechanism_targets.periodic_grant)
    : undefined;
  const nameOf = (id: string, fallback: string) => value.rarity_labels[id]?.trim() || fallback;
  return <div className="pool-editor pool-readonly">
    <section className="editor-section"><h3>基本信息</h3><div className="field-grid">
      <ReadonlyValue label="角色池名称" value={value.name} />
      <ReadonlyValue label="池类型" value={kind === "public" ? "公共池" : "私有池"} />
      {kind === "private" && <ReadonlyValue label="可见性" value={visibility === "public" ? "公开可见" : "隐藏"} />}
      <ReadonlyValue label="最初作者" value={value.original_author ?? "未署名"} />
    </div></section>
    <section className="editor-section"><h3>绑定规则</h3>
      {rule ? <RuleSummary rule={rule} pool={value} /> : <p className="form-error" role="alert">当前绑定规则不可用。</p>}
    </section>
    {rule && <section className="editor-section"><h3>角色名单</h3>
      {rule.document.rarities.slice().sort((a, b) => a.rank - b.rank).map((rarity) => {
        const roster = rosters.get(rarity.id);
        const rarityName = nameOf(rarity.id, rarity.name);
        return <section className="pool-rarity" key={rarity.id}><h4>{rarityName}</h4>
          <p className="muted">UP概率分组：{roster?.up_enabled ? "已启用" : "已关闭"}{roster?.up_enabled ? ` · UP占比 ${roster.up_share * 100}%` : ""}</p>
          {roster?.characters.length ? <ul>{roster.characters.map((character) => <li key={character.id}>
            {character.name} · 权重 {character.weight} · {character.is_up ? "UP" : "非UP"} · {character.is_limited ? "限定" : "非限定"}
          </li>)}</ul> : <p className="muted">此档仍可抽出，但不记录具体角色。</p>}
        </section>;
      })}
    </section>}
    {rule && (rule.document.big_pity.enabled || rule.document.grant.enabled)
      ? <section className="editor-section"><h3>机制目标</h3>
        {rule.document.big_pity.enabled && <ReadonlyValue label="大保底目标" value={bigTarget?.name ?? "未解析；需在最高档名单标记UP角色"} />}
        {rule.document.grant.enabled && <ReadonlyValue label="周期赠送目标" value={grantTarget?.name ?? (rule.document.grant.target === "first_up" ? "未解析；需标记UP角色" : "未解析；需绑定池指定角色")} />}
        {rule.document.big_pity.enabled && <p className="muted">大保底目标从最高档名单中按顺序选第一个UP。</p>}
        {rule.document.grant.enabled && rule.document.grant.target === "first_up" &&
          <p className="muted">周期自动目标从最高档到低档逐档检查名单，选中第一个UP。</p>}
      </section>
      : <section className="editor-section"><h3>机制目标</h3><p className="muted">当前无需绑定目标。</p></section>}
    <section className="editor-section"><h3>奖励</h3>
      <p className="muted">每抽获得该稀有度时附加的奖励数量。</p>
      {value.rewards.length ? value.rewards.map((reward) => <div className="pool-reward" key={reward.id}>
        <ReadonlyValue label="奖励名称" value={reward.name} />
        {rule?.document.rarities.map((rarity) => <ReadonlyValue key={rarity.id} label={`${nameOf(rarity.id, rarity.name)}数量`}
          value={reward.amounts[rarity.id] ?? 0} />)}
      </div>) : <p className="muted">没有配置奖励。</p>}
    </section>
  </div>;
}

export function PoolEditor({ value, rule, rules, kind, visibility, canEdit, busy = false, canCreatePublic, editing,
  ownerIsAdmin = false, poolOwnerId, savedRuleId, onChange, onKind, onVisibility, onRuleMapping, onCancelRuleMapping,
  onValidityChange, onUnfinishedChange }: Props) {
  const [pendingRule, setPendingRule] = useState<Rule | null>(null);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [clearUnmapped, setClearUnmapped] = useState(false);
  const [switchError, setSwitchError] = useState("");
  const numberDrafts = useNumberDrafts();
  const [shareRepairVisible, setShareRepairVisible] = useState<string[]>([]);
  const availableRules = useMemo(() => rules.filter((item) => {
    if (kind === "public") return item.kind === "public";
    if (item.kind === "public") return true;
    if (visibility === "public") return item.visibility === "public";
    return item.owner_id === poolOwnerId || item.visibility === "public" || ownerIsAdmin;
  }), [rules, kind, visibility, poolOwnerId, ownerIsAdmin]);
  const savedRule = savedRuleId ? rules.find((item) => item.id === savedRuleId) : undefined;
  const deletedRarities = savedRule && rule && savedRule.id !== rule.id
    ? savedRule.document.rarities.filter((rarity) => !rule.document.rarities.some((next) => next.id === rarity.id))
    : [];
  const poolStructureAccepted = editing && deletedRarities.length > 0 && value.rule_ref.id !== savedRuleId;
  const rarityById = new Map(rule?.document.rarities.map((rarity) => [rarity.id, rarity]) ?? []);
  const characters = value.rarity_pools.flatMap((roster) => roster.characters);
  const highestId = rule?.document.rarities.reduce((highest, rarity) =>
    !highest || rarity.rank > highest.rank ? rarity : highest, undefined as Rule["document"]["rarities"][number] | undefined)?.id;
  const firstUp = [...(rule?.document.rarities ?? [])].sort((a, b) => b.rank - a.rank)
    .flatMap((rarity) => value.rarity_pools.find((roster) => roster.rarity_id === rarity.id)?.characters ?? [])
    .find((character) => character.is_up);
  const bigTarget = value.rarity_pools.find((roster) => roster.rarity_id === highestId)?.characters.find((character) => character.is_up);
  const rostersValid = value.rarity_pools.every((roster) => {
    const names = roster.characters.map((character) => character.name.trim());
    return names.every(Boolean) && new Set(names).size === names.length
      && roster.characters.every((character) => Number.isFinite(character.weight) && character.weight > 0
        && (!character.is_up || character.is_limited))
      && Number.isFinite(roster.up_share) && roster.up_share >= 0 && roster.up_share <= 1
      && (!roster.up_enabled || (roster.characters.length > 0
        && (roster.up_share === 0 || roster.characters.some((character) => character.is_up))
        && (roster.up_share === 1 || roster.characters.some((character) => !character.is_up))));
  });
  const valid = value.name.trim().length > 0 && !!rule && value.rarity_pools.length === rule.document.rarities.length
    && rule.document.rarities.every((rarity) => value.rarity_pools.some((roster) => roster.rarity_id === rarity.id))
    && rostersValid
    && (!rule.document.big_pity.enabled || Boolean(bigTarget))
    && (!rule.document.grant.enabled || (rule.document.grant.target === "pool_selected"
      ? characters.some((character) => character.id === value.mechanism_targets.periodic_grant)
      : Boolean(firstUp)))
    && new Set(value.rewards.map((reward) => reward.name.trim())).size === value.rewards.length
    && value.rewards.every((reward) => reward.name.trim() && Object.values(reward.amounts).every((amount) => Number.isFinite(amount) && amount >= 0))
    && new Set(value.rarity_pools.flatMap((roster) => roster.characters.map((character) => character.id))).size === characters.length
    && new Set(Object.values(value.rarity_labels)).size === Object.values(value.rarity_labels).length
    && (!rule?.document.grant.enabled || rule.document.grant.target !== "pool_selected"
      || characters.some((character) => character.id === value.mechanism_targets.periodic_grant))
    && !numberDrafts.hasInvalid;
  useEffect(() => onValidityChange?.(valid), [onValidityChange, valid]);
  useEffect(() => onUnfinishedChange?.(Object.keys(numberDrafts.fields).length > 0), [numberDrafts.fields, onUnfinishedChange]);
  const dataDisabled = !canEdit || busy || poolStructureAccepted;

  function change(update: (draft: PoolDocument) => void) {
    const draft = structuredClone(value);
    update(draft);
    onChange(draft);
  }

  function editRarity(rarityId: string, update: (roster: PoolDocument["rarity_pools"][number]) => void) {
    change((draft) => update(draft.rarity_pools.find((item) => item.rarity_id === rarityId)!));
  }

  function requestRule(id: string) {
    const candidate = rules.find((item) => item.id === id);
    if (!candidate || candidate.id === value.rule_ref.id) return;
    if (!rule) {
      if (poolHasUserData(value) && !window.confirm("选择新规则会清除当前名单、显示名和奖励数值。继续吗？")) return;
      onChange(initializeForRule(value, candidate));
      numberDrafts.clear();
      setShareRepairVisible([]);
      setSwitchError(""); setMapping({}); setClearUnmapped(false);
      return;
    }
    setPendingRule(candidate); setMapping({}); setClearUnmapped(false); setSwitchError("");
  }

  function confirmRuleChange() {
    if (!pendingRule || !rule) return;
    const oldIds = new Set(rule.document.rarities.map((item) => item.id));
    const newIds = new Set(pendingRule.document.rarities.map((item) => item.id));
    const removed = [...oldIds].filter((id) => !newIds.has(id));
    if (removed.some((id) => mapping[id] === undefined)) {
      setSwitchError("请为每个删除的稀有度选择映射目标或清空。"); return;
    }
    if (removed.some((id) => mapping[id] === null) && !clearUnmapped) {
      setSwitchError("清空未映射档位需要勾选确认。"); return;
    }
    const resolved = [...oldIds].map((id) => mapping[id] === undefined ? (newIds.has(id) ? id : null) : mapping[id]);
    if (resolved.filter(Boolean).length !== new Set(resolved.filter(Boolean)).size) {
      setSwitchError("多个旧档不能映射到同一个新档，请调整映射。"); return;
    }
    const next = remapDocument(value, pendingRule.document, mapping);
    const nextCharacterIds = new Set(next.rarity_pools.flatMap((roster) => roster.characters.map((character) => character.id)));
    const nextRarityIds = new Set(pendingRule.document.rarities.map((rarity) => rarity.id));
    Object.keys(numberDrafts.fields).forEach((fieldId) => {
      if (fieldId.startsWith("weight:") && !nextCharacterIds.has(fieldId.slice("weight:".length))) numberDrafts.discard(fieldId);
      if (fieldId.startsWith("up_share:")) {
        const oldRarityId = fieldId.slice("up_share:".length);
        const targetId = mapping[oldRarityId] === undefined
          ? nextRarityIds.has(oldRarityId) ? oldRarityId : null
          : mapping[oldRarityId];
        if (targetId) {
          if (targetId !== oldRarityId) numberDrafts.update(`up_share:${targetId}`, numberDrafts.fields[fieldId]);
          if (targetId !== oldRarityId) numberDrafts.discard(fieldId);
        } else numberDrafts.discard(fieldId);
      }
      if (fieldId.startsWith("reward:")) {
        const [, rewardId, oldRarityId] = fieldId.split(":");
        const targetId = mapping[oldRarityId] === undefined
          ? nextRarityIds.has(oldRarityId) ? oldRarityId : null
          : mapping[oldRarityId];
        const targetKey = targetId ? `reward:${rewardId}:${targetId}` : "";
        if (targetKey && targetKey !== fieldId) {
          numberDrafts.update(targetKey, numberDrafts.fields[fieldId]);
          numberDrafts.discard(fieldId);
        } else if (!targetKey) numberDrafts.discard(fieldId);
      }
    });
    setShareRepairVisible((current) => current.filter((id) => nextRarityIds.has(id)));
    onChange(next); onRuleMapping(mapping, clearUnmapped);
    setPendingRule(null); setSwitchError("");
  }

  if (!canEdit) return <ReadOnlyPool value={value} rule={rule} kind={kind} visibility={visibility} />;

  return <div className="pool-editor">
    <section className="editor-section"><h3>基本信息</h3>
      <div className="field-grid">
        <label>角色池名称<input id="pool-name" aria-label="角色池名称" maxLength={255} required disabled={!canEdit || busy}
          value={value.name} onChange={(event) => change((draft) => { draft.name = event.target.value; })} /></label>
        <label>池类型<select aria-label="池类型" disabled={!canEdit || busy || editing || !canCreatePublic}
          value={kind} onChange={(event) => onKind(event.target.value as "private" | "public")}>
          <option value="private">私有池</option>{(canCreatePublic || kind === "public") && <option value="public">公共池</option>}
        </select></label>
        {kind === "private" && <label>可见性<select aria-label="池可见性" disabled={!canEdit || busy} value={visibility}
          onChange={(event) => onVisibility(event.target.value as "public" | "hidden")}>
          <option value="hidden">隐藏</option><option value="public">公开可见</option>
        </select></label>}
      </div>
      {editing && <p className="muted">池类型不能原位转换；请复制为新池。</p>}
    </section>

    <section className="editor-section"><h3>绑定规则</h3>
      <label className="compact-field">规则<select aria-label="绑定规则" disabled={dataDisabled}
        value={value.rule_ref.id} onChange={(event) => requestRule(event.target.value)}>
        {!rule && <option value={value.rule_ref.id}>{value.rule_ref.name || "当前无规则"}（不可用）</option>}
        {!availableRules.length && <option value="">没有可用规则</option>}
        {availableRules.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.revision}</option>)}
      </select></label>
      {!rule && <p className="form-error" role="alert">当前绑定规则不可用，请选择一个可用规则。</p>}
      {!availableRules.length && <p className="muted">没有符合此池所有者、类型和可见性的可用规则。<Link to="/rules/">前往规则页查看或创建规则</Link>。</p>}
      {rule && <RuleSummary rule={rule} pool={value} />}
      {pendingRule && rule && <div className="import-preview" aria-labelledby="rule-switch-title">
        <h3 id="rule-switch-title">确认切换规则</h3>
        <p>从“{rule.name}”切换到“{pendingRule.name}”。同ID稀有度保留名单、显示名和奖励；其他旧档需要映射或明确清空。</p>
        <RarityMapping previous={rule} next={pendingRule} mapping={mapping} onChange={setMapping}
          clearUnmapped={clearUnmapped} onClearUnmapped={setClearUnmapped} />
        {switchError && <p role="alert" className="form-error">{switchError}</p>}
        <div className="button-row"><button type="button" className="primary-button" disabled={dataDisabled} onClick={confirmRuleChange}>应用映射并切换</button>
          <button type="button" disabled={busy} onClick={() => { setPendingRule(null); setSwitchError(""); }}>取消切换</button></div>
      </div>}
      {pendingRule && rule && <div className="notice-note">仅本次明确确认会修改草稿；此时尚未向服务器保存。</div>}
    </section>

    {rule && <section className="editor-section"><h3>按稀有度设置角色名单</h3>
      <p className="muted">权重1和2表示组内概率比例1:2，不是1%和2%。UP勾选会自动标记限定；启用UP分组与角色的UP标记不同，UP占比是档内比例，不是整次抽卡的概率。</p>
      {[...rule.document.rarities].sort((a, b) => a.rank - b.rank).map((rarity) => {
        const roster = value.rarity_pools.find((item) => item.rarity_id === rarity.id)!;
        return <section className="pool-rarity" key={rarity.id}>
          <div className="section-heading"><div><h4>{value.rarity_labels[rarity.id] ?? rarity.name}</h4>
            <p className="muted">基础概率 {(rarity.base_probability * 100).toFixed(3)}% · 规则硬保底{rarity.hard_enabled ? `${rarity.hard_pity}抽` : "关闭"}</p></div>
            <button type="button" disabled={dataDisabled} onClick={() => editRarity(rarity.id, (item) => item.characters.push({
              id: newId(), rarity_id: rarity.id, name: "新角色", weight: 1, is_up: false, is_limited: false,
            }))}>添加角色</button>
          </div>
          <div className="field-grid">
            <label className="inline-check"><input type="checkbox" disabled={dataDisabled} checked={roster.up_enabled}
              onChange={(event) => {
                if (!event.target.checked) setShareRepairVisible((current) => current.filter((id) => id !== rarity.id));
                editRarity(rarity.id, (item) => { item.up_enabled = event.target.checked; });
              }} />启用UP概率分组</label>
            {(roster.up_enabled || shareRepairVisible.includes(rarity.id)) && <label>UP占比（%）<input id={`pool-up-share-${rarity.id}`}
              type="text" inputMode="decimal" disabled={dataDisabled}
              value={numberDrafts.fields[`up_share:${rarity.id}`]?.text ?? String(roster.up_share * 100)}
              aria-invalid={Boolean(numberDrafts.fields[`up_share:${rarity.id}`]?.error)}
              onChange={(event) => {
                const text = event.target.value;
                const error = upShareDraftError(text);
                numberDrafts.update(`up_share:${rarity.id}`, { text, lastLegal: roster.up_share * 100, error });
                if (!error) editRarity(rarity.id, (item) => { item.up_share = Number(text) / 100; });
              }} onBlur={() => {
                const field = numberDrafts.fields[`up_share:${rarity.id}`];
                if (field && !field.error) numberDrafts.discard(`up_share:${rarity.id}`);
              }} />
              {numberDrafts.fields[`up_share:${rarity.id}`]?.error && <small className="form-error" role="alert">{numberDrafts.fields[`up_share:${rarity.id}`].error}</small>}</label>}
            {!roster.up_enabled && numberDrafts.fields[`up_share:${rarity.id}`]?.error && <div className="notice-note">
              <p>UP占比有未完成的参数修改。</p>
              <button type="button" onClick={() => setShareRepairVisible((current) => [...new Set([...current, rarity.id])])}>展开修正</button>
              <button type="button" onClick={() => { numberDrafts.discard(`up_share:${rarity.id}`); setShareRepairVisible((current) => current.filter((id) => id !== rarity.id)); }}>放弃未完成输入，恢复上次合法值</button>
            </div>}
            <label>显示名称<input aria-label={`${rarity.name}显示名称`} value={value.rarity_labels[rarity.id] ?? ""} disabled={dataDisabled}
              onChange={(event) => change((draft) => { if (event.target.value) draft.rarity_labels[rarity.id] = event.target.value; else delete draft.rarity_labels[rarity.id]; })} /></label>
          </div>
          <p className="muted">角色的UP标记用于分类和自动目标；启用UP概率分组后，UP占比才参与本档角色概率分配。</p>
          <div className="table-wrap"><table><thead><tr><th>角色</th><th>权重</th><th>UP</th><th>限定</th><th>顺序 / 操作</th></tr></thead><tbody>
            {roster.characters.map((character, index) => <CharacterRow key={character.id} character={character} disabled={dataDisabled}
              nameError={!character.name.trim() ? "角色名称不能为空。"
                : roster.characters.some((other, otherIndex) => otherIndex !== index && other.name.trim() === character.name.trim())
                  ? "同一稀有度的角色名称不能重复。" : ""}
              weightDraft={numberDrafts.fields[`weight:${character.id}`]}
              onChange={(patch) => editRarity(rarity.id, (item) => { item.characters[index] = { ...item.characters[index], ...patch }; })}
              onWeightText={(text) => numberDrafts.update(`weight:${character.id}`, {
                text, lastLegal: numberDrafts.fields[`weight:${character.id}`]?.lastLegal ?? character.weight,
                error: weightDraftError(text),
              })}
              onWeightCommit={() => {
                const field = numberDrafts.fields[`weight:${character.id}`];
                if (!field) return;
                const error = weightDraftError(field.text);
                if (error) { numberDrafts.update(`weight:${character.id}`, { ...field, error }); return; }
                editRarity(rarity.id, (item) => { item.characters[index] = { ...item.characters[index], weight: Number(field.text) }; });
                numberDrafts.discard(`weight:${character.id}`);
              }}
              onRemove={() => {
                numberDrafts.discard(`weight:${character.id}`);
                change((draft) => {
                  draft.rarity_pools.find((item) => item.rarity_id === rarity.id)!.characters.splice(index, 1);
                  if (draft.mechanism_targets.periodic_grant === character.id) delete draft.mechanism_targets.periodic_grant;
                });
              }}
              onMove={(direction) => editRarity(rarity.id, (item) => {
                const target = index + direction; if (target < 0 || target >= item.characters.length) return;
                [item.characters[index], item.characters[target]] = [item.characters[target], item.characters[index]];
              })} />)}
          </tbody></table></div>
          {roster.characters.length === 0 && <p className="muted">此档仍可抽出，但不记录具体角色。</p>}
        </section>;
      })}
    </section>}

    {rule && (rule.document.big_pity.enabled || rule.document.grant.enabled) && <section className="editor-section"><h3>机制目标绑定</h3>
      <p>目标按角色ID绑定，不会因同名角色自动替换。</p>
      {rule.document.big_pity.enabled && <><p>大保底目标：{bigTarget?.name ?? "未解析；请在最高稀有度标记UP角色"}（规则使用最高稀有度中排序第一的UP）</p><p className="muted">按这一档角色名单从上到下选择第一个标记UP的角色，与权重大小无关。</p></>}
      {rule.document.grant.enabled && rule.document.grant.target === "pool_selected" && <label className="compact-field">周期赠送角色
        <select aria-label="周期赠送角色" disabled={dataDisabled} value={value.mechanism_targets.periodic_grant ?? ""}
          onChange={(event) => change((draft) => { if (event.target.value) draft.mechanism_targets.periodic_grant = event.target.value; else delete draft.mechanism_targets.periodic_grant; })}>
          <option value="">选择实际角色</option>{characters.map((item) => <option key={item.id} value={item.id}>{item.name} · {value.rarity_labels[item.rarity_id] ?? rarityById.get(item.rarity_id)?.name}</option>)}
        </select></label>}
      {rule.document.grant.enabled && rule.document.grant.target === "first_up" && <><p>周期赠送目标：{firstUp?.name ?? "未解析；请标记UP角色"}</p><p className="muted">自动目标按最高档到低档逐档检查名单，选中第一个UP角色。</p></>}
    </section>}

    <section className="editor-section"><div className="section-heading"><div><h3>奖励</h3><p className="muted">每抽获得该稀有度时附加的奖励数量。</p></div>
      <button type="button" disabled={dataDisabled} onClick={() => change((draft) => draft.rewards.push({
        id: newId(), name: `奖励${draft.rewards.length + 1}`,
        amounts: Object.fromEntries(rule?.document.rarities.map((rarity) => [rarity.id, 0]) ?? []),
      }))}>添加奖励</button></div>
      {value.rewards.map((reward, index) => <div className="pool-reward" key={reward.id}>
        <label>奖励名称<input required value={reward.name} disabled={dataDisabled} onChange={(event) => change((draft) => { draft.rewards[index].name = event.target.value; })} /></label>
        {rule?.document.rarities.map((rarity) => <label key={rarity.id}>{value.rarity_labels[rarity.id] ?? rarity.name}数量
          <input id={`pool-reward-${reward.id}-${rarity.id}`} type="text" inputMode="decimal"
            value={numberDrafts.fields[`reward:${reward.id}:${rarity.id}`]?.text ?? String(reward.amounts[rarity.id] ?? 0)}
            aria-invalid={Boolean(numberDrafts.fields[`reward:${reward.id}:${rarity.id}`]?.error)} disabled={dataDisabled}
            onChange={(event) => {
              const text = event.target.value;
              const error = nonNegativeDraftError(text);
              numberDrafts.update(`reward:${reward.id}:${rarity.id}`, { text, lastLegal: reward.amounts[rarity.id] ?? 0, error });
              if (!error) change((draft) => { draft.rewards[index].amounts[rarity.id] = Number(text); });
            }} onBlur={() => {
              const key = `reward:${reward.id}:${rarity.id}`;
              if (numberDrafts.fields[key] && !numberDrafts.fields[key].error) numberDrafts.discard(key);
            }} />
          {numberDrafts.fields[`reward:${reward.id}:${rarity.id}`]?.error && <small className="form-error" role="alert">{numberDrafts.fields[`reward:${reward.id}:${rarity.id}`].error}</small>}</label>)}
        <button type="button" className="danger-button" disabled={dataDisabled} onClick={() => {
          numberDrafts.removeMatching(`reward:${reward.id}:`);
          change((draft) => { draft.rewards.splice(index, 1); });
        }}>删除奖励</button>
      </div>)}
      {value.rewards.length === 0 && <p className="muted">没有配置奖励。</p>}
    </section>
    {poolStructureAccepted && <div className="notice-note"><p>映射结果需先保存，服务端确认与旧名单、奖励及显示名一致后，才能继续编辑池数据。</p>
      <button type="button" disabled={!canEdit} onClick={onCancelRuleMapping}>取消未保存的规则切换</button></div>}
    {!valid && <p className="form-error" role="alert">请检查池名称、稀有度、角色名/权重、UP分组比例、奖励与机制目标绑定。</p>}
  </div>;
}
