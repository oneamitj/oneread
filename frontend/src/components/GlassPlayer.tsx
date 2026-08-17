import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, audioUrl } from "../api";
import { clock } from "../format";
import type { Cue } from "../types";

interface Props {
  renditionId: string;
  title: string;
  duration: number;
  /** Lines exist, but they're only fetched if someone opens the transcript. */
  hasCues: boolean;
}

export function GlassPlayer({ renditionId, title, duration, hasCues }: Props) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLOListElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [scrubbing, setScrubbing] = useState(false);
  const [showTranscript, setShowTranscript] = useState(false);
  const [cues, setCues] = useState<Cue[] | null>(null);
  const [cueError, setCueError] = useState<string | null>(null);

  const total = duration || 0;
  const progress = total > 0 ? Math.min(1, time / total) : 0;

  // A long document has thousands of cues, so they stay on the server until
  // someone actually asks to read along.
  useEffect(() => {
    if (!showTranscript || cues) return;
    let cancelled = false;
    api
      .rendition(renditionId)
      .then((reading) => { if (!cancelled) setCues(reading.cues ?? []); })
      .catch((problem) => {
        if (!cancelled) {
          setCueError(
            problem instanceof ApiError ? problem.message : "Couldn't load the words.",
          );
        }
      });
    return () => { cancelled = true; };
  }, [showTranscript, cues, renditionId]);

  const activeCue = useMemo(() => {
    if (!cues?.length) return -1;
    let low = 0;
    let high = cues.length - 1;
    let found = 0;
    while (low <= high) {
      const middle = (low + high) >> 1;
      if (cues[middle].start <= time) { found = middle; low = middle + 1; }
      else high = middle - 1;
    }
    return found;
  }, [cues, time]);

  // While playing, read the clock every frame. `timeupdate` fires ~4x a second,
  // which is enough for the label but visibly jerky for the progress bar.
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !playing) return;
    let frame = requestAnimationFrame(function tick() {
      if (!scrubbing) setTime(audio.currentTime);
      frame = requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(frame);
  }, [playing, scrubbing]);

  useEffect(() => {
    if (!showTranscript || activeCue < 0 || !playing) return;
    const node = listRef.current?.children[activeCue] as HTMLElement | undefined;
    node?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeCue, showTranscript, playing]);

  const toggle = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) void audio.play();
    else audio.pause();
  }, []);

  const seekSeconds = useCallback((seconds: number) => {
    const audio = audioRef.current;
    const target = Math.max(0, Math.min(seconds, total || seconds));
    setTime(target);
    if (audio && Number.isFinite(target)) audio.currentTime = target;
  }, [total]);

  const seekFraction = useCallback(
    (fraction: number) => seekSeconds(Math.max(0, Math.min(1, fraction)) * total),
    [seekSeconds, total],
  );

  const fractionAt = (clientX: number): number => {
    const box = trackRef.current?.getBoundingClientRect();
    return box ? (clientX - box.left) / box.width : 0;
  };

  // Pointer capture keeps the scrub 1:1 even when the finger leaves the bar.
  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    setScrubbing(true);
    seekFraction(fractionAt(event.clientX));
  };

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (scrubbing) seekFraction(fractionAt(event.clientX));
  };

  const endScrub = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!scrubbing) return;
    event.currentTarget.releasePointerCapture(event.pointerId);
    setScrubbing(false);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? 30 : 10;
    if (event.key === "ArrowRight") { event.preventDefault(); seekSeconds(time + step); }
    else if (event.key === "ArrowLeft") { event.preventDefault(); seekSeconds(time - step); }
    else if (event.key === " " || event.key === "Enter") { event.preventDefault(); toggle(); }
  };

  return (
    <div className={`player${playing ? " is-playing" : ""}`}>
      <div className="player__row">
        <audio
          ref={audioRef}
          src={audioUrl(renditionId)}
          preload="metadata"
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onEnded={() => { setPlaying(false); setTime(0); }}
          onTimeUpdate={(e) => { if (!scrubbing) setTime(e.currentTarget.currentTime); }}
        />

        <button
          type="button"
          className="player__play"
          onClick={toggle}
          aria-label={playing ? `Pause ${title}` : `Play ${title}`}
        >
          {playing ? <PauseGlyph /> : <PlayGlyph />}
        </button>

        <div className="player__body">
          <div
            ref={trackRef}
            className={`player__track${scrubbing ? " is-scrubbing" : ""}`}
            role="slider"
            tabIndex={0}
            aria-label="Position"
            aria-valuemin={0}
            aria-valuemax={Math.round(total)}
            aria-valuenow={Math.round(time)}
            aria-valuetext={`${clock(time)} of ${clock(total)}`}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={endScrub}
            onPointerCancel={endScrub}
            onKeyDown={onKeyDown}
          >
            <div className="player__fill" style={{ transform: `scaleX(${progress})` }} />
            <div className="player__knob" style={{ left: `${progress * 100}%` }} />
          </div>
          <div className="player__times">
            <span>{clock(time)}</span>
            <span>{clock(total)}</span>
          </div>
        </div>

        {hasCues ? (
          <button
            type="button"
            className="btn btn--quiet player__toggle"
            onClick={() => setShowTranscript((open) => !open)}
            aria-expanded={showTranscript}
          >
            {showTranscript ? "Hide words" : "Follow along"}
          </button>
        ) : null}
      </div>

      {showTranscript ? (
        cueError ? (
          <p className="error-text">{cueError}</p>
        ) : cues ? (
          <ol className="cues" ref={listRef}>
            {cues.map((cue, index) => (
              <li key={cue.i}>
                <button
                  type="button"
                  className={`cues__line${index === activeCue ? " is-active" : ""}`}
                  onClick={() => seekSeconds(cue.start)}
                >
                  <span className="cues__time">{clock(cue.start)}</span>
                  <span className="cues__text">{cue.text}</span>
                </button>
              </li>
            ))}
          </ol>
        ) : (
          <p className="hint cues__loading">Fetching the words…</p>
        )
      ) : null}
    </div>
  );
}

function PlayGlyph() {
  return (
    <svg width="16" height="16" viewBox="0 0 18 18" aria-hidden="true">
      <path d="M5 3.2v11.6L14.4 9 5 3.2z" fill="currentColor" />
    </svg>
  );
}

function PauseGlyph() {
  return (
    <svg width="16" height="16" viewBox="0 0 18 18" aria-hidden="true">
      <path d="M5 3.5h3.1v11H5zM9.9 3.5H13v11H9.9z" fill="currentColor" />
    </svg>
  );
}
