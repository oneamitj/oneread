/** Microsoft Clarity, loaded once for the whole app.

The vendor snippet is an inline `<script>`, which the CSP refuses
(`script-src 'self'`). Doing the same work from a module keeps the policy tight:
the only concession is the clarity.ms origin, which the tag needs regardless.
*/

type Clarity = {
  (...args: unknown[]): void;
  q?: IArguments[];
};

declare global {
  interface Window {
    clarity?: Clarity;
  }
}

/** Empty in dev, so local sessions don't land in the dashboard. Set
 * `VITE_CLARITY_ID` to override either way. */
const PROJECT_ID =
  import.meta.env.VITE_CLARITY_ID ?? (import.meta.env.PROD ? "y3ti72v9zz" : "");

export function startClarity(projectId: string = PROJECT_ID): void {
  if (!projectId || window.clarity) return;

  // Calls made before the tag lands are queued on `.q` and replayed by it.
  const queue = function (this: unknown) {
    (queue.q = queue.q || []).push(arguments);
  } as Clarity;
  window.clarity = queue;

  const tag = document.createElement("script");
  tag.async = true;
  tag.src = `https://www.clarity.ms/tag/${encodeURIComponent(projectId)}`;
  document.head.appendChild(tag);
}

/** Name the screen for session filtering. Kept to fixed labels — an entry id
 * would put a piece of someone's library into the analytics tags. */
export function clarityPage(name: string): void {
  window.clarity?.("set", "page", name);
}
