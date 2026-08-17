import { downloadUrl, srtUrl, vttUrl } from "../api";
import { fileSize } from "../format";
import type { Rendition } from "../types";

interface Props {
  reading: Rendition;
}

/**
 * The files, sitting in the open next to the recording they belong to.
 * Nobody outside video work knows what an SRT is, so each row says what it's
 * for and leaves the extension as a footnote.
 */
export function DownloadCard({ reading }: Props) {
  const size = fileSize(reading.duration_s);

  return (
    <aside className="files glass glass--thin">
      <h4 className="files__head">Download</h4>

      <div className="files__list">
        <a href={downloadUrl(reading.id)} download>
          <span className="files__icon" aria-hidden="true"><WaveGlyph /></span>
          <span className="files__body">
            <strong>The audio</strong>
            <span>Plays anywhere{size ? ` · ${size}` : ""}</span>
          </span>
          <span className="files__ext">WAV</span>
        </a>

        <a href={srtUrl(reading.id)} download>
          <span className="files__icon" aria-hidden="true"><TextGlyph /></span>
          <span className="files__body">
            <strong>Subtitles</strong>
            <span>Timed text for video players and editors</span>
          </span>
          <span className="files__ext">SRT</span>
        </a>

        <a href={vttUrl(reading.id)} download>
          <span className="files__icon" aria-hidden="true"><TextGlyph /></span>
          <span className="files__body">
            <strong>Subtitles for the web</strong>
            <span>The format browsers use</span>
          </span>
          <span className="files__ext">VTT</span>
        </a>
      </div>
    </aside>
  );
}

function WaveGlyph() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <path
        d="M2 8h1.6M5.2 4.4v7.2M8 2.4v11.2M10.8 5.6v4.8M13.6 7.2v1.6"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

function TextGlyph() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <rect x="2" y="3" width="12" height="10" rx="2" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M4.6 9.4h3M9 9.4h2.4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}
