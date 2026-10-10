import { useEffect, useMemo, useState } from "react";
import { apiRequest, errorMessage } from "../api/client";
import type { ProcessEventRecord, ProcessEventDrawRecord, RunResult, TracePage } from "../api/types";
import { DownloadForm } from "./DownloadForm";
import { eventTypeLabel, formatCount, formatProbability, mechanismLabel, sourceLabel } from "../formatters";

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
  const [loadedData, setLoadedData] = useState<{ query: string; value: TracePage<ProcessEventRecord> } | null>(null);
  const [error, setError] = useState("");
  const [clearedSource, setClearedSource] = useState(false);
  const [retry, setRetry] = useState(0);
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
    const controller = new AbortController(); setLoadedData(null); setError("");
    void apiRequest<TracePage<ProcessEventRecord>>(`${base}/trace/?${query}`, {}, controller.signal)
      .then((next) => { if (!controller.signal.aborted) setLoadedData({ query: `${base}?${query}`, value: next }); })
      .catch((cause) => { if (!controller.signal.aborted) setError(errorMessage(cause)); });
    return () => controller.abort();
  }, [base, query, retry]);
  const data = loadedData?.query === `${base}?${query}` ? loadedData.value : null;
  const exactPages = data ? (BigInt(data.total) + BigInt(pageSize) - 1n) / BigInt(pageSize) : 1n;
  const pageCount = exactPages > MAX_PAGE ? MAX_PAGE : exactPages;
  const downloadFilter = filter as Record<string, unknown>;
  const stateText = (state: ProcessEventDrawRecord["main_state_before"]) =>
    `小保底：${rarities.map((item) => `${labels[item.id]} ${state.small_pity[item.id] == null && !item.soft_enabled && !item.hard_enabled ? "不适用" : formatCount(state.small_pity[item.id])}`).join("；")}；大保底未中 ${formatCount(state.big_misses)} 次（${state.big_active ? "有效" : "未生效"}）`;
  const pityText = (event: ProcessEventDrawRecord) => {
    const pity = event.draw_result.outcome.pity_status;
    return pity.soft_active.map((id) => `${labels[id] ?? id}软保底`).concat(
      pity.hard_active.map((id) => `${labels[id] ?? id}硬保底`), pity.big_forced ? ["大保底"] : [],
    ).join("、") || "无";
  };
  const rewardText = (event: ProcessEventDrawRecord) => result.pool_snapshot.rewards.map((reward) =>
    `${reward.name} ${formatCount(event.draw_result.outcome.rewards[reward.id])}`,
  ).join("；") || "无奖励";

  return <div className="page-stack">
    <div className="field-grid">
      <label className="compact-field">轮次<select value={trialMode} onChange={(event) => setTrialMode(event.target.value)}><option value="first">第1轮</option><option value="single">指定轮次</option><option value="range">轮次范围</option><option value="all">全部轮次</option></select></label>
      {trialMode !== "first" && trialMode !== "all" && <label className="compact-field">轮次起<input inputMode="numeric" value={trialFrom} onChange={(event) => setTrialFrom(event.target.value)} /></label>}
      {trialMode === "range" && <label className="compact-field">轮次止<input inputMode="numeric" value={trialTo} onChange={(event) => setTrialTo(event.target.value)} /></label>}
      <label className="compact-field">事件类型<select value={eventType} onChange={(event) => {
        const next = event.target.value; setEventType(next);
        if (next === "character_grant") { setClearedSource(Boolean(source || sourceFrom || sourceTo)); setSource(""); setSourceFrom(""); setSourceTo(""); }
        else setClearedSource(false);
      }}><option value="">全部</option><option value="draw">抽取</option><option value="character_grant">角色直接赠送</option></select></label>
      {eventType !== "character_grant" && <label className="compact-field">来源<select value={source} onChange={(event) => setSource(event.target.value)}><option value="">全部</option><option value="main">主池</option><option value="bonus">赠送池抽取</option></select></label>}
      <label className="compact-field">稀有度<select value={rarity} onChange={(event) => { setRarity(event.target.value); setCharacter(""); }}><option value="">全部</option>{rarities.map((item) => <option key={item.id} value={item.id}>{labels[item.id]}</option>)}</select></label>
      {rarity && <label className="compact-field">角色<select value={character} onChange={(event) => setCharacter(event.target.value)}><option value="">全部</option><option value="__unnamed__">未配置角色名单</option>{catalog.filter((item) => item.rarity === rarity).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}
      {eventType !== "character_grant" && <><label className="compact-field">来源抽次起<input inputMode="numeric" value={sourceFrom} onChange={(event) => setSourceFrom(event.target.value)} placeholder="不限" /></label>
      <label className="compact-field">来源抽次止<input inputMode="numeric" value={sourceTo} onChange={(event) => setSourceTo(event.target.value)} placeholder="不限" /></label></>}
      <label className="compact-field">每页条数<select value={pageSize} onChange={(event) => setPageSize(Number(event.target.value))}><option>50</option><option>100</option><option>200</option></select></label>
    </div>
    {eventType === "character_grant" && <p className="notice-note">直接赠送没有来源抽次。{clearedSource ? "已清除不适用的来源及来源抽次筛选。" : "来源及来源抽次筛选在此不适用。"}</p>}
    {eventType !== "character_grant" && source && <p className="muted">按来源筛选时仅包含抽取事件。</p>}
    <p className="muted">{data ? `匹配 ${formatCount(data.total)} 条 · 第 ${page}/${pageCount.toLocaleString("zh-CN")} 页` : error ? "过程明细读取失败" : "正在读取过程明细…"}</p>
    {error && <p className="form-error" role="alert">{error}</p>}
    {error && <button type="button" onClick={() => setRetry((value) => value + 1)}>重试读取</button>}
    {data?.items.length === 0 && <p role="status">当前筛选无记录，请调整或清除筛选。</p>}
    {data && data.items.length > 0 && <div className="table-wrap trace-table"><table><thead><tr><th>轮次</th><th>事件类型</th><th>累计主抽</th><th>来源</th><th>结果</th><th>奖励/赠送数量</th><th>保底触发</th><th>查看详情</th></tr></thead><tbody>
      {data.items.map((event) => <tr key={`${event.trial_index}-${event.event_index}`}>
        <td>{formatCount(event.trial_index)}</td><td>{eventTypeLabel(event.event_type)}</td><td>{formatCount(event.main_draws_completed)}</td>
        <td>{isDraw(event) ? sourceLabel(event.source) : "不适用"}</td>
        <td>{isDraw(event) ? `${labels[event.draw_result.outcome.rarity_id] ?? event.draw_result.outcome.rarity_id} · ${event.draw_result.outcome.character_name ?? "未配置角色名单"}` : `${labels[event.grant.rarity_id] ?? event.grant.rarity_id} · ${event.grant.character_name}`}</td>
        <td>{isDraw(event) ? rewardText(event) : `${formatCount(event.grant.quantity)} 名角色`}</td>
        <td>{isDraw(event) ? pityText(event) : "不适用"}</td>
        <td><details className="trace-details"><summary>查看详情</summary><dl>
          <dt>事件序号</dt><dd>{formatCount(event.event_index)}</dd>
          <dt>机制</dt><dd>{event.mechanism_id == null ? "无机制" : mechanismLabel(event.mechanism_id)}</dd>
          {isDraw(event) ? <>
            <dt>实际抽次</dt><dd>{formatCount(event.draw_index)}</dd><dt>来源内抽次</dt><dd>{formatCount(event.source_index)}</dd>
            <dt>各档条件概率</dt><dd>{Object.entries(event.draw_result.probabilities).map(([id, probability]) => <div key={id}>{labels[id] ?? id}：{formatProbability(probability)}（原值 {String(probability)}）</div>)}</dd>
            <dt>当前角色在该档内的概率</dt><dd>{event.draw_result.character_probability == null ? event.draw_result.outcome.character_id == null ? "不适用（未配置角色）" : "数据缺失" : `${formatProbability(event.draw_result.character_probability)}（原值 ${event.draw_result.character_probability}）`}</dd>
            <dt>来源抽前状态</dt><dd>{stateText(event.draw_result.state_before)}</dd><dt>来源抽后状态</dt><dd>{stateText(event.draw_result.state_after)}</dd>
            <dt>主池抽前状态</dt><dd>{stateText(event.main_state_before)}</dd><dt>主池抽后状态</dt><dd>{stateText(event.main_state_after)}</dd>
          </> : <><dt>触发主抽</dt><dd>{formatCount(event.grant.trigger_main_draw)}</dd><dt>抽取概率、来源状态</dt><dd>不适用（直接赠送不进行抽取）</dd></>}
        </dl></details></td>
      </tr>)}
    </tbody></table></div>}
    <div className="button-row"><button disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button><button disabled={BigInt(page) >= pageCount} onClick={() => setPage(page + 1)}>下一页</button></div>
    {runId ? <><p className="muted">JSONL包含冻结规则/角色池快照。若超过账号下载限额，请缩小事件、轮次或来源位置筛选。</p><DownloadForm runId={runId} filters={downloadFilter} matchingTotal={data?.total} limit={data?.download_limit} /></> : <p className="muted">任务保存为历史后可下载过程明细；当前仍可分页查看。</p>}
  </div>;
}
