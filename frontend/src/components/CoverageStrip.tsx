import type { Rendition } from "../types";

interface Props {
  reading: Rendition;
}

/**
 * Which slice of the document this recording is. Two readings called "the first
 * minute" look identical in a list; as bars they don't.
 */
export function CoverageStrip({ reading }: Props) {
  const total = reading.document_segments;
  if (!total) return null; // made before readings tracked this

  const from = Math.min(reading.start_segment, total);
  const to = Math.min(from + Math.max(reading.segments_done, 1), total);
  const left = (from / total) * 100;
  const width = Math.max(1.5, ((to - from) / total) * 100);
  const share = Math.round(((to - from) / total) * 100);

  const where =
    to - from === total
      ? "The whole document"
      : from === 0
        ? `Opens the document · sentences 1 to ${to} of ${total}`
        : `Sentences ${from + 1} to ${to} of ${total}`;

  return (
    <div className="cover">
      <div className="cover__row">
        <span className="cover__label">Covers</span>
        <span className="cover__share">{share < 1 ? "under 1%" : `${share}%`}</span>
      </div>
      <div
        className="cover__track"
        role="img"
        aria-label={`${where}, ${share}% of the text`}
      >
        <div className="cover__fill" style={{ left: `${left}%`, width: `${width}%` }} />
      </div>
      <span className="hint">{where}</span>
    </div>
  );
}
