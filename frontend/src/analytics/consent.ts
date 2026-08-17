/** Whether the reader has agreed to analytics, and what follows from that.

Clarity records sessions and sets its own cookies, so the tag is not fetched at
all until someone says yes. That's the point of loading it from a module: an
inline snippet in `index.html` runs before anyone has been asked.

Withdrawal has to be as easy as consent, so the choice is a stored value that
can go back to "denied" from the account menu, and doing so stops the recorder
and clears what it left behind.
*/

import { useSyncExternalStore } from "react";
import { startClarity } from "./clarity";

export type Choice = "granted" | "denied";

const KEY = "oneread.analytics";
const CLARITY_COOKIES = ["_clck", "_clsk", "CLID", "ANONCHK", "MR", "MUID", "SM"];

const listeners = new Set<() => void>();
let choice: Choice | null = load();

function load(): Choice | null {
  // Private-mode Safari throws on storage rather than returning null.
  try {
    const stored = window.localStorage.getItem(KEY);
    return stored === "granted" || stored === "denied" ? stored : null;
  } catch {
    return null;
  }
}

function save(next: Choice): void {
  try {
    window.localStorage.setItem(KEY, next);
  } catch {
    // Nothing stored means they get asked again next visit, which is the safe
    // way round: it never turns a "no" into a silent yes.
  }
}

/** Call once at boot. Loads the tag only for someone who already agreed. */
export function applyStoredConsent(): void {
  if (choice === "granted") start();
}

export function setConsent(next: Choice): void {
  if (choice === next) return;
  choice = next;
  save(next);
  if (next === "granted") start();
  else stop();
  listeners.forEach((notify) => notify());
}

/** `null` while they haven't been asked yet — that's when the bar shows. */
export function useConsent(): Choice | null {
  return useSyncExternalStore(subscribe, () => choice, () => null);
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
