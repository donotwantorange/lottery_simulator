import type { ExperimentParameters } from "../api/types";

interface Props {
  value: ExperimentParameters;
  onChange(value: ExperimentParameters): void;
}

export const initialParameters: ExperimentParameters = {
  draws: "100", trials: "1000", initial_pity: "0", initial_five_star_pity: "0", seed: null, trace: false,
};

export function validateParameters(value: ExperimentParameters): string | null {
  for (const [field, label, positive] of [
    ["draws", "每轮主池抽数", true], ["trials", "实验轮数", true],
    ["initial_pity", "六星保底进度", false], ["initial_five_star_pity", "五星保底进度", false],
  ] as const) {
    const text = value[field];
    if (!/^(0|[1-9][0-9]*)$/.test(text) || (positive && text === "0")) return `${label}必须是${positive ? "正" : "非负"}整数字符串`;
  }
  if (value.seed !== null && !/^-?(0|[1-9][0-9]*)$/.test(value.seed)) return "随机种子必须是十进制整数";
  return null;
}

export function ExperimentForm({ value, onChange }: Props) {
  function update<K extends keyof ExperimentParameters>(key: K, next: ExperimentParameters[K]) {
    onChange({ ...value, [key]: next });
  }
  return <div className="field-grid">
    <label>每轮主池抽数<input inputMode="numeric" value={value.draws} onChange={(event) => update("draws", event.target.value)} /></label>
    <label>实验轮数<input inputMode="numeric" value={value.trials} onChange={(event) => update("trials", event.target.value)} /></label>
    <label>假设主池已累计多少抽仍未出6星<input inputMode="numeric" value={value.initial_pity} onChange={(event) => update("initial_pity", event.target.value)} /></label>
    <label>假设已连续多少抽未出5星或以上<input inputMode="numeric" value={value.initial_five_star_pity} onChange={(event) => update("initial_five_star_pity", event.target.value)} /></label>
    <label>随机种子（可留空）<input inputMode="numeric" value={value.seed ?? ""} onChange={(event) => update("seed", event.target.value === "" ? null : event.target.value)} /></label>
    <label className="inline-check"><input type="checkbox" checked={value.trace} onChange={(event) => update("trace", event.target.checked)} />保存每抽明细（Trace）</label>
  </div>;
}
