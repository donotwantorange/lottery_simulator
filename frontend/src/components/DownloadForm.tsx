import { useRef, useState, type FormEvent } from "react";
import { currentCsrfToken, errorMessage } from "../api/client";
import { formatCount } from "../formatters";

export function DownloadForm({ runId, filters, matchingTotal, limit }: { runId: string; filters: Record<string, unknown>; matchingTotal?: string; limit?: string | null }) {
  const form = useRef<HTMLFormElement>(null);
  const token = useRef<HTMLInputElement>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const overLimit = matchingTotal != null && limit != null && BigInt(matchingTotal) > BigInt(limit);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const target = `trace-download-${crypto.randomUUID()}`;
    const tab = window.open("", target);
    if (!tab) { setError("浏览器阻止了下载标签页，请允许弹窗后重试"); return; }
    setBusy(true); setError("");
    try {
      // The browser owns the response stream; no fetch/blob copy of the Trace is made.
      if (token.current) token.current.value = await currentCsrfToken();
      if (!form.current) { tab.close(); return; }
      form.current.target = target;
      form.current.submit();
    } catch (cause) {
      tab.close();
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return <form ref={form} method="post" action={`/api/v1/runs/${encodeURIComponent(runId)}/download-trace/`}
    target="_blank" onSubmit={(event) => void submit(event)}>
    <p className="muted">下载当前筛选结果：{matchingTotal == null ? "正在查询匹配条数" : `${formatCount(matchingTotal)} 条`}；当前账号适用限额：{limit === undefined ? "由服务端校验" : limit === null ? "无上限" : `${formatCount(limit)} 条`}。</p>
    <input ref={token} type="hidden" name="csrfmiddlewaretoken" />
    <input type="hidden" name="filters" value={JSON.stringify(filters)} />
    <button type="submit" disabled={busy || matchingTotal == null || overLimit}>{busy ? "正在准备…" : "下载当前筛选结果（Trace JSONL）"}</button>
    {overLimit && <p className="notice-note">当前筛选匹配数超过适用下载限额，请缩小范围。</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
  </form>;
}
