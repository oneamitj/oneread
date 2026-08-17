import { useRef, useState } from "react";
import { api, ApiError } from "../api";
import { sizeOf } from "../format";
import type { Meta, Upload } from "../types";

interface Props {
  meta: Meta;
  /** The file already read, if one has been. */
  upload: Upload | null;
  onRead: (upload: Upload) => void;
  onClear: () => void;
  disabled?: boolean;
}

/**
 * Somewhere to put a document.
 *
 * Both gestures are here on purpose: dragging is what people reach for and
 * leaves no trace in the interface, so a plain button has to be visible too.
 * The whole sheet is a drop target as well, because aiming at a small rectangle
 * with a file in hand is a nuisance.
 */
export function FileDrop({ meta, upload, onRead, onClear, disabled }: Props) {
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);

  const accept = meta.upload_types.map((type) => type.ext).join(",");
  // Counted the way the server counts it. Rendered in round decimal megabytes
  // this reads "26.2 MB" against a setting of 25, which looks like a mistake.
  const limit = Math.round(meta.max_upload_bytes / (1024 * 1024));

  async function take(file: File | undefined) {
    if (!file || disabled) return;
    setError(null);
    setBusy(file.name);
    try {
      onRead(await api.upload(file));
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "That file couldn't be read.");
    } finally {
      setBusy(null);
      if (picker.current) picker.current.value = "";
    }
  }

  async function clear() {
    const going = upload;
    onClear();
    setError(null);
    if (going) await api.discardUpload(going.id).catch(() => undefined);
  }

  if (busy) {
    return (
      <div className="drop drop--busy" aria-live="polite">
        <span className="drop__spinner" aria-hidden="true" />
        <span>Reading {busy}…</span>
      </div>
    );
  }

  if (upload) {
    return (
      <div className="drop drop--done">
        <span className="drop__icon" aria-hidden="true"><PageGlyph /></span>
        <span className="drop__body">
          <strong>{upload.filename}</strong>
          <span>
            {sizeOf(upload.bytes)} · kept with this entry
            {upload.truncated ? " · read up to the limit" : ""}
          </span>
        </span>
        <button type="button" className="btn btn--quiet" onClick={clear}>
          Remove
        </button>
      </div>
    );
  }

  return (
    <>
      <div
        className={`drop${over ? " drop--over" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => {
          event.preventDefault();
          setOver(false);
          void take(event.dataTransfer.files[0]);
        }}
      >
        <span className="drop__icon" aria-hidden="true"><PageGlyph /></span>
        <span className="drop__body">
          <strong>Drop a document here</strong>
          <span>
            Word, slides, spreadsheets, PDF, markdown or plain text
            {/* Non-breaking, so a narrow sheet never leaves "MB" on a line of
                its own with nothing to belong to. */}
            {limit ? ` · up to ${limit} MB` : ""}
          </span>
        </span>
        <button
          type="button"
          className="btn btn--quiet"
          onClick={() => picker.current?.click()}
          disabled={disabled}
        >
          Choose a file
        </button>
        <input
          ref={picker}
          type="file"
          accept={accept}
          className="drop__input"
          onChange={(event) => void take(event.target.files?.[0])}
        />
      </div>
      {error ? <p className="error-text">{error}</p> : null}
    </>
  );
}

function PageGlyph() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <path
        d="M9 1.6H4.4A1.4 1.4 0 0 0 3 3v10a1.4 1.4 0 0 0 1.4 1.4h7.2A1.4 1.4 0 0 0 13 13V5.6L9 1.6Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinejoin="round"
      />
      <path d="M9 1.8v3.8h3.8" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}
