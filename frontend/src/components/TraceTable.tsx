import { useEffect, useMemo, useState } from "react";
import { apiRequest, errorMessage } from "../api/client";
import type { ProcessEventRecord, ProcessEventDrawRecord, RunResult, TracePage } from "../api/types";
import { DownloadForm } from "./DownloadForm";

const MAX_PAGE = 2_147_483_647n;
const isDraw = (event: ProcessEventRecord): event is ProcessEventDrawRecord => event.event_type === "draw";

export function TraceTable({ base, runId, result }: { base: string; runId?: string | null; result: RunResult }) {
  const rarities = [...result.rule_snapshot.rarities].sort((a, b) => a.rank - b.rank);
  const labels = Object.fromEntries(rarities.map((rarity) => [rarity.id, result.pool_snapshot.rarity_labels[rarity.id] ?? rarity.name]));
  const [trialMode, setTrialMode] = useState("first");
  const [trialFrom, setTrialFrom] = useState("1");
  const [trialTo, setTrialTo] = useState("1");
  const [eventType, setEventType] = useState("");
  const [source, setSource] = useState("");
  const [rarity, setRarity] = useState("");
  const [character, setCharacter] = useState("");
  const [sourceFrom, setSourceFrom] = useState("");
  const [sourceTo, setSourceTo] = useState("");
  const [pageSize, setPageSize] = useState(100);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<TracePage<ProcessEventRecord> | null>(null);
  const [error, setError] = useState("");
  const catalog = useMemo(() => result.pool_snapshot.rarity_pools.flatMap((group) =>
    group.characters.map((item) => ({ rarity: group.rarity_id, id: item.id, name: item.name })),
  ), [result]);
  const filter = useMemo(() => {
    const values: Record<string, string | boolean> = {};
    if (trialMode !== "all") {
      values.trial_from = trialMode === "first" ? "1" : trialFrom;
      values.trial_to = trialMode === "first" ? "1" : trialMode === "single" ? trialFrom : trialTo;
    }
    if (eventType) values.event_type = eventType;
    if (eventType !== "character_grant") {
      if (source) values.source = source;
      if (sourceFrom) values.source_from = sourceFrom;
      if (sourceTo) values.source_to = sourceTo;
    }
    if (rarity) values.rarity_id = rarity;
    if (character === "__unnamed__") values.unnamed_character = true;
    else if (character) values.character_id = character;
    return values;
  }, [trialMode, trialFrom, trialTo, eventType, source, rarity, character, sourceFrom, sourceTo]);
  const query = useMemo(() => new URLSearchParams({ page: String(page), page_size: String(pageSize),
    ...Object.fromEntries(Object.entries(filter).map(([key, value]) => [key, String(value)])),
  }).toString(), [filter, page, pageSize]);

  useEffect(() => { setPage(1); }, [trialMode, trialFrom, trialTo, eventType, source, rarity, character, sourceFrom, sourceTo, pageSize, base]);
  useEffect(() => {
    const controller = new AbortController(); setData(null); setError("");
    void apiRequest<TracePage<ProcessEventRecord>>(`${base}/trace/?${query}`, {}, controller.signal)
      .then((next) => { if (!controller.signal.aborted) setData(next); })
      .catch((cause) => { if (!controller.signal.aborted) setError(errorMessage(cause)); });
    return () => controller.abort();
  }, [base, query]);
  const exactPages = data ? (BigInt(data.total) + BigInt(pageSize) - 1n) / BigInt(pageSize) : 1n;
  const pageCount = exactPages > MAX_PAGE ? MAX_PAGE : exactPages;
  const downloadFilter = filter as Record<string, unknown>;

  return <div className="page-stack">
    <div className="field-grid">
      <label className="compact-field">轮次<select value={trialMode} onChange={(event) => setTrialMode(event.target.value)}><option value="first">第1轮</option><option value="single">指定轮次</option><option value="range">轮次范围</option><option value="all">全部轮次</option></select></label>
      {trialMode !== "first" && trialMode !== "all" && <label className="compact-field">轮次起<input inputMode="numeric" value={trialFrom} onChange={(event) => setTrialFrom(event.target.value)} /></label>}
      {trialMode === "range" && <label className="compact-field">轮次止<input inputMode="numeric" value={trialTo} onChange={(event) => setTrialTo(event.target.value)} /></label>}
      <label className="compact-field">事件类型<select value={eventType} onChange={(event) => {
        const next = event.target.value; setEventType(next);
        if (next === "character_grant") { setSource(""); setSourceFrom(""); setSourceTo(""); }
      }}><option value="">全部</option><option value="draw">抽取</option><option value="character_grant">角色直接赠送</option></select></label>
      <label className="compact-field">来源<select disabled={eventType === "character_grant"} value={source} onChange={(event) => setSource(event.target.value)}><option value="">全部</option><option value="main">主池</option><option value="bonus">赠送池抽取</option></select></label>
      <label className="compact-field">稀有度<select value={rarity} onChange={(event) => { setRarity(event.target.value); setCharacter(""); }}><option value="">全部</option>{rarities.map((item) => <option key={item.id} value={item.id}>{labels[item.id]}</option>)}</select></label>
      {rarity && <label className="compact-field">角色<select value={character} onChange={(event) => setCharacter(event.target.value)}><option value="">全部</option><option value="__unnamed__">未配置角色名单</option>{catalog.filter((item) => item.rarity === rarity).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}
      <label className="compact-field">来源抽次起<input disabled={eventType === "character_grant"} inputMode="numeric" value={sourceFrom} onChange={(event) => setSourceFrom(event.target.value)} placeholder="不限" /></label>
      <label className="compact-field">来源抽次止<input disabled={eventType === "character_grant"} inputMode="numeric" value={sourceTo} onChange={(event) => setSourceTo(event.target.value)} placeholder="不限" /></label>
      <label className="compact-field">每页条数<select value={pageSize} onChange={(event) => setPageSize(Number(event.target.value))}><option>50</option><option>100</option><option>200</option></select></label>
    </div>
    <p className="muted">{data ? `匹配 ${BigInt(data.total).toLocaleString("zh-CN")} 条 · 第 ${page}/${pageCount.toLocaleString("zh-CN")} 页` : "正在读取过程明细…"}</p>
    {error && <p className="form-error" role="alert">{error}</p>}
    {data && <div className="table-wrap"><table><thead><tr><th>轮次</th><th>事件序号</th><th>事件类型</th><th>主池累计抽数</th><th>抽次 / 直接赠送</th><th>来源</th><th>来源内序号</th><th>稀有度</th><th>角色</th><th>抽取概率</th><th>奖励</th><th>保底状态</th><th>机制</th></tr></thead><tbody>
      {data.items.map((event) => isDraw(event) ? <tr key={`${event.trial_index}-${event.event_index}`}>
        <td>{event.trial_index}</td><td>{event.event_index}</td><td>抽取</td><td>{event.main_draws_completed}</td><td>{event.draw_index}</td>
        <td>{event.source === "main" ? "主池" : "赠送池"}</td><td>{event.source_index}</td>
        <td>{labels[event.draw_result.outcome.rarity_id] ?? event.draw_result.outcome.rarity_id}</td>
        <td>{event.draw_result.outcome.character_name ?? "未配置角色名单"}</td>
        <td>{Object.entries(event.draw_result.probabilities).map(([id, probability]) => `${labels[id] ?? id} ${probability}`).join("；")}</td>
        <td>{result.pool_snapshot.rewards.map((reward) => `${reward.name} ${event.draw_result.outcome.rewards[reward.id] ?? 0}`).join("；") || "—"}</td>
        <td>来源小保底 {rarities.map((item) => `${labels[item.id]} ${event.draw_result.state_before.small_pity[item.id] ?? "0"}→${event.draw_result.state_after.small_pity[item.id] ?? "0"}`).join("；")}；主池小保底 {rarities.map((item) => `${labels[item.id]} ${event.main_state_before.small_pity[item.id] ?? "0"}→${event.main_state_after.small_pity[item.id] ?? "0"}`).join("；")}；来源大保底 {event.draw_result.state_before.big_misses}→{event.draw_result.state_after.big_misses}（{event.draw_result.state_before.big_active ? "有效" : "无效"}→{event.draw_result.state_after.big_active ? "有效" : "无效"}）；触发 {event.draw_result.outcome.pity_status.soft_active.map((id) => `${labels[id]}软保底`).concat(event.draw_result.outcome.pity_status.hard_active.map((id) => `${labels[id]}硬保底`), event.draw_result.outcome.pity_status.big_forced ? ["大保底"] : []).join("、") || "无"}</td>
        <td>{event.mechanism_id ?? "—"}</td>
      </tr> : <tr key={`${event.trial_index}-${event.event_index}`}>
        <td>{event.trial_index}</td><td>{event.event_index}</td><td>直接赠送角色</td><td>{event.main_draws_completed}</td>
        <td>不适用 · 赠送数量 <span>{event.grant.quantity}</span></td><td>不适用</td><td>不适用</td>
        <td>{labels[event.grant.rarity_id] ?? event.grant.rarity_id}</td><td>{event.grant.character_name}</td>
        <td>不适用</td><td>不适用</td><td>不适用</td><td>{event.mechanism_id ?? "—"}</td>
      </tr>)}
    </tbody></table></div>}
    <div className="button-row"><button disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button><button disabled={BigInt(page) >= pageCount} onClick={() => setPage(page + 1)}>下一页</button></div>
    {runId ? <><p className="muted">JSONL包含冻结规则/角色池快照。若超过账号下载限额，请缩小事件、轮次或来源位置筛选。</p><DownloadForm runId={runId} filters={downloadFilter} /></> : <p className="muted">任务保存为历史后可下载过程明细；当前仍可分页查看。</p>}
  </div>;
}
