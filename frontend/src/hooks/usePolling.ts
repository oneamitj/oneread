import { useEffect, useRef } from "react";

/**
 * Calls `tick` on an interval, but only while `active` is true and the tab is
 * visible. A backgrounded tab has nothing to redraw, so it shouldn't ask.
 */
export function usePolling(tick: () => void, active: boolean, intervalMs = 1500) {
  const saved = useRef(tick);
  saved.current = tick;

  useEffect(() => {
    if (!active) return;
    const run = () => {
      if (document.visibilityState === "visible") saved.current();
    };
    const timer = window.setInterval(run, intervalMs);
    document.addEventListener("visibilitychange", run);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", run);
    };
  }, [active, intervalMs]);
}
