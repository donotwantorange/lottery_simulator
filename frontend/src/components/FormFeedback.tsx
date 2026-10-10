import type { ReactNode } from "react";
import { ApiError } from "../api/client";

export interface FieldIssue { id: string; label: string; message: string; reveal?: () => void }

export function apiFieldIssues(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || !error.fields) return {};
  const result: Record<string, string> = {};
  const visit = (path: string, value: unknown) => {
    if (typeof value === "string") { result[path] = value; return; }
    if (Array.isArray(value)) {
      if (value.every((part) => typeof part === "string")) result[path] = value.join("；");
      else value.forEach((part, index) => visit(`${path}.${index}`, part));
      return;
    }
    if (value && typeof value === "object") Object.entries(value).forEach(([key, part]) => visit(path ? `${path}.${key}` : key, part));
  };
  visit("", error.fields);
  return result;
}

export function FormFeedback({ error, issues, children }: { error?: string; issues?: FieldIssue[]; children?: ReactNode }) {
  if (!error && !issues?.length && !children) return null;
  return <div className="form-feedback" role="alert">
    {issues?.length ? <><strong>有{issues.length}项需要处理</strong><ul>{issues.map((issue) => <li key={issue.id}><button type="button" className="link-button" onClick={() => {
      issue.reveal?.();
      requestAnimationFrame(() => document.getElementById(issue.id)?.focus());
    }}>{issue.label}：{issue.message}</button></li>)}</ul></> : null}
    {error && <p>{error}</p>}{children}
  </div>;
}

export function ReadonlyValue({ label, value }: { label: string; value: ReactNode }) {
  return <div className="readonly-value"><span className="muted">{label}</span><strong>{value}</strong></div>;
}
