import { useEffect, useState } from "react";
import { characters, spell } from "../format";
import type { EntrySummary } from "../types";
import { MiniPlayer } from "./MiniPlayer";

interface Props {
  summary: EntrySummary;
  onOpen: (id: string) => void;
  onTagClick: (tag: string) => void;
  onDelete: (summary: EntrySummary) => void;
}

const ACTIVE_LABEL: Record<string, string> = {
  pending: "In line",
  processing: "Reading",
};

export function EntryCard({ summary, onOpen, onTagClick, onDelete }: Props) {
  const { playable, active } = summary;
  const failed = !playable && !active;
  // Two presses, same as the entry's own page. A card is one careless click
  // from a whole document, and there is no undo behind it.
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    if (!confirming) return;
    const timer = window.setTimeout(() => setConfirming(false), 4000);
    return () => window.clearTimeout(timer);
  }, [confirming]);

  return (
    <article
      className={`card glass${summary.locked ? " is-locked" : ""}`}
      onClick={() => onOpen(summary.id)}
      role="link"
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen(summary.id);
        }
      }}
    >
      <h3 className="card__title">{summary.title}</h3>
      <p className="card__excerpt">{summary.excerpt}</p>

      {/* One slot, one height, whatever is in it — so every footer lines up. */}
      <div className="card__slot">
        {playable ? (
          <MiniPlayer
            renditionId={playable.id}
            title={summary.title}
            duration={playable.duration_s ?? 0}
          />
        ) : active ? (
          <div className="card__working">
            <span className="status status--processing">
              <span className="status__pulse" aria-hidden="true" />
              {ACTIVE_LABEL[active.status] ?? "Working"}
              {active.status === "processing" ? ` ${Math.round(active.progress * 100)}%` : ""}
            </span>
            <div className="bar">
              <div
                className="bar__fill"
                style={{ transform: `scaleX(${active.progress})` }}
              />
            </div>
          </div>
        ) : failed ? (
          <p className="card__working error-text">No audio. Open it to see why.</p>
        ) : null}
      </div>

      <div className="card__tags" onClick={(event) => event.stopPropagation()}>
        {summary.tags.slice(0, 3).map((tag) => (
          <button key={tag} type="button" className="chip" onClick={() => onTagClick(tag)}>
            {tag}
          </button>
        ))}
      </div>

      <footer className="card__foot">
        <button
          type="button"
          className={`btn btn--quiet btn--danger btn--small${confirming ? " is-armed" : ""}`}
          disabled={summary.locked}
          title={summary.locked ? "A full reading is running. It has to finish first." : undefined}
          onClick={(event) => {
            event.stopPropagation();
            if (confirming) onDelete(summary);
            else setConfirming(true);
          }}
        >
          {confirming ? "Really delete?" : "Delete"}
        </button>
        <span className="card__meta">
          {characters(summary.body_chars)}
          {playable?.duration_s ? ` · ${spell(playable.duration_s)}` : ""}
          {summary.rendition_count > 1 ? ` · ${summary.rendition_count} readings` : ""}
        </span>
      </footer>
    </article>
  );
}
