import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { TextFormat } from "../types";

interface Props {
  text: string;
  format: TextFormat;
}

/**
 * Shows the flattened text, so you can check how a table or a code fence is
 * going to land before spending a generation on it.
 */
export function SpokenPreview({ text, format }: Props) {
  const [open, setOpen] = useState(false);
  const [spoken, setSpoken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !text.trim()) { setSpoken(null); return; }
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const result = await api.spokenText(text, format);
        if (!cancelled) { setSpoken(result.text); setError(null); }
      } catch (problem) {
        if (!cancelled) {
          setError(problem instanceof ApiError ? problem.message : "Couldn't work that out.");
        }
      }
    }, 250);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [open, text, format]);

  return (
    <div className="spoken">
      <button
        type="button"
        className="btn btn--quiet spoken__toggle"
        onClick={() => setOpen((shown) => !shown)}
        aria-expanded={open}
      >
        {open ? "Hide what gets read" : "See what gets read"}
      </button>
      {open ? (
        <div className="spoken__body">
          {error ? (
            <p className="error-text">{error}</p>
          ) : spoken ? (
            <pre className="spoken__text">{spoken}</pre>
          ) : (
            <p className="hint">
              {text.trim() ? "Working it out…" : "Nothing to read yet."}
            </p>
          )}
        </div>
      ) : null}
    </div>
  );
}
