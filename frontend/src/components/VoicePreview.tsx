import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type { TextFormat } from "../types";

interface Props {
  voice: string;
  lang: string;
  speed: number;
  /** The entry's own text. Its first sentence is what gets read, when there is one. */
  text: string;
  format: TextFormat;
}

type State = "idle" | "loading" | "playing";

/**
 * Plays a short sample in the settings currently selected, so nobody has to
 * generate a whole entry to find out a voice is wrong.
 */
export function VoicePreview({ voice, lang, speed, text, format }: Props) {
  const [state, setState] = useState<State>("idle");
  const [error, setError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);

  const stop = useCallback(() => {
    audioRef.current?.pause();
    audioRef.current = null;
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
    setState("idle");
  }, []);

  // Changing a setting makes the sample stale, so drop it rather than let
  // someone hear the voice they just switched away from.
  useEffect(() => { stop(); setError(null); }, [voice, lang, speed, format, stop]);
  useEffect(() => stop, [stop]);

  const play = async () => {
    if (state === "playing") { stop(); return; }
    setState("loading");
    setError(null);
    try {
      const blob = await api.preview({ voice, lang, speed, text, format });
      const url = URL.createObjectURL(blob);
      urlRef.current = url;
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = stop;
      audio.onerror = () => { setError("That sample wouldn't play."); stop(); };
      await audio.play();
      setState("playing");
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Couldn't reach the server.");
      setState("idle");
    }
  };

  return (
    <div className="preview">
      <button
        type="button"
        className="btn preview__btn"
        onClick={() => void play()}
        disabled={state === "loading"}
      >
        {state === "playing" ? <StopGlyph /> : <SpeakerGlyph />}
        {state === "loading" ? "Listening…" : state === "playing" ? "Stop" : "Hear it"}
      </button>
      <span className="hint preview__hint">
        {error ?? (text.trim() ? "Reads your first sentence." : "Reads a sample line.")}
      </span>
    </div>
  );
}

function SpeakerGlyph() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M7 2.5 4 5.2H2v5.6h2L7 13.5z" fill="currentColor" />
      <path
        d="M9.6 5.4a3.4 3.4 0 0 1 0 5.2M11.7 3.3a6.2 6.2 0 0 1 0 9.4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
  );
}

function StopGlyph() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true">
      <rect x="3.5" y="3.5" width="9" height="9" rx="2" fill="currentColor" />
    </svg>
  );
}
