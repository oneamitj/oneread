import { ago, localTime, spell } from "../format";
import type { Rendition } from "../types";
import { CoverageStrip } from "./CoverageStrip";
import { GlassPlayer } from "./GlassPlayer";

interface Props {
  entryTitle: string;
  reading: Rendition;
  onStop: (reading: Rendition) => void;
  onDelete: (reading: Rendition) => void;
}

/** Plain words for what this recording is. No jargon, no scope, no status enum. */
function headline(reading: Rendition): string {
  if (reading.status === "pending") return "Waiting to start";
  if (reading.status === "processing") return "Reading it out";
  if (reading.status === "failed") return "This one didn't work";
  if (reading.complete) return "The whole thing";
  if (reading.scope === "sample") {
    const minutes = (reading.limit_s ?? 60) / 60;
    return minutes === 1 ? "The first minute" : `The first ${minutes} minutes`;
  }
  return "Stopped part way";
}

function subtitle(reading: Rendition): string {
  const parts: string[] = [];
  if (reading.duration_s) parts.push(spell(reading.duration_s));
  parts.push(`${reading.voice} at ${reading.speed.toFixed(2)}×`);
  return parts.join(" · ");
}

export function ReadingCard({ entryTitle, reading, onStop, onDelete }: Props) {
  const live = reading.status === "pending" || reading.status === "processing";
  const playable = reading.status === "ready" || reading.status === "stopped";
  const percent = Math.round(reading.progress * 100);

  return (
    <article className={`reading glass glass--thin is-${reading.status}`}>
      <header className="reading__head">
        <div>
          <h3 className="reading__title">{headline(reading)}</h3>
          <p className="reading__sub">{live ? "Just started" : subtitle(reading)}</p>
        </div>
        <div className="reading__marks">
          {reading.is_default ? <span className="pill">Plays by default</span> : null}
          {reading.complete ? (
            <span className="tick" title="Covers the whole text">✓</span>
          ) : null}
        </div>
      </header>

      {live ? (
        <div className="reading__running">
          <div
            className="bar"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
            aria-label="Reading progress"
          >
            <div className="bar__fill" style={{ transform: `scaleX(${reading.progress})` }} />
          </div>
          <div className="reading__foot">
            <span className="hint">
              {reading.segments_total
                ? `${percent}% · line ${reading.segments_done.toLocaleString()} of ${reading.segments_total.toLocaleString()}`
                : "Getting started"}
            </span>
            <button
              type="button"
              className="btn btn--quiet"
              onClick={() => onStop(reading)}
              disabled={reading.stop_requested}
            >
              {reading.stop_requested ? "Stopping…" : "Stop and keep this much"}
            </button>
          </div>
        </div>
      ) : null}

      {playable ? (
        <GlassPlayer
          renditionId={reading.id}
          title={entryTitle}
          duration={reading.duration_s ?? 0}
        />
      ) : null}

      {playable ? <CoverageStrip reading={reading} /> : null}

      {playable && reading.opening ? (
        <blockquote className="opening">
          <span aria-hidden="true">“</span>
          {reading.opening}
          <span aria-hidden="true">…”</span>
        </blockquote>
      ) : null}

      {reading.error ? (
        <p className={reading.status === "failed" ? "error-text" : "hint"}>{reading.error}</p>
      ) : null}

      {playable ? (
        <div className="reading__foot">
          <span className="hint" title={localTime(reading.created_at)}>
            Made {ago(reading.created_at)}
            {reading.wall_s ? ` · took ${spell(reading.wall_s)}` : ""}
          </span>
          {/* Removing the default would leave the entry with nothing to play. */}
          {!reading.is_default ? (
            <button
              type="button"
              className="btn btn--quiet btn--danger"
              onClick={() => onDelete(reading)}
            >
              Remove
            </button>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}
