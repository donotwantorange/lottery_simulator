import { useState, type ChangeEvent } from "react";

interface Props {
  label: string;
  onImport(rawJson: string): Promise<void>;
  disabled?: boolean;
}

export function ImportDialog({ label, onImport, disabled = false }: Props) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function change(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || disabled || pending) return;
    setError("");
    if (file.size > 5 * 1024 * 1024) {
      setError("JSON文件不能超过5 MiB");
      return;
    }
    setPending(true);
    try {
      await onImport(await file.text());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "导入失败");
    } finally {
      setPending(false);
    }
  }

  return <div className="import-control" aria-busy={pending}>
    <label className="secondary-button">{pending ? "正在导入…" : label}
      <input type="file" accept=".json,application/json" onChange={(event) => void change(event)} disabled={disabled || pending} className="visually-hidden" />
    </label>
    {error && <p className="form-error" role="alert" aria-live="assertive">{error}</p>}
  </div>;
}
