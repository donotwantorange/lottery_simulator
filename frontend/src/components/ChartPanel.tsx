import { useEffect, useRef, useState } from "react";
import vegaEmbed from "vega-embed";
import type { VisualizationSpec } from "vega-embed";
import { apiRequest, errorMessage } from "../api/client";
import type { RunResult } from "../api/types";

const categories = {
  rarity: "星级", six_star_categories: "六星构成", characters: "六星具体角色",
  rewards: "奖励", pity: "保底",
} as const;
type Category = keyof typeof categories;

function inlineOnly(value: unknown): boolean {
  if (Array.isArray(value)) return value.every(inlineOnly);
  if (value && typeof value === "object") {
    return Object.entries(value).every(([key, child]) => {
      if (key === "url" || key === "href") return false;
      if (key === "data" && child && typeof child === "object" && !Array.isArray(child)) {
        const data = child as Record<string, unknown>;
        if (!("values" in data)) return false;
      }
      return inlineOnly(child);
    });
  }
  return true;
}

function VegaChart({ spec }: { spec: unknown }) {
  const element = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!element.current) return;
    if (!inlineOnly(spec)) { setError("图表数据必须由本地内联规格提供"); return; }
    let disposed = false;
    let finalize: (() => void) | undefined;
    setError("");
    void vegaEmbed(element.current, spec as VisualizationSpec, { actions: false, renderer: "svg" })
      .then((view) => { if (disposed) view.finalize(); else finalize = () => view.finalize(); })
      .catch(() => { if (!disposed) setError("图表绘制失败"); });
    return () => { disposed = true; finalize?.(); };
  }, [spec]);
  return <>{error && <p className="form-error" role="alert">{error}</p>}<div ref={element} className="chart-box" /></>;
}

interface SummaryCharts {
  specs: Record<Category, unknown | null>;
  rows: Record<Category, Array<Record<string, unknown>>>;
  rarity_labels: Record<"4" | "5" | "6", string>;
}

export function ChartPanel({ base, result, mode }: { base: string; result: RunResult; mode: "summary" | "position" }) {
  const [source, setSource] = useState<"main" | "bonus" | "total">("total");
  const [category, setCategory] = useState<Category>("rarity");
  const [positionSource, setPositionSource] = useState<"main" | "bonus">("main");
  const [countMode, setCountMode] = useState<"count" | "rate">("count");
  const [selected, setSelected] = useState<Array<"4" | "5" | "6">>(["4", "5", "6"]);
  const [trialFrom, setTrialFrom] = useState("1");
  const [trialTo, setTrialTo] = useState(String(result.trials));
  const [sourceFrom, setSourceFrom] = useState("1");
  const [sourceTo, setSourceTo] = useState("200");
  const [summary, setSummary] = useState<SummaryCharts | null>(null);
  const [position, setPosition] = useState<{ spec: unknown } | null>(null);
  const [error, setError] = useState("");
  const labels = result.pool_config.rarity_labels ?? { "4": "四星", "5": "五星", "6": "六星" };

  useEffect(() => {
    if (mode !== "summary") return;
    const controller = new AbortController();
    setSummary(null); setError("");
    void apiRequest<SummaryCharts>(`${base}/charts/?kind=summary&source=${source}`, {}, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setSummary(value); })
      .catch((cause) => { if (!controller.signal.aborted) setError(errorMessage(cause)); });
    return () => controller.abort();
  }, [base, mode, source]);

  useEffect(() => {
    if (mode !== "position" || selected.length === 0 || !result.trace_enabled) return;
    const controller = new AbortController();
    const params = new URLSearchParams({ kind: "position", source: positionSource, mode: countMode,
      trial_from: trialFrom, trial_to: trialTo, source_from: sourceFrom, source_to: sourceTo });
    for (const rarity of selected) params.append("rarity", rarity);
    setPosition(null); setError("");
    void apiRequest<{ spec: unknown }>(`${base}/charts/?${params}`, {}, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setPosition(value); })
      .catch((cause) => { if (!controller.signal.aborted) setError(errorMessage(cause)); });
    return () => controller.abort();
  }, [base, mode, positionSource, countMode, selected, trialFrom, trialTo, sourceFrom, sourceTo, result.trace_enabled]);

  if (mode === "summary") {
    const rows = summary?.rows[category] ?? [];
    return <div className="page-stack"><div className="field-grid">
      <label className="compact-field">数据来源<select value={source} onChange={(event) => setSource(event.target.value as typeof source)}><option value="main">主池</option><option value="bonus">赠送</option><option value="total">总计</option></select></label>
      <label className="compact-field">分类统计<select value={category} onChange={(event) => setCategory(event.target.value as Category)}>{Object.entries(categories).map(([key, title]) => <option key={key} value={key}>{key === "six_star_categories" ? `${labels["6"]}构成` : key === "characters" ? `${labels["6"]}具体角色` : title}</option>)}</select></label>
    </div>{error && <p className="form-error" role="alert">{error}</p>}
    {summary?.specs[category] ? <VegaChart spec={summary.specs[category]} /> : <p className="muted">{category === "rewards" ? "未配置奖励，暂无奖励统计。" : "暂无图表数据。"}</p>}
    {rows.length > 0 && <div className="table-wrap"><table><thead><tr>{Object.keys(rows[0]).map((key) => <th key={key}>{key}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{Object.values(row).map((value, cell) => <td key={cell}>{typeof value === "number" ? Number(value.toPrecision(12)) : String(value ?? "—")}</td>)}</tr>)}</tbody></table></div>}
    </div>;
  }
  if (!result.trace_enabled) return <p className="muted">本次运行未保存逐抽结果，无法进行按抽次分析。</p>;
  const maximum = positionSource === "main" ? result.main_draws : result.bonus_draws;
  return <div className="page-stack"><div className="field-grid">
    <label className="compact-field">位置来源<select value={positionSource} onChange={(event) => setPositionSource(event.target.value as typeof positionSource)}><option value="main">主池</option><option value="bonus">赠送</option></select></label>
    <label className="compact-field">统计口径<select value={countMode} onChange={(event) => setCountMode(event.target.value as typeof countMode)}><option value="count">计数</option><option value="rate">比例</option></select></label>
    <label className="compact-field">轮次起<input type="number" min="1" max={result.trials} value={trialFrom} onChange={(event) => setTrialFrom(event.target.value)} /></label>
    <label className="compact-field">轮次止<input type="number" min="1" max={result.trials} value={trialTo} onChange={(event) => setTrialTo(event.target.value)} /></label>
    <label className="compact-field">来源位置起<input type="number" min="1" max={maximum} value={sourceFrom} onChange={(event) => setSourceFrom(event.target.value)} /></label>
    <label className="compact-field">来源位置止（最多1000个）<input type="number" min="1" max={maximum} value={sourceTo} onChange={(event) => setSourceTo(event.target.value)} /></label>
  </div><fieldset className="plain-fieldset"><legend>稀有度（可多选）</legend><div className="button-row">{(["4", "5", "6"] as const).map((key) => <label className="inline-check" key={key}><input type="checkbox" checked={selected.includes(key)} onChange={() => setSelected(selected.includes(key) ? selected.filter((item) => item !== key) : [...selected, key])} />{labels[key]}</label>)}</div></fieldset>
    {selected.length === 0 ? <p role="status">请至少选择一种稀有度；筛选只改变图表，不会重新模拟。</p> : <>{error && <p className="form-error" role="alert">{error}</p>}{position?.spec && <VegaChart spec={position.spec} />}</>}
  </div>;
}
