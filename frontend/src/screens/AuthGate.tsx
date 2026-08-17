import { useState } from "react";
import type { Session } from "../types";
import { api, ApiError } from "../api";

interface Props {
  onSignedIn: (session: Session) => void;
}

export function AuthGate({ onSignedIn }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await api.signIn(username, password));
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Couldn't reach the server.");
      setBusy(false);
    }
  };

  return (
    <main className="gate">
      <form className="gate__card glass glass--thick" onSubmit={submit}>
        <h1 className="gate__mark">
          <picture>
            <source srcSet="/brand/oneread-logo-dark-512.png" media="(prefers-color-scheme: dark)" />
            <img src="/brand/oneread-logo-512.png" alt="" width={512} height={505} />
          </picture>
          <span className="sr-only">oneread</span>
        </h1>
        <p className="gate__lede">
          Your own library of things you'd rather listen to. Pick a user id and a
          password. If the id is new, that's your account made.
        </p>

        <label className="label" htmlFor="gate-user">User id</label>
        <input
          id="gate-user"
          className="field"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          autoComplete="username"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          required
        />

        <label className="label" htmlFor="gate-pass">Password</label>
        <input
          id="gate-pass"
          className="field"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="current-password"
          required
        />

        {error ? <p className="error-text">{error}</p> : null}

        <button
          type="submit"
          className="btn btn--primary gate__go"
          disabled={busy || !username || !password}
        >
          {busy ? "Checking…" : "Continue"}
        </button>

        <p className="hint gate__foot">
          Everything is generated and stored on this machine. Nothing is sent anywhere else.{" "}
          {/* A real link, not a router push: /about is rendered by the server,
              which is the only version a crawler that skips JavaScript sees. */}
          <a href="/about">What this is</a>
        </p>
      </form>
    </main>
  );
}
