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

export function VegaChart({ spec, responsiveHeight = false }: { spec: unknown; responsiveHeight?: boolean }) {
  const element = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!element.current) return;
    if (!inlineOnly(spec)) { setError("图表数据必须由本地内联规格提供"); return; }
    let disposed = false;
    let finalize: (() => void) | undefined;
    let observer: ResizeObserver | undefined;
    let frame = 0;
    let resize = () => {};
    setError("");
    void vegaEmbed(element.current, spec as VisualizationSpec, { actions: false, renderer: "svg" })
      .then((embedded) => {
        if (disposed) { embedded.finalize(); return; }
        finalize = () => embedded.finalize();
        resize = () => {
          cancelAnimationFrame(frame);
          frame = requestAnimationFrame(() => {
            if (disposed || !element.current) return;
            const width = element.current.clientWidth;
            if (width <= 0) return;
            if (responsiveHeight) embedded.view.height(Math.max(320, Math.min(600, window.innerHeight * 0.55)));
            void embedded.view.width(width).resize().runAsync().catch(() => {
              if (!disposed) setError("图表尺寸更新失败");
            });
          });
        };
        observer = new ResizeObserver(resize);
        observer.observe(element.current!);
        window.addEventListener("resize", resize);
        resize();
      })
      .catch(() => { if (!disposed) setError("图表绘制失败"); });
    return () => {
      disposed = true; observer?.disconnect(); window.removeEventListener("resize", resize);
      cancelAnimationFrame(frame); finalize?.();
    };
  }, [spec, responsiveHeight]);
  return <>{error && <p className="form-error" role="alert">{error}</p>}<div ref={element} className="chart-box" /></>;
}

interface PositionRow {
  position: number;
  observations: number;
  four_count?: number; four_rate?: number;
  five_count?: number; five_rate?: number;
  six_count?: number; six_rate?: number;
}
interface PositionChart { spec: unknown; rows: PositionRow[] }

function PositionTable({ rows, labels, selected }: {
  rows: PositionRow[]; labels: Record<"4" | "5" | "6", string>; selected: Array<"4" | "5" | "6">;
}) {
  const [page, setPage] = useState(1);
  const fields = { "4": "four", "5": "five", "6": "six" } as const;
  const pages = Math.max(1, Math.ceil(rows.length / 50));
  const formatCount = (n: number) => n.toLocaleString("zh-CN");
  return <details className="position-values"><summary>查看数值表（{rows.length}个抽次）</summary>
    <p className="muted">比例为该位置出现次数 ÷ 有效轮数，不是理论条件概率。</p>
    <div className="table-wrap"><table><caption className="visually-hidden">按抽次模拟观察数值</caption>
      <thead><tr><th scope="col">来源内抽次</th><th scope="col">有效轮数</th>{selected.map(rarity =>
        <th scope="col" key={rarity}>{labels[rarity]}次数 / 比例</th>)}</tr></thead>
      <tbody>{rows.slice((page - 1) * 50, page * 50).map(row => <tr key={row.position}>
        <th scope="row">{formatCount(row.position)}</th><td>{formatCount(row.observations)}</td>
        {selected.map(rarity => <td key={rarity}>
          {formatCount(row[`${fields[rarity]}_count`] ?? 0)} / {((row[`${fields[rarity]}_rate`] ?? 0) * 100).toFixed(2)}%
        </td>)}</tr>)}</tbody></table></div>
    <div className="button-row"><button disabled={page === 1} onClick={() => setPage(page - 1)}>上一页</button>
      <span role="status">第{page} / {pages}页，每页50个抽次</span>
      <button disabled={page === pages} onClick={() => setPage(page + 1)}>下一页</button></div>
  </details>;
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
  const [position, setPosition] = useState<PositionChart | null>(null);
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
    void apiRequest<PositionChart>(`${base}/charts/?${params}`, {}, controller.signal)
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
    {selected.length === 0 ? <p role="status">请至少选择一种稀有度；筛选只改变图表，不会重新模拟。</p> : <>{error && <p className="form-error" role="alert">{error}</p>}{position?.spec && <>
      {position.rows.length === 0 ? <p role="status">所选范围没有逐抽数据，请调整筛选条件。</p> : <>
        <p className="muted">悬停任意抽次附近可查看所选星级的次数、比例和有效轮数；也可展开下方数值表。</p>
        <VegaChart spec={position.spec} responsiveHeight />
        <PositionTable rows={position.rows} labels={labels} selected={selected} />
      </>}
    </>}</>}
  </div>;
}
