import type { RuleRarityDocument } from "./api/types";
type NullableText = string | null | undefined;

export function softStartFromMisses(misses: number): number {
  if (typeof misses !== "number" || !Number.isSafeInteger(misses) || misses < 0 || !Number.isSafeInteger(misses + 1)) {
    throw new Error("连续未获得次数须为非负安全整数，且加1仍为安全整数。");
  }
  return misses + 1;
}

export function formatPoints(step: number): string {
  const points = step * 100;
  if (!Number.isFinite(points) || points < 0) return "数据无效";
  return points > 0 && points < 0.00005 ? points.toExponential(4) : points.toFixed(4);
}

export function softPityTarget(name: string, highest: boolean): string {
  const target = name.includes("干员") ? name : `${name}干员`;
  return highest ? target : `${target}或更高档`;
}

export const SOFT_PITY_CONSTRAINT = "增幅单位为百分点，实际概率受低档可扣减概率、更高档机制及100%上限约束。";

export function softPityText(rarity: RuleRarityDocument, highest: boolean, scope = ""): string {
  if (!rarity.soft_enabled) return "软保底未启用";
  const target = softPityTarget(rarity.name, highest);
  return `${scope ? `${scope}：` : ""}若连续${rarity.soft_start - 1}次没有获取${target}，接下来每一次寻访获取${rarity.name.includes("干员") ? rarity.name : `${rarity.name}干员`}的概率将依次提高${formatPoints(rarity.soft_step)}个百分点。`;
}

const MISSING = "数据缺失";

function groupDecimalText(value: string): string {
  const match = /^([+-]?)(\d+)(\.\d+)?$/.exec(value);
  if (!match) return "数据无效";
  const [, sign, integer, fraction = ""] = match;
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${sign}${grouped}${fraction}`;
}

export function formatCount(value: number | string | bigint | null | undefined): string {
  if (value === null || value === undefined) return MISSING;
  if (typeof value === "bigint") return groupDecimalText(value.toString());
  if (typeof value === "string") return groupDecimalText(value);
  if (!Number.isFinite(value)) return "数据无效";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 20 }).format(value);
}

export function formatProbability(value: number | null | undefined): string {
  if (value === null || value === undefined) return MISSING;
  if (!Number.isFinite(value) || value < 0 || value > 1) return "数据无效";
  if (value === 0) return "0%";

  const percent = value * 100;
  if (percent < 0.0001) {
    const [coefficient, exponent] = percent.toExponential(3).split("e");
    const conciseCoefficient = coefficient.replace(/(?:\.0+|(?<=\d)0+)$/, "").replace(/\.$/, "");
    return `${conciseCoefficient}e${Number(exponent)}%`;
  }
  return `${new Intl.NumberFormat("en-US", { maximumSignificantDigits: 4 }).format(percent)}%`;
}

export function formatQuantity(value: number | null | undefined): string {
  if (value === null || value === undefined) return MISSING;
  if (!Number.isFinite(value)) return "数据无效";
  return formatCount(value);
}

const JOB_STATUS_LABELS: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  completed: "已完成",
  cancelled: "已取消",
  failed: "失败",
};

const JOB_STAGE_LABELS: Record<string, string> = {
  simulating: "正在模拟",
  theory: "正在计算理论结果",
  validating: "正在校验结果",
  saving: "正在保存结果",
  committing: "正在提交结果",
};

function knownLabel(value: NullableText, labels: Record<string, string>, unknownKind: string): string {
  if (value === null || value === undefined) return MISSING;
  return labels[value] ?? `未知${unknownKind}（${value || "空值"}）`;
}

export function jobStatusLabel(status: NullableText): string {
  return knownLabel(status, JOB_STATUS_LABELS, "状态");
}

export function jobStageLabel(stage: NullableText): string {
  if (stage === null || stage === undefined) return "无进行中阶段";
  return knownLabel(stage, JOB_STAGE_LABELS, "阶段");
}

export function eventTypeLabel(eventType: NullableText): string {
  return knownLabel(eventType, { draw: "抽取", character_grant: "角色赠送" }, "事件类型");
}

export function sourceLabel(source: NullableText): string {
  return knownLabel(source, { main: "主池", bonus: "赠送池抽取" }, "来源");
}

export function mechanismLabel(mechanism: NullableText): string {
  return knownLabel(mechanism, {
    first_bonus: "首次赠送抽取",
    periodic_grant: "周期直接赠送",
  }, "机制");
}
