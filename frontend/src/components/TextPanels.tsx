import { useEffect, useState } from "react";
import { api, sourceUrl, spokenTextUrl } from "../api";
import { sizeOf } from "../format";
import type { Entry } from "../types";
import { FileKind, kindOf } from "./FileKind";
import { DownGlyph } from "./Glyphs";

interface Props {
  entry: Entry;
  /** Opens the editor. The hint below says "edit it", so the word does it. */
  onEdit: () => void;
}

type Which = "spoken" | "source";

/**
 * Two views of the same entry: what you started with, and what the voice made of
 * it. For markdown and for files those differ, and the second is the only way to
 * check a table or a code fence landed right.
 */
export function TextPanels({ entry, onEdit }: Props) {
  const markdown = entry.format === "markdown";
  const [which, setWhich] = useState<Which>(markdown ? "spoken" : "source");
  const [spoken, setSpoken] = useState<string | null>(entry.spoken);
  const [failed, setFailed] = useState(false);

  useEffect(() => { setSpoken(entry.spoken); }, [entry.spoken]);

  // Nothing has been read yet, so work it out rather than showing an empty panel.
  useEffect(() => {
    if (spoken !== null || which !== "spoken" || failed) return;
    let cancelled = false;
    api
      .spokenText(entry.body, entry.format)
      .then((result) => { if (!cancelled) setSpoken(result.text); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [spoken, which, failed, entry.body, entry.format]);

  const shown = which === "source" ? entry.body : spoken;
  const count = shown?.length ?? 0;
  const source = entry.source;
  const kind = source ? kindOf(source.name) : null;

  return (
    <>
      <div className="switchrow">
        <div className="switchrow__left">
          <div className="segmented" role="radiogroup" aria-label="Which text to show">
            <button
              type="button"
              role="radio"
              aria-checked={which === "spoken"}
              className="segmented__option"
              onClick={() => setWhich("spoken")}
            >
              What it reads
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={which === "source"}
              className="segmented__option"
              onClick={() => setWhich("source")}
            >
              {source ? "From the file" : markdown ? "Your markdown" : "Your text"}
            </button>
          </div>

          {source && kind ? (
            <a
              className="filepill"
              href={sourceUrl(entry.id)}
              download={source.name}
              title={`Download ${source.name}`}
            >
              <FileKind kind={kind} />
              <span className="filepill__name">{source.name}</span>
              <span className="filepill__type">
                {kind.label}
                {sizeOf(source.bytes) ? ` · ${sizeOf(source.bytes)}` : ""}
              </span>
              <DownGlyph />
            </a>
          ) : null}
        </div>

        <span className="switchrow__right">
          <span className="hint">{count.toLocaleString()} characters</span>
          <a className="filepill filepill--plain" href={spokenTextUrl(entry.id)} download>
            <DownGlyph />
            <span className="filepill__name">Save as text</span>
          </a>
        </span>
      </div>

      <p className="hint">
        {which === "spoken" ? (
          markdown ? (
            "Headings, lists and tables turned into sentences. This is what the voice sees."
          ) : (
            "Read exactly as written, give or take symbols a voice can't pronounce."
          )
        ) : source ? (
          <>
            Taken out of {source.name}.{" "}
            {entry.locked ? (
              "Edit it"
            ) : (
              // Ordinary prose until you point at it: the word says what it does.
              <button type="button" className="inlink" onClick={onEdit}>
                Edit it
              </button>
            )}{" "}
            any time; the file itself stays put.
          </>
        ) : (
          "Your original, untouched."
        )}
      </p>

      <div className="panel glass glass--thin">
        {shown ?? (failed ? "Couldn't work that out." : "Working it out…")}
      </div>
    </>
  );
}
