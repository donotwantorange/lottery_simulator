import type { ExperimentParameters } from "../api/types";
import defaultExperiment from "../../../configs/experiments/default.json";

interface Props {
  value: ExperimentParameters;
  onChange(value: ExperimentParameters): void;
}

export const initialParameters: ExperimentParameters = {
  ...defaultExperiment.parameters,
  draws: String(defaultExperiment.parameters.draws), trials: String(defaultExperiment.parameters.trials),
  seed: null, initial_main_draws: String(defaultExperiment.parameters.initial_main_draws),
  initial_small_pity: Object.fromEntries(Object.entries(defaultExperiment.parameters.initial_small_pity).map(([id, count]) => [id, String(count)])),
  initial_big_pity: { ...defaultExperiment.parameters.initial_big_pity, misses: String(defaultExperiment.parameters.initial_big_pity.misses) },
};

export function validateParameters(value: ExperimentParameters): string | null {
  for (const [text, label, positive] of [
    [value.draws, "每轮主抽数", true], [value.trials, "实验轮数", true], [value.initial_main_draws, "历史主抽数", false],
    ...Object.values(value.initial_small_pity).map((item) => [item, "小保底初始计数", false] as const),
    [value.initial_big_pity.misses, "大保底未命中数", false],
  ] as const) {
    if (!/^(0|[1-9][0-9]*)$/.test(text) || (positive && text === "0")) return `${label}必须是${positive ? "正" : "非负"}十进制整数字符串`;
  }
  if (value.seed !== null && !/^-?(0|[1-9][0-9]*)$/.test(value.seed)) return "随机种子必须是十进制整数";
  if (value.seed === "0") return "随机种子不能为0";
  return null;
}

export function ExperimentForm({ value, onChange }: Props) {
  function update<K extends keyof ExperimentParameters>(key: K, next: ExperimentParameters[K]) {
    onChange({ ...value, [key]: next });
  }
  return <div className="field-grid">
    <label>每轮主池抽数<input inputMode="numeric" value={value.draws} onChange={(event) => update("draws", event.target.value)} /></label>
    <label>实验轮数<input inputMode="numeric" value={value.trials} onChange={(event) => update("trials", event.target.value)} /></label>
    <label>随机种子（可留空，由系统生成）<input inputMode="numeric" value={value.seed ?? ""} onChange={(event) => update("seed", event.target.value === "" ? null : event.target.value)} /></label>
    <label className="inline-check"><input type="checkbox" checked={value.trace} onChange={(event) => update("trace", event.target.checked)} />保存全过程明细（Trace）</label>
  </div>;
}
