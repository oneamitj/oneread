import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "./api";
import { AuthGate } from "./screens/AuthGate";
import { EntryPage } from "./screens/EntryPage";
import { Library } from "./screens/Library";
import type { Meta, User } from "./types";

/** `/e/<id>` is one entry; anything else is the library. */
function entryFromPath(path: string): string | null {
  const match = /^\/e\/([a-zA-Z0-9]+)\/?$/.exec(path);
  return match ? match[1] : null;
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [checked, setChecked] = useState(false);
  const [path, setPath] = useState(() => window.location.pathname);
  const [knownTags, setKnownTags] = useState<string[]>([]);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [session, settings] = await Promise.allSettled([api.me(), api.meta()]);
      if (cancelled) return;
      if (session.status === "fulfilled") setUser(session.value);
      if (settings.status === "fulfilled") setMeta(settings.value);
      setChecked(true);
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const go = useCallback((next: string) => {
    window.history.pushState(null, "", next);
    setPath(next);
    window.scrollTo({ top: 0 });
  }, []);

  const back = useCallback(() => {
    // Coming from a card, the library is genuinely the previous page.
    if (window.history.length > 1) window.history.back();
    else go("/");
    setRevision((n) => n + 1);
  }, [go]);

  const signOut = useCallback(async () => {
    try {
      await api.signOut();
    } catch (problem) {
      if (!(problem instanceof ApiError)) throw problem;
    }
    setUser(null);
    go("/");
  }, [go]);

  // The library owns the tag list, so hand what it knows to the entry page.
  useEffect(() => {
    if (!user) return;
    api.list("", []).then((result) => setKnownTags(result.tags)).catch(() => {});
  }, [user, revision]);

  const entryId = entryFromPath(path);

  return (
    <>
      <div className="backdrop" aria-hidden="true" />
      {!checked ? (
        <div className="boot" role="status">Loading</div>
      ) : !user || !meta ? (
        <AuthGate
          onSignedIn={async (session) => {
            setUser(session.user);
            if (!meta) setMeta(await api.meta());
          }}
        />
      ) : entryId ? (
        <EntryPage
          key={entryId}
          entryId={entryId}
          meta={meta}
          knownTags={knownTags}
          onBack={back}
          onGone={() => { go("/"); setRevision((n) => n + 1); }}
        />
      ) : (
        <Library
          user={user}
          meta={meta}
          revision={revision}
          onOpen={(id) => go(`/e/${id}`)}
          onSignOut={() => void signOut()}
        />
      )}
    </>
  );
}
