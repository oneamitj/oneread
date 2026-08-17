import { setConsent, useConsent } from "../analytics/consent";

/**
 * The one time the app asks for something for its own benefit rather than the
 * reader's. So it says plainly what is collected, offers both answers as equal
 * buttons, and doesn't come back once either one is pressed.
 */
export function ConsentBar() {
  const choice = useConsent();
  if (choice !== null) return null;

  return (
    <div className="consent glass glass--thin" role="region" aria-label="Analytics">
      <p className="consent__copy">
        Oneread can track how the app gets used, through Microsoft Clarity. Two cookies,
        nothing recorded unless you say yes, off again from the account menu.
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
