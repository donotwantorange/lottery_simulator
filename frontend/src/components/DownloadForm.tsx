import { useRef, useState, type FormEvent } from "react";
import { currentCsrfToken, errorMessage } from "../api/client";

export function DownloadForm({ runId, filters }: { runId: string; filters: Record<string, unknown> }) {
  const form = useRef<HTMLFormElement>(null);
  const token = useRef<HTMLInputElement>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

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
    <input ref={token} type="hidden" name="csrfmiddlewaretoken" />
    <input type="hidden" name="filters" value={JSON.stringify(filters)} />
    <button type="submit" disabled={busy}>{busy ? "正在准备…" : "在新标签页下载 Trace JSONL"}</button>
    {error && <p className="form-error" role="alert">{error}</p>}
  </form>;
}
