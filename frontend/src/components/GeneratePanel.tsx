import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api";
import { spell } from "../format";
import { languageOptions } from "../languages";
import type {
  Entry,
  Estimate,
  Meta,
  ReadingMode,
  ReadingRequest,
  Scope,
  SegmentList,
} from "../types";
import { RangePicker } from "./RangePicker";
import { VoicePreview } from "./VoicePreview";

interface Props {
  entry: Entry;
  meta: Meta;
  onStart: (plan: ReadingRequest) => void;
  onCancel: () => void;
  starting: boolean;
}

const MODES: { id: Scope; label: string; blurb: string }[] = [
  { id: "sample", label: "A taster", blurb: "The opening few minutes." },
  { id: "range", label: "A section", blurb: "Pick where it starts and stops." },
  { id: "full", label: "Everything", blurb: "The document end to end." },
];

const STYLES: { id: ReadingMode; label: string; blurb: string }[] = [
  {
    id: "sentence",
    label: "Default",
    blurb: "One sentence at a time. Every subtitle line is one sentence.",
  },
  {
    id: "paragraph",
    label: "Refined",
    blurb:
      "Reads a few sentences in one breath, so a paragraph runs on the way a " +
      "person would read it. The voice places those pauses itself, and one " +
      "subtitle line covers the whole group. Experimental.",
  },
];

export function GeneratePanel({ entry, meta, onStart, onCancel, starting }: Props) {
  // A taster first: it is the cheap answer to "is this voice right?"
  const [mode, setMode] = useState<Scope>("sample");
  const [style, setStyle] = useState<ReadingMode>("sentence");
  const [minutes, setMinutes] = useState(meta.sample_minutes);
  const [voice, setVoice] = useState(entry.voice);
  const [lang, setLang] = useState(entry.lang);
  const [speed, setSpeed] = useState(entry.speed);

  const [list, setList] = useState<SegmentList | null>(null);
  const [range, setRange] = useState<[number, number] | null>(null);
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [error, setError] = useState<string | null>(null);

  // The sentence list is the document again, so it's only fetched if someone
  // actually wants to pick a section out of it.
  useEffect(() => {
    if (mode !== "range" || list) return;
    let cancelled = false;
    api
      .segments(entry.id, speed)
      .then((result) => {
        if (cancelled) return;
        setList(result);
        setRange([0, Math.min(result.segments.length, Math.ceil(result.segments.length / 4))]);
      })
      .catch((problem) => {
        if (!cancelled) {
          setError(problem instanceof ApiError ? problem.message : "Couldn't read the text.");
        }
      });
    return () => { cancelled = true; };
  }, [mode, list, entry.id, speed]);

  const plan = useMemo<ReadingRequest>(() => {
    const base = { voice, lang, speed, mode: style };
    if (mode === "sample") return { ...base, scope: "sample", minutes };
    if (mode === "range" && range) {
      return { ...base, scope: "range", start: range[0], end: range[1] };
    }
    return { ...base, scope: mode };
  }, [mode, minutes, range, voice, lang, speed, style]);

  useEffect(() => {
    if (mode === "range" && !range) return;
    let cancelled = false;
    setEstimate(null);
    const timer = window.setTimeout(() => {
      api
        .estimate(entry.id, plan)
        .then((result) => { if (!cancelled) { setEstimate(result); setError(null); } })
        .catch((problem) => {
          if (!cancelled) {
            setError(problem instanceof ApiError ? problem.message : "Couldn't work it out.");
          }
        });
    }, 200);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [entry.id, plan, mode, range]);

  const languages = useMemo(() => languageOptions(meta.languages), [meta.languages]);

  const ready = Boolean(estimate) && (mode !== "range" || Boolean(range));

  return (
    <section className="gen glass">
      <header className="gen__head">
        <h3>Make a recording</h3>
        <button type="button" className="btn btn--quiet" onClick={onCancel}>
          Close
        </button>
      </header>

      <div className="gen__modes">
        {MODES.map((choice) => (
          <button
            key={choice.id}
            type="button"
            className={`mode${mode === choice.id ? " is-on" : ""}`}
            aria-pressed={mode === choice.id}
            onClick={() => setMode(choice.id)}
          >
            <strong>{choice.label}</strong>
            <span>{choice.blurb}</span>
          </button>
        ))}
      </div>

      {mode === "sample" ? (
        <div className="gen__block">
          <span className="label">How much</span>
          <div className="segmented" role="radiogroup" aria-label="Sample length">
            {meta.sample_minute_choices.map((option) => (
              <button
                key={option}
                type="button"
                role="radio"
                aria-checked={minutes === option}
                className="segmented__option"
                onClick={() => setMinutes(option)}
              >
                {option} min
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {mode === "range" ? (
        <div className="gen__block">
          {list && range ? (
            <RangePicker
              segments={list.segments}
              start={range[0]}
              end={range[1]}
              onChange={(from, to) => setRange([from, to])}
            />
          ) : (
            <p className="hint">Working out where the sentences are…</p>
          )}
        </div>
      ) : null}

      <div className="gen__block">
        <span className="label">Style</span>
        <div className="segmented" role="radiogroup" aria-label="Reading style">
          {STYLES.map((choice) => (
            <button
              key={choice.id}
              type="button"
              role="radio"
              aria-checked={style === choice.id}
              className="segmented__option"
              onClick={() => setStyle(choice.id)}
            >
              {choice.label}
              {choice.id === "paragraph" ? " (experimental)" : ""}
            </button>
          ))}
        </div>
        <p className="hint">
          {STYLES.find((choice) => choice.id === style)?.blurb}
        </p>
      </div>

      <div className="gen__block gen__voice">
        <div>
          <label className="label" htmlFor="gen-voice">Voice</label>
          <select
            id="gen-voice"
            className="field"
            value={voice}
            onChange={(event) => setVoice(event.target.value)}
          >
            {meta.voices.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label} ({option.id})
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="gen-lang">Language</label>
          <select
            id="gen-lang"
            className="field"
            value={lang}
            onChange={(event) => setLang(event.target.value)}
          >
            {languages.map((option) => (
              <option key={option.code} value={option.code}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <div className="sheet__labelrow">
            <label className="label" htmlFor="gen-speed">Speed</label>
            <span className="hint">{speed.toFixed(2)}&times;</span>
          </div>
          <input
            id="gen-speed"
            className="slider"
            type="range"
            min={meta.min_speed}
            max={meta.max_speed}
            step={0.05}
            value={speed}
            onChange={(event) => setSpeed(Number(event.target.value))}
          />
        </div>
      </div>

      <VoicePreview
        voice={voice}
        lang={lang}
        speed={speed}
        text={entry.spoken ?? entry.body}
        format={entry.spoken ? "plain" : entry.format}
      />

      <footer className="gen__foot">
        <dl className="gen__facts">
          <div>
            <dt>Audio</dt>
            <dd>{estimate ? spell(estimate.audio_s) : "…"}</dd>
          </div>
          <div>
            <dt>Takes about</dt>
            <dd>{estimate ? spell(estimate.wall_s) : "…"}</dd>
          </div>
          <div>
            <dt>Lines</dt>
            <dd>{estimate ? estimate.segments.toLocaleString() : "…"}</dd>
          </div>
        </dl>
        <button
          type="button"
          className="btn btn--primary"
          onClick={() => onStart(plan)}
          disabled={starting || !ready}
        >
          {starting ? "Starting…" : "Start reading"}
        </button>
      </footer>

      {error ? <p className="error-text">{error}</p> : null}
      <p className="hint">
        {estimate?.measured
          ? "Measured from readings this machine has already done."
          : "A rough guess until something has been read."}{" "}
        The entry can't be edited while a reading runs, and stopping one keeps
        everything read up to that point.
      </p>
    </section>
  );
}
