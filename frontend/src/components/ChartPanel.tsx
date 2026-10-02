import { useEffect, useRef, useState } from "react";
import vegaEmbed from "vega-embed";
import type { VisualizationSpec } from "vega-embed";
import { apiRequest, errorMessage } from "../api/client";
import type { RunResult } from "../api/types";

const categories = { rarity: "稀有度", categories: "角色类别", characters: "角色", rewards: "奖励", pity: "保底" } as const;
type Category = keyof typeof categories;
interface PositionRow {
  position: string;
  window_position: number;
  observations: string;
  [field: string]: string | number;
}
interface PositionChart { spec: unknown; rows: PositionRow[]; chart_approximate: boolean; rarity_labels: Record<string, string> }
interface SummaryCharts {
  specs: Record<Category, unknown | null>;
  rows: Record<Category, Array<Record<string, unknown>>>;
  chart_approximate?: boolean;
}

function inlineOnly(value: unknown): boolean {
  if (Array.isArray(value)) return value.every(inlineOnly);
  if (value && typeof value === "object") return Object.entries(value).every(([key, child]) => {
    if (key === "url" || key === "href") return false;
    if (key === "data" && child && typeof child === "object" && !Array.isArray(child) && !("values" in child)) return false;
    return inlineOnly(child);
  });
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
            void embedded.view.width(width).resize().runAsync().catch(() => { if (!disposed) setError("图表尺寸更新失败"); });
          });
        };
    observer = new ResizeObserver(resize); observer.observe(element.current!);
        window.addEventListener("resize", resize); resize();
      }).catch(() => { if (!disposed) setError("图表绘制失败"); });
    return () => { disposed = true; observer?.disconnect(); window.removeEventListener("resize", resize); cancelAnimationFrame(frame); finalize?.(); };
  }, [spec, responsiveHeight]);
  return <>{error && <p className="form-error" role="alert">{error}</p>}<div ref={element} className="chart-box" /></>;
}

function PositionTable({ rows, labels, selected, ruleRarities }: {
  rows: PositionRow[]; labels: Record<string, string>; selected: string[]; ruleRarities: Array<{ id: string; name: string }>;
}) {
  const [page, setPage] = useState(1);
  const pages = Math.max(1, Math.ceil(rows.length / 50));
  const indexes = Object.fromEntries(ruleRarities.map((rarity, index) => [rarity.id, `r${index}`]));
  const format = (value: string) => BigInt(value).toLocaleString("zh-CN");
  return <details className="position-values"><summary>查看数值表（{rows.length}个抽次）</summary>
    <p className="muted">比例为该位置出现次数 ÷ 有效轮数，不是理论条件概率。计数和位置以精确十进制文本展示。</p>
    <div className="table-wrap"><table><caption className="visually-hidden">按抽次模拟观察数值</caption>
      <thead><tr><th scope="col">来源内抽次</th><th scope="col">有效轮数</th>{selected.map((id) => <th scope="col" key={id}>{labels[id]}次数 / 比例</th>)}</tr></thead>
      <tbody>{rows.slice((page - 1) * 50, page * 50).map((row) => <tr key={row.position}>
        <th scope="row">{format(row.position)}</th><td>{format(row.observations)}</td>
        {selected.map((id) => <td key={id}>{format(String(row[`${indexes[id]}_count`]))} / {(Number(row[`${indexes[id]}_rate`]) * 100).toFixed(2)}%</td>)}</tr>)}</tbody>
    </table></div>
    <div className="button-row"><button disabled={page === 1} onClick={() => setPage(page - 1)}>上一页</button>
      <span role="status">第 {page} / {pages} 页，每页50个抽次</span>
      <button disabled={page === pages} onClick={() => setPage(page + 1)}>下一页</button></div>
  </details>;
}

export function ChartPanel({ base, result, mode }: { base: string; result: RunResult; mode: "summary" | "position" }) {
  const rarities = [...result.rule_snapshot.rarities].sort((a, b) => a.rank - b.rank);
  const labels = Object.fromEntries(rarities.map((rarity) => [rarity.id, result.pool_snapshot.rarity_labels[rarity.id] ?? rarity.name]));
  const [source, setSource] = useState<"main" | "bonus" | "total" | "grants" | "acquisitions">("total");
  const [category, setCategory] = useState<Category>("rarity");
  const [positionSource, setPositionSource] = useState<"main" | "bonus">("main");
  const [countMode, setCountMode] = useState<"count" | "rate">("count");
  const [selected, setSelected] = useState<string[]>(() => rarities.map((rarity) => rarity.id));
  const [trialFrom, setTrialFrom] = useState("1");
  const [trialTo, setTrialTo] = useState(result.parameters.trials);
  const [sourceFrom, setSourceFrom] = useState("1");
  const [sourceTo, setSourceTo] = useState("200");
  const [summary, setSummary] = useState<SummaryCharts | null>(null);
  const [position, setPosition] = useState<PositionChart | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (mode !== "summary") return;
    const controller = new AbortController(); setSummary(null); setError("");
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
    for (const rarity of selected) params.append("rarity_id", rarity);
    setPosition(null); setError("");
    void apiRequest<PositionChart>(`${base}/charts/?${params}`, {}, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setPosition(value); })
      .catch((cause) => { if (!controller.signal.aborted) setError(errorMessage(cause)); });
    return () => controller.abort();
  }, [base, mode, positionSource, countMode, selected, trialFrom, trialTo, sourceFrom, sourceTo, result.trace_enabled]);

  if (mode === "summary") {
    const rows = summary?.rows[category] ?? [];
    return <div className="page-stack"><div className="field-grid">
      <label className="compact-field">数据来源<select value={source} onChange={(event) => setSource(event.target.value as typeof source)}>
        <option value="main">主池抽取</option><option value="bonus">首次赠送抽取</option><option value="total">全部抽取</option><option value="grants">直接赠送</option><option value="acquisitions">全部角色获得</option>
      </select></label>
      <label className="compact-field">分类<select value={category} onChange={(event) => setCategory(event.target.value as Category)}>{Object.entries(categories).map(([key, title]) => <option key={key} value={key}>{title}</option>)}</select></label>
    </div><p className="muted">抽取统计包括抽数与概率；直接赠送没有抽取概率；全部角色获得合并抽取与赠送。</p>
      {error && <p className="form-error" role="alert">{error}</p>}
      {summary?.chart_approximate && <p className="notice-note">数值超出浏览器精确图形范围，图形近似显示；数值表优先保留服务端值。</p>}
      {summary?.specs[category] ? <VegaChart spec={summary.specs[category]} /> : <p className="muted">{category === "rewards" ? "此来源没有奖励统计。" : "暂无图表数据。"}</p>}
      {rows.length > 0 && <div className="table-wrap"><table><thead><tr>{Object.keys(rows[0]).map((key) => <th key={key}>{key}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{Object.entries(row).map(([key, value]) => <td key={key}>{key === "相对误差" ? (value === null ? "不可用" : `${(Number(value) * 100).toFixed(4)}%`) : value === null || value === undefined ? "—" : String(value)}</td>)}</tr>)}</tbody></table></div>}
    </div>;
  }
  if (!result.trace_enabled) return <p className="muted">本次运行未保存过程明细，无法进行按抽次分析。</p>;
  return <div className="page-stack"><div className="field-grid">
    <label className="compact-field">位置来源<select value={positionSource} onChange={(event) => setPositionSource(event.target.value as typeof positionSource)}><option value="main">主池</option><option value="bonus">赠送</option></select></label>
    <label className="compact-field">统计口径<select value={countMode} onChange={(event) => setCountMode(event.target.value as typeof countMode)}><option value="count">出现轮数</option><option value="rate">比例</option></select></label>
    <label className="compact-field">轮次起<input inputMode="numeric" value={trialFrom} onChange={(event) => setTrialFrom(event.target.value)} /></label>
    <label className="compact-field">轮次止<input inputMode="numeric" value={trialTo} onChange={(event) => setTrialTo(event.target.value)} /></label>
    <label className="compact-field">来源位置起<input inputMode="numeric" value={sourceFrom} onChange={(event) => setSourceFrom(event.target.value)} /></label>
    <label className="compact-field">来源位置止（最多1000个）<input inputMode="numeric" value={sourceTo} onChange={(event) => setSourceTo(event.target.value)} /></label>
  </div><fieldset className="plain-fieldset"><legend>稀有度（可多选）</legend><div className="button-row">{rarities.map((rarity) => <label className="inline-check" key={rarity.id}><input type="checkbox" checked={selected.includes(rarity.id)} onChange={() => setSelected(selected.includes(rarity.id) ? selected.filter((id) => id !== rarity.id) : [...selected, rarity.id])} />{labels[rarity.id]}</label>)}</div></fieldset>
    {selected.length === 0 ? <p role="status">请至少选择一种稀有度；筛选只改变图表，不会重新模拟。</p> : <>{error && <p className="form-error" role="alert">{error}</p>}{position && <>
      {position.rows.length === 0 ? <p role="status">所选范围没有逐抽数据，请调整筛选条件。</p> : <>
        <p className="muted">悬停任意抽次附近可查看原始抽次、有效轮数和所选稀有度次数；下方数值表保留精确整数。窗口坐标用于图形定位，原始十进制抽次显示在刻度与提示中。</p>
        {position.chart_approximate && <p className="notice-note">计数轴超出浏览器精确数值范围，图形为近似显示；下方表格仍显示精确值。</p>}
        <VegaChart spec={position.spec} responsiveHeight />
        <PositionTable rows={position.rows} labels={position.rarity_labels ?? labels} selected={selected} ruleRarities={rarities} />
      </>}
    </>}</>}
  </div>;
}
