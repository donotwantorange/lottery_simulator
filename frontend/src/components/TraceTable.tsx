import { useEffect, useMemo, useState } from "react";
import { apiRequest, errorMessage } from "../api/client";
import type { Page, RunResult, TraceRecord } from "../api/types";
import { DownloadForm } from "./DownloadForm";

const rarityKeys = ["4", "5", "6"] as const;

export function TraceTable({ base, runId, result }: { base: string; runId?: string | null; result: RunResult }) {
  const labels = result.pool_config.rarity_labels ?? { "4": "四星", "5": "五星", "6": "六星" };
  const [trialMode, setTrialMode] = useState("first");
  const [trialFrom, setTrialFrom] = useState("1");
  const [trialTo, setTrialTo] = useState("1");
  const [source, setSource] = useState("");
  const [rarity, setRarity] = useState("");
  const [character, setCharacter] = useState("");
  const [sourceFrom, setSourceFrom] = useState("");
  const [sourceTo, setSourceTo] = useState("");
  const [pageSize, setPageSize] = useState(100);
  const [full, setFull] = useState(false);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Page<TraceRecord> | null>(null);
  const [error, setError] = useState("");
  const catalog = useMemo(() => rarityKeys.flatMap((key) => {
    const field = key === "4" ? "four_star_characters" : key === "5" ? "five_star_characters" : "six_star_characters";
    return result.pool_config[field].map((item) => ({ rarity: key, name: item.name }));
  }), [result]);
  const filter = useMemo(() => {
    const values: Record<string, string | number | boolean> = {};
    if (trialMode !== "all") {
      values.trial_from = trialMode === "first" ? 1 : trialFrom;
      values.trial_to = trialMode === "first" ? 1 : trialMode === "single" ? trialFrom : trialTo;
    }
    if (source) values.source = source;
    if (rarity) values.rarity = Number(rarity);
    if (character === "__unnamed__") values.unnamed_character = true;
    else if (character) values.character_name = character;
    if (sourceFrom) values.source_from = sourceFrom;
    if (sourceTo) values.source_to = sourceTo;
    return values;
  }, [trialMode, trialFrom, trialTo, source, rarity, character, sourceFrom, sourceTo]);
  const query = useMemo(() => {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    for (const [key, value] of Object.entries(filter)) {
      if (key !== "unnamed_character" && key !== "character_name") params.set(key, String(value));
    }
    if (filter.character_name) params.set("character_name", String(filter.character_name));
    if (filter.unnamed_character) params.set("unnamed_character", "true");
    return params.toString();
  }, [filter, page, pageSize]);

  useEffect(() => { setPage(1); }, [trialMode, trialFrom, trialTo, source, rarity, character, sourceFrom, sourceTo, pageSize, base]);
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError("");
    void apiRequest<Page<TraceRecord>>(`${base}/trace/?${query}`, {}, controller.signal)
      .then((next) => { if (!controller.signal.aborted) setData(next); })
      .catch((cause) => { if (!controller.signal.aborted) setError(errorMessage(cause)); });
    return () => controller.abort();
  }, [base, query]);
  const pageCount = Math.max(1, Math.ceil((data?.total ?? 0) / pageSize));

  return <div className="page-stack">
    <div className="field-grid">
      <label className="compact-field">轮次<select value={trialMode} onChange={(event) => setTrialMode(event.target.value)}><option value="first">第1轮</option><option value="single">指定轮次</option><option value="range">轮次范围</option><option value="all">全部轮次</option></select></label>
      {trialMode !== "first" && trialMode !== "all" && <label className="compact-field">轮次起<input type="number" min="1" max={result.trials} value={trialFrom} onChange={(event) => setTrialFrom(event.target.value)} /></label>}
      {trialMode === "range" && <label className="compact-field">轮次止<input type="number" min="1" max={result.trials} value={trialTo} onChange={(event) => setTrialTo(event.target.value)} /></label>}
      <label className="compact-field">来源<select value={source} onChange={(event) => setSource(event.target.value)}><option value="">全部</option><option value="main">主池</option><option value="bonus">赠送</option></select></label>
      <label className="compact-field">稀有度<select value={rarity} onChange={(event) => { setRarity(event.target.value); setCharacter(""); }}><option value="">全部</option>{rarityKeys.map((key) => <option key={key} value={key}>{labels[key]}</option>)}</select></label>
      {rarity && <label className="compact-field">角色<select value={character} onChange={(event) => setCharacter(event.target.value)}><option value="">全部</option><option value="__unnamed__">未配置角色名单</option>{catalog.filter((item) => item.rarity === rarity).map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}</select></label>}
      <label className="compact-field">来源抽次起<input type="number" min="1" value={sourceFrom} onChange={(event) => setSourceFrom(event.target.value)} placeholder="不限" /></label>
      <label className="compact-field">来源抽次止<input type="number" min="1" value={sourceTo} onChange={(event) => setSourceTo(event.target.value)} placeholder="不限" /></label>
      <label className="compact-field">每页条数<select value={pageSize} onChange={(event) => setPageSize(Number(event.target.value))}><option>50</option><option>100</option><option>200</option></select></label>
      <label className="compact-field">明细列<select value={full ? "full" : "basic"} onChange={(event) => setFull(event.target.value === "full")}><option value="basic">基础列</option><option value="full">完整列</option></select></label>
    </div>
    {full && <p className="muted">{labels["4"]}、{labels["5"]}、{labels["6"]}条件概率保持 0～1 数值尺度；0 表示 0%，1 表示 100%。</p>}
    <p className="muted">{data ? `匹配 ${data.total} 条 · 第 ${page}/${pageCount} 页` : "正在读取逐抽明细…"}</p>
    {error && <p className="form-error" role="alert">{error}</p>}
    {data && <div className="table-wrap"><table><thead><tr><th>轮次</th><th>轮内抽次</th><th>来源</th><th>来源内序号</th><th>稀有度</th><th>角色</th><th>主池累计抽数</th><th>UP</th><th>限定</th>{full && <><th>{labels["4"]}概率</th><th>{labels["5"]}概率</th><th>{labels["6"]}概率</th><th>来源抽前{labels["6"]}未出</th><th>来源抽前{labels["5"]}未出</th><th>来源抽后{labels["6"]}未出</th><th>来源抽后{labels["5"]}未出</th><th>主池抽前{labels["6"]}未出</th><th>主池抽前{labels["5"]}未出</th><th>主池抽后{labels["6"]}未出</th><th>主池抽后{labels["5"]}未出</th><th>{labels["5"]}保底</th><th>{labels["6"]}硬保底</th><th>赠送事件</th></>}{result.pool_config.rewards.map((item) => <th key={item.name}>奖励：{item.name}</th>)}</tr></thead><tbody>
      {data.items.map((row) => <tr key={`${row.trial_index}-${row.draw_index}`}><td>{row.trial_index}</td><td>{row.draw_index}</td><td>{row.source === "main" ? "主池" : "赠送"}</td><td>{row.source_index}</td><td>{labels[String(row.draw_result.outcome.rarity) as "4" | "5" | "6"]}</td><td>{row.draw_result.outcome.character_name ?? "未配置角色名单"}</td><td>{row.main_draws_completed}</td><td>{row.draw_result.outcome.is_up ? "是" : "否"}</td><td>{row.draw_result.outcome.is_limited ? "是" : "否"}</td>{full && <><td>{row.draw_result.probabilities.four_star}</td><td>{row.draw_result.probabilities.five_star}</td><td>{row.draw_result.probabilities.six_star}</td><td>{row.draw_result.state_before.misses_since_six_star}</td><td>{row.draw_result.state_before.misses_since_five_or_higher}</td><td>{row.draw_result.state_after.misses_since_six_star}</td><td>{row.draw_result.state_after.misses_since_five_or_higher}</td><td>{row.main_state_before.misses_since_six_star}</td><td>{row.main_state_before.misses_since_five_or_higher}</td><td>{row.main_state_after.misses_since_six_star}</td><td>{row.main_state_after.misses_since_five_or_higher}</td><td>{row.draw_result.outcome.five_star_pity_triggered ? "是" : "否"}</td><td>{row.draw_result.outcome.six_star_hard_pity_triggered ? "是" : "否"}</td><td>{row.bonus_event ?? "—"}</td></>}{result.pool_config.rewards.map((item) => <td key={item.name}>{row.draw_result.outcome.rewards[item.name] ?? 0}</td>)}</tr>)}
    </tbody></table></div>}
    <div className="button-row"><button disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button><button disabled={page >= pageCount} onClick={() => setPage(page + 1)}>下一页</button></div>
    {runId ? <><p className="muted">下载为 JSONL；首行包含本次池快照与{labels["4"]}/{labels["5"]}/{labels["6"]}名称，记录字段保留内部稀有度 4/5/6。</p><DownloadForm runId={runId} filters={filter} /></> : <p className="muted">任务保存为历史后可下载 Trace；当前仍可分页查看。</p>}
  </div>;
}
