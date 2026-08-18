/** Whether someone has to be asked before analytics may run.

Decided from the browser's own timezone. No IP lookup, no geolocation database,
nothing sent anywhere to find out where somebody is — which would be a strange
way to open a conversation about privacy.

What this is: a regional default, chosen to be over-inclusive. Every `Europe/`
zone is asked, which sweeps in Moscow, Istanbul and Kyiv along with the EU, and
all three have laws of their own anyway. An unreadable or unfamiliar timezone is
asked too. Being asked when you needn't be is a small annoyance; not being asked
when you should be is the failure that matters, so it never rounds that way.

What this is not: a legal determination or a location. A traveller or a VPN gets
the wrong answer in both directions, which is fine — the account menu turns
analytics on and off either way, and an explicit answer always wins.
*/

/** EU/EEA/UK/CH and neighbours all live under this prefix. */
const ASK_PREFIX = /^Europe\//;

/** The rest of the territory covered by the GDPR: the Atlantic islands, Cyprus,
 * and the French overseas departments, none of which are `Europe/` zones. */
const ASK_ALSO = new Set([
  "Atlantic/Azores",
  "Atlantic/Madeira",
  "Atlantic/Canary",
  "Atlantic/Reykjavik",
  "Asia/Nicosia",
  "Asia/Famagusta",
  "Indian/Reunion",
  "Indian/Mayotte",
  "America/Martinique",
  "America/Guadeloupe",
  "America/Cayenne",
  "America/Miquelon",
]);

export function needsConsent(): boolean {
  let zone = "";
  try {
    zone = Intl.DateTimeFormat().resolvedOptions().timeZone ?? "";
  } catch {
    return true;
  }
  // An empty zone means the browser wouldn't say. Unknown means ask.
  if (!zone) return true;
  return ASK_PREFIX.test(zone) || ASK_ALSO.has(zone);
}
