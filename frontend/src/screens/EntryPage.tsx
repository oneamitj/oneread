import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { EntryEditor } from "../components/EntryEditor";
import { GeneratePanel } from "../components/GeneratePanel";
import { ReadingCard } from "../components/ReadingCard";
import { TextPanels } from "../components/TextPanels";
import { usePolling } from "../hooks/usePolling";
import { characters, spell } from "../format";
import type { Entry, EntryDraft, Meta, ReadingRequest, Rendition } from "../types";

interface Props {
  entryId: string;
  meta: Meta;
  knownTags: string[];
  onBack: () => void;
  onGone: () => void;
}

export function EntryPage({ entryId, meta, knownTags, onBack, onGone }: Props) {
  const [entry, setEntry] = useState<Entry | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [planning, setPlanning] = useState(false);
  const [starting, setStarting] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const load = useCallback(async () => {
    try {
      setEntry(await api.get(entryId));
    } catch (problem) {
      if (problem instanceof ApiError && problem.status === 404) onGone();
      else setNotice(problem instanceof ApiError ? problem.message : "Couldn't load that.");
    }
  }, [entryId, onGone]);

  useEffect(() => { void load(); }, [load]);

  const busy = Boolean(
    entry?.renditions.some((r) => r.status === "pending" || r.status === "processing"),
  );
  usePolling(() => void load(), busy);

  useEffect(() => {
    if (!confirming) return;
    const timer = window.setTimeout(() => setConfirming(false), 4000);
    return () => window.clearTimeout(timer);
  }, [confirming]);

  const run = async (work: () => Promise<unknown>) => {
    try {
      await work();
      await load();
    } catch (problem) {
      setNotice(problem instanceof ApiError ? problem.message : "That didn't work.");
    }
  };

  const save = async (draft: EntryDraft) => {
    setSaving(true);
    setSaveError(null);
    try {
      await api.update(entryId, draft);
      setEditing(false);
      await load();
    } catch (problem) {
      setSaveError(problem instanceof ApiError ? problem.message : "Couldn't save that.");
    } finally {
      setSaving(false);
    }
  };

  const start = async (plan: ReadingRequest) => {
    setStarting(true);
    try {
      await api.read(entryId, plan);
      setPlanning(false);
      await load();
    } catch (problem) {
      setNotice(problem instanceof ApiError ? problem.message : "Couldn't start that.");
    } finally {
      setStarting(false);
    }
  };

  if (!entry) {
    return (
      <div className="page">
        <button type="button" className="btn btn--quiet page__back" onClick={onBack}>
          ← Library
        </button>
        <p className="hint">{notice ?? "Opening…"}</p>
      </div>
    );
  }

  const best = entry.renditions
    .filter((r) => r.status === "ready" || r.status === "stopped")
    .sort((a, b) => Number(b.complete) - Number(a.complete))[0];

  // Newest first. A recording being made now is the one worth watching, and
  // burying its progress bar under every older reading means scrolling to it.
  const readings = [...entry.renditions].sort(
    (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at),
  );

  return (
    <div className="page">
      <button type="button" className="btn btn--quiet page__back" onClick={onBack}>
        ← Library
      </button>

      <header className="page__head glass">
        <div className="page__titles">
          <h1>{entry.title}</h1>
          <p className="page__gist">
            {characters(entry.body.length)}
            {best?.duration_s ? ` · ${spell(best.duration_s)} of audio` : " · not read yet"}
          </p>
          <div className="page__chips">
            <span className="chip chip--static">{entry.voice}</span>
            <span className="chip chip--static">
              {entry.lang === "na" ? "auto language" : entry.lang}
            </span>
            <span className="chip chip--static">{entry.speed.toFixed(2)}× speed</span>
            {entry.format === "markdown" ? (
              <span className="chip chip--static">markdown</span>
            ) : null}
            {entry.tags.map((tag) => (
              <span key={tag} className="chip chip--tag">{tag}</span>
            ))}
          </div>
        </div>

        <div className="page__actions">
          {entry.locked ? (
            <span className="lockchip">Reading now, locked</span>
          ) : null}
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => setPlanning((shown) => !shown)}
            disabled={entry.locked}
          >
            {planning ? "Close" : "Make a recording"}
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => setEditing(true)}
            disabled={entry.locked}
          >
            Edit
          </button>
          <button
            type="button"
            className={`btn btn--quiet btn--danger${confirming ? " is-armed" : ""}`}
            disabled={entry.locked}
            onClick={() => {
              if (confirming) void run(async () => { await api.remove(entryId); onGone(); });
              else setConfirming(true);
            }}
          >
            {confirming ? "Really delete?" : "Delete"}
          </button>
        </div>
      </header>

      {notice ? <p className="notice glass glass--thin">{notice}</p> : null}

      {planning ? (
        <GeneratePanel
          entry={entry}
          meta={meta}
          starting={starting}
          onStart={(plan) => void start(plan)}
          onCancel={() => setPlanning(false)}
        />
      ) : null}

      <section className="page__section">
        <h2 className="page__h2">
          <span>Recordings</span>
          <span className="hint">
            {entry.renditions.length === 1
              ? "1 recording"
              : `${entry.renditions.length} recordings`}
          </span>
        </h2>
        {entry.renditions.length ? (
          <div className="readings">
            {readings.map((reading) => (
              <ReadingCard
                key={reading.id}
                entryTitle={entry.title}
                reading={reading}
                onStop={(r: Rendition) => void run(() => api.stop(r.id))}
                onDelete={(r: Rendition) => void run(() => api.dropRendition(r.id))}
              />
            ))}
          </div>
        ) : (
          <p className="empty-line glass glass--thin">
            Nothing has been read yet. Press “Make a recording” above to start one.
          </p>
        )}
      </section>

      <section className="page__section">
        <h2 className="page__h2">
          <span>The text</span>
        </h2>
        <TextPanels entry={entry} onEdit={() => setEditing(true)} />
      </section>

      {editing ? (
        <EntryEditor
          meta={meta}
          entry={entry}
          knownTags={knownTags}
          busy={saving}
          error={saveError}
          onSave={(draft) => void save(draft)}
          onClose={() => { setEditing(false); setSaveError(null); }}
        />
      ) : null}
    </div>
  );
}
