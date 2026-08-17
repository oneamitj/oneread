import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { Entry, EntryDraft, Meta, TextFormat, Upload } from "../types";
import { FileDrop } from "./FileDrop";
import { SpokenPreview } from "./SpokenPreview";
import { TagInput } from "./TagInput";
import { VoicePreview } from "./VoicePreview";

interface Props {
  meta: Meta;
  entry: Entry | null;
  knownTags: string[];
  busy: boolean;
  error: string | null;
  onSave: (draft: EntryDraft) => void;
  onClose: () => void;
}

const FORMAT_CHOICES: { id: TextFormat; label: string }[] = [
  { id: "plain", label: "Plain text" },
  { id: "markdown", label: "Markdown" },
];

const LANGUAGE_NAMES = new Intl.DisplayNames(["en"], { type: "language" });

function languageLabel(code: string): string {
  if (code === "na") return "Work it out for me";
  try {
    return LANGUAGE_NAMES.of(code) ?? code;
  } catch {
    return code;
  }
}

export function EntryEditor({
  meta, entry, knownTags, busy, error, onSave, onClose,
}: Props) {
  const [title, setTitle] = useState(entry?.title ?? "");
  const [body, setBody] = useState(entry?.body ?? "");
  const [format, setFormat] = useState<TextFormat>(entry?.format ?? "plain");
  const [tags, setTags] = useState<string[]>(entry?.tags ?? []);
  const [voice, setVoice] = useState(entry?.voice ?? meta.default_voice);
  const [lang, setLang] = useState(entry?.lang ?? meta.default_lang);
  const [speed, setSpeed] = useState(entry?.speed ?? meta.default_speed);
  const [sampleMinutes, setSampleMinutes] = useState(meta.sample_minutes);
  const [upload, setUpload] = useState<Upload | null>(null);
  // What the box held before a file replaced it. Offered back as an undo, and
  // forgotten when the sheet closes — a dropped file shouldn't quietly destroy
  // twenty minutes of typing.
  const [replaced, setReplaced] = useState<{ title: string; body: string; format: TextFormat } | null>(null);
  const titleRef = useRef<HTMLInputElement>(null);

  // Walking away shouldn't leave a file sitting on the server nobody wants.
  const close = useCallback(() => {
    if (upload) void api.discardUpload(upload.id).catch(() => undefined);
    onClose();
  }, [upload, onClose]);

  useEffect(() => { titleRef.current?.focus(); }, []);

  useEffect(() => {
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onEscape);
    return () => window.removeEventListener("keydown", onEscape);
  }, [close]);

  const languages = useMemo(() => {
    const rest = meta.languages
      .filter((code) => code !== "na")
      .map((code) => ({ code, label: languageLabel(code) }))
      .sort((a, b) => a.label.localeCompare(b.label));
    return [{ code: "na", label: languageLabel("na") }, ...rest];
  }, [meta.languages]);

  const over = body.length - meta.max_text_chars;
  const canSave = title.trim().length > 0 && body.trim().length > 0 && over <= 0 && !busy;

  const tookFile = (read: Upload) => {
    if (body.trim()) setReplaced({ title, body, format });
    setBody(read.text);
    setFormat(read.format);
    if (!title.trim()) setTitle(read.title);
    setUpload(read);
  };

  const undo = () => {
    if (!replaced) return;
    setTitle(replaced.title);
    setBody(replaced.body);
    setFormat(replaced.format);
    setReplaced(null);
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSave) return;
    onSave({
      title: title.trim(),
      body: body.trim(),
      format,
      tags,
      voice,
      lang,
      speed,
      sample_minutes: sampleMinutes,
      upload_id: upload?.id ?? null,
    });
  };

  return (
    <div className="sheet-layer" role="dialog" aria-modal="true" aria-label={entry ? "Edit entry" : "New entry"}>
      <button type="button" className="scrim" onClick={close} aria-label="Close" />
      <form className="sheet glass glass--thick" onSubmit={submit}>
        <header className="sheet__head">
          <h2>{entry ? "Edit entry" : "New entry"}</h2>
          <button type="button" className="btn btn--quiet" onClick={close}>
            Close
          </button>
        </header>

        <div className="sheet__scroll">
          <label className="label" htmlFor="entry-title">Title</label>
          <input
            id="entry-title"
            ref={titleRef}
            className="field"
            value={title}
            maxLength={200}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="What is this?"
          />

          <div className="sheet__labelrow">
            <label className="label" htmlFor="entry-body">Text to read</label>
            <span className={`hint${over > 0 ? " hint--over" : ""}`}>
              {body.length.toLocaleString()} / {meta.max_text_chars.toLocaleString()}
            </span>
          </div>

          <FileDrop
            meta={meta}
            upload={upload}
            onRead={tookFile}
            onClear={() => setUpload(null)}
            disabled={busy}
          />

          {replaced ? (
            <p className="hint sheet__note">
              That file replaced what was in the box.{" "}
              <button type="button" className="linkish" onClick={undo}>
                Put my text back
              </button>
            </p>
          ) : null}

          {upload?.truncated ? (
            <p className="hint sheet__note">
              That file runs past the {meta.max_text_chars.toLocaleString()}-character limit, so
              only the start came through. The rest is still in the original file.
            </p>
          ) : null}

          <div className="segmented" role="radiogroup" aria-label="How to read the text">
            {FORMAT_CHOICES.filter((choice) => meta.formats.includes(choice.id)).map(
              (choice) => (
                <button
                  key={choice.id}
                  type="button"
                  role="radio"
                  aria-checked={format === choice.id}
                  className="segmented__option"
                  onClick={() => setFormat(choice.id)}
                >
                  {choice.label}
                </button>
              ),
            )}
          </div>

          <textarea
            id="entry-body"
            className="field field--area"
            value={body}
            onChange={(event) => setBody(event.target.value)}
            placeholder={
              format === "markdown"
                ? "Paste a README, a spec, meeting notes. Headings, lists and tables all get read out."
                : "Paste an article, a chapter, a recipe, tomorrow's talk."
            }
          />
          <p className="hint sheet__note">
            {format === "markdown"
              ? "Formatting is spoken, not spelled: headings and list items become their own lines, tables are read column by column, and code fences are announced rather than dictated."
              : "Every character is read exactly as written."}
          </p>

          <SpokenPreview text={body} format={format} />

          <label className="label" htmlFor="entry-tags">Tags</label>
          <TagInput tags={tags} onChange={setTags} suggestions={knownTags} />

          <div className="sheet__grid">
            <div>
              <label className="label" htmlFor="entry-voice">Voice</label>
              <select
                id="entry-voice"
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
              <label className="label" htmlFor="entry-lang">Language</label>
              <select
                id="entry-lang"
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
          </div>

          <div className="sheet__labelrow">
            <label className="label" htmlFor="entry-speed">Speed</label>
            <span className="hint">{speed.toFixed(2)}&times;</span>
          </div>
          <input
            id="entry-speed"
            className="slider"
            type="range"
            min={meta.min_speed}
            max={meta.max_speed}
            step={0.05}
            value={speed}
            onChange={(event) => setSpeed(Number(event.target.value))}
          />

          <VoicePreview
            voice={voice}
            lang={lang}
            speed={speed}
            text={body}
            format={format}
          />

          <div className="sheet__labelrow">
            <label className="label">Read the first</label>
            <span className="hint">then decide about the rest</span>
          </div>
          <div className="segmented" role="radiogroup" aria-label="Sample length">
            {meta.sample_minute_choices.map((minutes) => (
              <button
                key={minutes}
                type="button"
                role="radio"
                aria-checked={sampleMinutes === minutes}
                className="segmented__option"
                onClick={() => setSampleMinutes(minutes)}
              >
                {minutes} min
              </button>
            ))}
          </div>

          {error ? <p className="error-text">{error}</p> : null}
        </div>

        <footer className="sheet__foot">
          <p className="hint">
            {entry
              ? "Changing the text, format, voice, language or speed starts a new sample."
              : "You get the first few minutes now. The full reading is one press away, once you've heard it."}
          </p>
          <button type="submit" className="btn btn--primary" disabled={!canSave}>
            {busy ? "Working…" : entry ? "Save" : "Read the start"}
          </button>
        </footer>
      </form>
    </div>
  );
}
