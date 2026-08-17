import { useMemo } from "react";
import { clock } from "../format";
import type { Segment } from "../types";

interface Props {
  segments: Segment[];
  start: number;
  end: number;
  onChange: (start: number, end: number) => void;
}

/**
 * Two thumbs over the sentence list. The slider counts sentences rather than
 * seconds, so a range can only ever begin and end on a whole one, and the
 * timeline underneath shows where that lands in the finished audio.
 */
export function RangePicker({ segments, start, end, onChange }: Props) {
  const last = segments.length;
  const total = segments.length ? segments[segments.length - 1].end_s : 0;

  const span = useMemo(() => {
    const from = segments[start];
    const to = segments[Math.min(end, last) - 1];
    return {
      from,
      to,
      seconds: from && to ? Math.max(0, to.end_s - from.start_s) : 0,
      left: from && total ? (from.start_s / total) * 100 : 0,
      width: from && to && total ? ((to.end_s - from.start_s) / total) * 100 : 0,
    };
  }, [segments, start, end, last, total]);

  return (
    <div className="range">
      <div className="range__track">
        <div
          className="range__span"
          style={{ left: `${span.left}%`, width: `${span.width}%` }}
        />
        <input
          type="range"
          className="range__input range__input--start"
          min={0}
          max={last - 1}
          value={start}
          aria-label="First sentence"
          onChange={(event) => {
            const next = Number(event.target.value);
            onChange(Math.min(next, end - 1), end);
          }}
        />
        <input
          type="range"
          className="range__input range__input--end"
          min={1}
          max={last}
          value={end}
          aria-label="Last sentence"
          onChange={(event) => {
            const next = Number(event.target.value);
            onChange(start, Math.max(next, start + 1));
          }}
        />
      </div>

      <div className="range__scale">
        <span>0:00</span>
        <span>{clock(total)}</span>
      </div>

      <div className="range__ends">
        <div className="range__end">
          <span className="range__label">Starts at</span>
          <p className="range__quote">{span.from?.text ?? "—"}</p>
          <span className="hint">
            sentence {start + 1} · {clock(span.from?.start_s ?? 0)}
          </span>
        </div>
        <div className="range__end">
          <span className="range__label">Ends after</span>
          <p className="range__quote">{span.to?.text ?? "—"}</p>
          <span className="hint">
            sentence {Math.min(end, last)} · {clock(span.to?.end_s ?? 0)}
          </span>
        </div>
      </div>

      <div className="range__jump">
        <button type="button" className="chip" onClick={() => onChange(0, last)}>
          Everything
        </button>
        <button
          type="button"
          className="chip"
          onClick={() => onChange(0, Math.min(last, Math.ceil(last / 2)))}
        >
          First half
        </button>
        <button
          type="button"
          className="chip"
          onClick={() => onChange(Math.floor(last / 2), last)}
        >
          Second half
        </button>
        <span className="hint range__count">
          {end - start} of {last} sentences · about {clock(span.seconds)}
        </span>
      </div>
    </div>
  );
}
