import { useEffect, useRef, useState } from "react";
import { audioUrl } from "../api";
import { clock } from "../format";
import { PauseGlyph, PlayGlyph } from "./Glyphs";

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
        {playing ? <PauseGlyph size={14} /> : <PlayGlyph size={14} />}
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
