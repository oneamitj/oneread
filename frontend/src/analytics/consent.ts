/** Whether the reader has agreed to analytics, and what follows from that.

Clarity records sessions and sets cookies, so the tag isn't fetched until
someone says yes — which is why it loads from a module rather than an inline
snippet in `index.html`, which would run before anyone was asked.

Where the law requires the question, it gets asked. Everywhere else Clarity
starts on its own, because a bar nobody is obliged to show is a bar that mostly
gets ignored, and an ignored bar measures nothing. `region.ts` draws the line.

Either way the answer is one click in the account menu, in both directions, and
an explicit answer beats the regional default permanently:

  | Where       | Stored          | Bar    | Clarity          |
  | ----------- | --------------- | ------ | ---------------- |
  | Ask-region  | nothing         | shows  | off until Allow  |
  | Ask-region  | granted/denied  | hidden | as chosen        |
  | Elsewhere   | nothing         | hidden | on               |
  | Elsewhere   | denied          | hidden | off              |

None of this covers the headcount the server keeps, which runs for everybody and
asks nobody. It sets no cookie, stores nothing in this browser and writes down
no address — it is four integers a day. See `backend/oneread/visits.py`.
*/

import { useSyncExternalStore } from "react";
import { startClarity } from "./clarity";
import { needsConsent } from "./region";

export type Choice = "granted" | "denied";

const KEY = "oneread.analytics";
const CLARITY_COOKIES = ["_clck", "_clsk", "CLID", "ANONCHK", "MR", "MUID", "SM"];

const listeners = new Set<() => void>();

/** Only ever an answer someone actually gave. */
let stored: Choice | null = load();

/** The regional default, worked out afresh on every load rather than saved. A
 * stored "granted" nobody clicked is exactly the thing worth not creating. */
const implied: Choice | null = needsConsent() ? null : "granted";

/** What's in force: an explicit answer, else the regional default. */
function effective(): Choice | null {
  return stored ?? implied;
}

function load(): Choice | null {
  // Private-mode Safari throws on storage rather than returning null.
  try {
    const value = window.localStorage.getItem(KEY);
    return value === "granted" || value === "denied" ? value : null;
  } catch {
    return null;
  }
}

function save(next: Choice): void {
  try {
    window.localStorage.setItem(KEY, next);
  } catch {
    // Nothing stored means the regional default applies again next visit. In an
    // ask-region that means being asked again, which is the safe way round: it
    // never turns a "no" into a silent yes.
  }
}

/** Call once at boot, before anything renders. */
export function applyConsent(): void {
  if (effective() === "granted") start();
}

export function setConsent(next: Choice): void {
  if (stored === next) return;
  stored = next;
  save(next);
  if (next === "granted") start();
  else stop();
  listeners.forEach((notify) => notify());
}

/** `null` only where someone has to be asked and hasn't been — that's when the
 * bar shows. Elsewhere it reads "granted" from the first paint. */
export function useConsent(): Choice | null {
  return useSyncExternalStore(subscribe, effective, () => null);
}

function subscribe(notify: () => void): () => void {
  listeners.add(notify);
  return () => listeners.delete(notify);
}

function start(): void {
  startClarity();
  // Explicit, in case the project is set to cookie-consent mode: there, the
  // recorder stays cookieless until it hears this.
  window.clarity?.("consent");
}

function stop(): void {
  // The tag may already be on the page from earlier in this visit. Stopping it
  // and clearing the cookies is what makes "no" take effect without a reload.
  window.clarity?.("stop");
  for (const name of CLARITY_COOKIES) forget(name);
}

function forget(name: string): void {
  const expired = "=; Max-Age=0; path=/";
  document.cookie = `${name}${expired}`;
  // Cookies set on the registrable domain need the same domain to be removed.
  const parts = window.location.hostname.split(".");
  for (let i = 0; i < parts.length - 1; i += 1) {
    document.cookie = `${name}${expired}; domain=.${parts.slice(i).join(".")}`;
  }
}
