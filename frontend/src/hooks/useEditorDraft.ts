import { useCallback, useEffect, useState } from "react";
import { useBlocker } from "react-router-dom";

export interface NumberDraft {
  text: string;
  lastLegal: number;
  error: string;
}

export function useNumberDrafts() {
  const [fields, setFields] = useState<Record<string, NumberDraft>>({});
  const update = useCallback((id: string, field: NumberDraft) => {
    setFields((current) => ({ ...current, [id]: field }));
  }, []);
  const discard = useCallback((id: string) => {
    setFields((current) => {
      const next = { ...current };
      delete next[id];
      return next;
    });
  }, []);
  const removeMatching = useCallback((fragment: string) => {
    setFields((current) => Object.fromEntries(Object.entries(current).filter(([id]) => !id.includes(fragment))));
  }, []);
  const clear = useCallback(() => setFields({}), []);
  return { fields, update, discard, removeMatching, clear, hasInvalid: Object.values(fields).some((field) => !!field.error) };
}

export function useEditorDraft<T>(initial: T) {
  const [value, setValue] = useState(initial);
  const [baseline, setBaseline] = useState(initial);
  const [unfinished, setUnfinished] = useState(false);
  const dirty = unfinished || JSON.stringify(value) !== JSON.stringify(baseline);
  const reset = useCallback((next: T) => {
    setValue(next);
    setBaseline(structuredClone(next));
    setUnfinished(false);
  }, []);
  const markSaved = useCallback((next: T) => reset(next), [reset]);
  return { value, setValue, baseline, dirty, reset, markSaved, setUnfinished };
}

export function confirmDiscard(dirty: boolean): boolean {
  return !dirty || window.confirm("有未保存修改。放弃修改并继续吗？");
}

export function useUnsavedNavigation(dirty: boolean) {
  const blocker = useBlocker(({ nextLocation }) => dirty && !nextLocation.pathname.startsWith("/accounts/"));
  useEffect(() => {
    if (!dirty) return;
    const unload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", unload);
    return () => window.removeEventListener("beforeunload", unload);
  }, [dirty]);
  useEffect(() => {
    if (blocker.state !== "blocked") return;
    if (confirmDiscard(true)) blocker.proceed();
    else blocker.reset();
  }, [blocker]);
}
