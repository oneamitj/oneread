import { setConsent, useConsent } from "../analytics/consent";

/**
 * Shown only where somebody has to be asked — see `analytics/region.ts`. So:
 * plain words about what Clarity collects, both answers as equal buttons, and
 * no second asking.
 */
export function ConsentBar() {
  const choice = useConsent();
  if (choice !== null) return null;

  return (
    <div className="consent glass glass--thin" role="region" aria-label="Analytics">
      <p className="consent__copy">
        Oneread can record how the app gets used, through Microsoft Clarity. Two cookies,
        nothing recorded unless you say yes, off again from the account menu. Either way
        the server keeps a plain daily headcount, which sets no cookie and writes down
        nobody — <a href="/about">what that is</a>.
      </p>
      <div className="consent__acts">
        <button type="button" className="btn" onClick={() => setConsent("denied")}>
          No thanks
        </button>
        <button type="button" className="btn btn--primary" onClick={() => setConsent("granted")}>
          Allow
        </button>
      </div>
    </div>
  );
}
