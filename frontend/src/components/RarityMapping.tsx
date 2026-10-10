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
  const nextById = new Map(next.document.rarities.map((item) => [item.id, item]));
  const previousIds = new Set(previous.document.rarities.map((item) => item.id));
  const retained = previous.document.rarities.filter((item) => nextById.has(item.id));
  const removed = previous.document.rarities.filter((item) => !nextById.has(item.id));
  const hasExplicitClear = removed.some((item) => mapping[item.id] === null);

  return <div className="rarity-mapping">
    <p>规则稀有度变更影响池名单、显示名和奖励；同一稀有度ID自动保留，其他旧档请逐项映射或选择清空。映射目标不能重复。</p>
    {retained.map((rarity) => {
      const target = nextById.get(rarity.id)!;
      return <p className="muted" key={rarity.id}>{rarity.name} → {target.name}：按相同ID保留名单、显示名和奖励</p>;
    })}
    {removed.map((rarity) => {
      const selected = mapping[rarity.id];
      const target = typeof selected === "string" ? nextById.get(selected) : undefined;
      const impact = selected === null
        ? "清空：该档名单、显示名和奖励将被移除"
        : target
          ? `${target.name}：名单、显示名和奖励迁移到此档`
          : "尚未选择映射目标或清空";
      return <div className="compact-field" key={rarity.id}>
        <label>{rarity.name}（旧档）
          <select aria-label={`${rarity.name}（旧档）`} value={selected === undefined ? "__choose__" : selected ?? "__clear__"}
            onChange={(event) => {
              const nextValue = event.target.value;
              const updated = { ...mapping };
              if (nextValue === "__choose__") delete updated[rarity.id];
              else updated[rarity.id] = nextValue === "__clear__" ? null : nextValue;
              onChange(updated);
            }}>
            <option value="__choose__">请选择映射或清空</option>
            <option value="__clear__">清空此档数据</option>
            {next.document.rarities.filter((candidate) => !previousIds.has(candidate.id)).map((candidate) =>
              <option key={candidate.id} value={candidate.id}>{candidate.name}</option>)}</select>
        </label>
        <p className="muted">{rarity.name} → {impact}</p>
      </div>;
    })}
    {hasExplicitClear && <label className="inline-check"><input type="checkbox" checked={clearUnmapped}
      onChange={(event) => onClearUnmapped(event.target.checked)} />确认清空所选旧档数据</label>}
  </div>;
}
