import type { Rule } from "../api/types";

interface Props {
  previous: Rule;
  next: Rule;
  mapping: Record<string, string | null>;
  onChange(mapping: Record<string, string | null>): void;
  clearUnmapped: boolean;
  onClearUnmapped(value: boolean): void;
}

export function RarityMapping({ previous, next, mapping, onChange, clearUnmapped, onClearUnmapped }: Props) {
  const nextIds = new Set(next.document.rarities.map((item) => item.id));
  const previousIds = new Set(previous.document.rarities.map((item) => item.id));
  const removed = previous.document.rarities.filter((item) => !nextIds.has(item.id));
  if (!removed.length) return <p className="muted">稀有度ID没有删除；已有名单和奖励数据会按相同ID保留。</p>;
  return <div className="rarity-mapping">
    <p>已删除的旧稀有度需逐项映射到新档，或明确选择清空该档的名单、奖励和显示名。映射目标不能重复。</p>
    {removed.map((rarity) => <label className="compact-field" key={rarity.id}>
      {rarity.name}（旧档）
      <select value={mapping[rarity.id] === undefined ? "__choose__" : mapping[rarity.id] ?? "__clear__"}
        onChange={(event) => {
          const nextValue = event.target.value;
          const updated = { ...mapping };
          if (nextValue === "__choose__") delete updated[rarity.id];
          else updated[rarity.id] = nextValue === "__clear__" ? null : nextValue;
          onChange(updated);
        }}>
        <option value="__choose__">请选择映射或清空</option>
        <option value="__clear__">清空此档数据</option>
        {next.document.rarities.filter((target) => !previousIds.has(target.id)).map((target) =>
          <option key={target.id} value={target.id}>{target.name}</option>)}
      </select>
    </label>)}
    <label className="inline-check"><input type="checkbox" checked={clearUnmapped}
      onChange={(event) => onClearUnmapped(event.target.checked)} />确认清空未映射档位数据</label>
  </div>;
}
