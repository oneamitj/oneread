import { useEffect, useRef, useState } from "react";
import { audioUrl } from "../api";
import { clock } from "../format";

interface Props {
  renditionId: string;
  title: string;
  duration: number;
}

/**
 * Play, pause, and how far in you are. Nothing else lives on a card: scrubbing,
 * transcripts and downloads are all one tap away on the entry's own page.
 */
export function MiniPlayer({ renditionId, title, duration }: Props) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);

  const progress = duration > 0 ? Math.min(1, time / duration) : 0;

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !playing) return;
    let frame = requestAnimationFrame(function tick() {
      setTime(audio.currentTime);
      frame = requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(frame);
  }, [playing]);

  return (
    <div className="mini">
      <audio
        ref={audioRef}
        src={audioUrl(renditionId)}
        preload="none"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => { setPlaying(false); setTime(0); }}
      />
      <button
        type="button"
        className="mini__play"
        aria-label={playing ? `Pause ${title}` : `Play ${title}`}
        onClick={(event) => {
          event.stopPropagation();
          const audio = audioRef.current;
          if (!audio) return;
          if (audio.paused) void audio.play();
          else audio.pause();
        }}
      >
        {playing ? <PauseGlyph /> : <PlayGlyph />}
      </button>
      <div className="mini__line" aria-hidden="true">
        <div className="mini__fill" style={{ transform: `scaleX(${progress})` }} />
      </div>
      <span className="mini__time">
        {playing || time > 0 ? clock(time) : clock(duration)}
      </span>
    </div>
  );
}

function PlayGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 18 18" aria-hidden="true">
      <path d="M5 3.2v11.6L14.4 9 5 3.2z" fill="currentColor" />
    </svg>
  );
}

function PauseGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 18 18" aria-hidden="true">
      <path d="M5 3.5h3.1v11H5zM9.9 3.5H13v11H9.9z" fill="currentColor" />
    </svg>
  );
}
