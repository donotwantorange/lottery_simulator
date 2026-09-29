import { useEffect, useState } from "react";
import type { PoolDocument } from "../api/types";

type Config = PoolDocument["pool_config"];
type Rarity = "4" | "5" | "6";

interface Props {
  value: PoolDocument;
  kind: "public" | "private";
  visibility: "public" | "hidden";
  canCreatePublic: boolean;
  editing: boolean;
  onChange(value: PoolDocument): void;
  onKind(value: "public" | "private"): void;
  onVisibility(value: "public" | "hidden"): void;
}

interface DecimalInputProps {
  value: number | null;
  label: string;
  disabled?: boolean;
  onCommit(value: number): void;
}

function DecimalInput({ value, label, disabled = false, onCommit }: DecimalInputProps) {
  const displayValue = value === null ? "" : String(value);
  const [text, setText] = useState(displayValue);
  useEffect(() => setText(displayValue), [displayValue]);
  function commit() {
    const parsed = Number(text.trim());
    if (text.trim() === "" || !Number.isFinite(parsed)) {
      setText(displayValue);
      return;
    }
    onCommit(parsed);
  }
  return <input type="text" inputMode="decimal" aria-label={label} disabled={disabled}
    value={text} onChange={(event) => setText(event.target.value)} onBlur={commit} />;
}

export function PoolEditor({ value, kind, visibility, canCreatePublic, editing, onChange, onKind, onVisibility }: Props) {
  function change(update: (draft: PoolDocument) => void) {
    const next = structuredClone(value);
    update(next);
    onChange(next);
  }
  function changeConfig(update: (config: Config) => void) {
    change((draft) => update(draft.pool_config));
  }

  return <div className="stack-form">
    <div className="field-grid">
      <label>角色池名称<input value={value.name} maxLength={255} onChange={(event) => change((draft) => { draft.name = event.target.value; })} /></label>
      <label>池类型<select value={kind} disabled={editing} onChange={(event) => onKind(event.target.value as "public" | "private")}>
        <option value="private">私有池</option>{canCreatePublic && <option value="public">公共池</option>}
      </select></label>
      {kind === "private" && <label>可见性<select value={visibility} onChange={(event) => onVisibility(event.target.value as "public" | "hidden")}>
        <option value="hidden">仅自己</option><option value="public">对登录用户公开</option>
      </select></label>}
      <label>最初作者<input value={value.original_author ?? ""} disabled={editing} placeholder="创建时留空则使用当前账号" onChange={(event) => change((draft) => { draft.original_author = event.target.value || null; })} /></label>
    </div>
    <p className="muted">规则：{value.rule_name}。已有池不能更改类型或最初作者；需要转换类型请使用“复制”。</p>
    <section className="editor-section"><h3>稀有度名称与概率</h3>
      <div className="field-grid">
        {(["4", "5", "6"] as Rarity[]).map((rarity) => <label key={rarity}>{rarity}星显示名称<input value={value.rarity_labels[rarity]} onChange={(event) => change((draft) => { draft.rarity_labels[rarity] = event.target.value; })} /></label>)}
        <label>UP占六星概率<DecimalInput value={value.pool_config.up_share} label="UP占六星概率" onCommit={(number) => changeConfig((config) => { config.up_share = number; })} /></label>
        <label>五星基础概率<DecimalInput value={value.pool_config.five_star.base_probability} label="五星基础概率" onCommit={(number) => changeConfig((config) => { config.five_star.base_probability = number; })} /></label>
        <label>五星硬保底抽次<input type="number" min="1" step="1" value={value.pool_config.five_star.hard_pity} onChange={(event) => changeConfig((config) => { config.five_star.hard_pity = Number(event.target.value); })} /></label>
        <label className="inline-check"><input type="checkbox" checked={value.pool_config.five_star.pity_enabled} onChange={(event) => changeConfig((config) => { config.five_star.pity_enabled = event.target.checked; })} />启用五星保底</label>
      </div>
    </section>
    <section className="editor-section"><h3>六星角色</h3>
      <div className="table-wrap"><table><thead><tr><th>名称</th><th>UP</th><th>限定</th><th>UP权重</th><th>操作</th></tr></thead><tbody>
        {value.pool_config.six_star_characters.map((character, index) => <tr key={index}>
          <td><input aria-label={`六星角色${index + 1}名称`} value={character.name} onChange={(event) => changeConfig((config) => { config.six_star_characters[index].name = event.target.value; })} /></td>
          <td><input type="checkbox" aria-label={`六星角色${index + 1} UP`} checked={character.is_up} onChange={(event) => changeConfig((config) => { const item = config.six_star_characters[index]; item.is_up = event.target.checked; if (item.is_up) { item.is_limited = true; item.up_weight ??= 1; } else item.up_weight = null; })} /></td>
          <td><input type="checkbox" aria-label={`六星角色${index + 1}限定`} disabled={character.is_up} checked={character.is_limited} onChange={(event) => changeConfig((config) => { config.six_star_characters[index].is_limited = event.target.checked; })} /></td>
          <td><DecimalInput label={`六星角色${index + 1} UP权重`} disabled={!character.is_up} value={character.up_weight} onCommit={(number) => changeConfig((config) => { config.six_star_characters[index].up_weight = number; })} /></td>
          <td><button type="button" className="quiet-button" onClick={() => changeConfig((config) => { config.six_star_characters.splice(index, 1); })}>移除</button></td>
        </tr>)}
      </tbody></table></div>
      <button type="button" className="secondary-button" onClick={() => changeConfig((config) => { config.six_star_characters.push({ name: "新六星角色", is_up: false, is_limited: false, up_weight: null }); })}>添加六星角色</button>
    </section>
    {(["four_star_characters", "five_star_characters"] as const).map((field) => <section className="editor-section" key={field}>
      <h3>{field === "four_star_characters" ? "四星" : "五星"}角色名单</h3>
      <div className="table-wrap"><table><thead><tr><th>名称</th><th>权重</th><th>操作</th></tr></thead><tbody>
        {value.pool_config[field].map((character, index) => <tr key={index}>
          <td><input aria-label={`${field === "four_star_characters" ? "四" : "五"}星角色${index + 1}名称`} value={character.name} onChange={(event) => changeConfig((config) => { config[field][index].name = event.target.value; })} /></td>
          <td><DecimalInput label={`${field === "four_star_characters" ? "四" : "五"}星角色${index + 1}权重`} value={character.weight} onCommit={(number) => changeConfig((config) => { config[field][index].weight = number; })} /></td>
          <td><button type="button" className="quiet-button" onClick={() => changeConfig((config) => { config[field].splice(index, 1); })}>移除</button></td>
        </tr>)}
      </tbody></table></div>
      <button type="button" className="secondary-button" onClick={() => changeConfig((config) => { config[field].push({ name: "新角色", weight: 1 }); })}>添加角色</button>
    </section>)}
    <section className="editor-section"><h3>附赠奖励</h3>
      <div className="table-wrap"><table><thead><tr><th>名称</th><th>四星</th><th>五星</th><th>六星</th><th>操作</th></tr></thead><tbody>
        {value.pool_config.rewards.map((reward, index) => <tr key={index}>
          <td><input aria-label={`奖励${index + 1}名称`} value={reward.name} onChange={(event) => changeConfig((config) => { config.rewards[index].name = event.target.value; })} /></td>
          {(["four_star", "five_star", "six_star"] as const).map((rarity) => <td key={rarity}><DecimalInput label={`奖励${index + 1}${rarity}数值`} value={reward[rarity]} onCommit={(number) => changeConfig((config) => { config.rewards[index][rarity] = number; })} /></td>)}
          <td><button type="button" className="quiet-button" onClick={() => changeConfig((config) => { config.rewards.splice(index, 1); })}>移除</button></td>
        </tr>)}
      </tbody></table></div>
      <button type="button" className="secondary-button" onClick={() => changeConfig((config) => { config.rewards.push({ name: "新奖励", four_star: 0, five_star: 0, six_star: 0 }); })}>添加奖励</button>
    </section>
  </div>;
}
