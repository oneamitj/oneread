import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { setConsent, useConsent } from "../analytics/consent";
import { api, ApiError } from "../api";
import { EntryCard } from "../components/EntryCard";
import { EntryEditor } from "../components/EntryEditor";
import { usePolling } from "../hooks/usePolling";
import type { EntryDraft, EntrySummary, Meta, User } from "../types";

interface Props {
  user: User;
  meta: Meta;
  onSignOut: () => void;
  onOpen: (id: string) => void;
  /** Bumped by the page when it changes something, so the grid refetches. */
  revision: number;
}

export function Library({ user, meta, onSignOut, onOpen, revision }: Props) {
  const [entries, setEntries] = useState<EntrySummary[]>([]);
  const [knownTags, setKnownTags] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [activeTags, setActiveTags] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const [composing, setComposing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const analytics = useConsent();

  const load = useCallback(
    async (options: { quiet?: boolean } = {}) => {
      if (!options.quiet) setLoading(true);
      try {
        const result = await api.list(query, activeTags);
        setEntries(result.entries);
        setKnownTags(result.tags);
      } catch (problem) {
        if (problem instanceof ApiError && problem.status === 401) onSignOut();
        else setNotice(problem instanceof ApiError ? problem.message : "Couldn't load your library.");
      } finally {
        setLoading(false);
      }
    },
    [query, activeTags, onSignOut],
  );

  const revokeSessions = useCallback(async () => {
    try {
      await api.revokeSessions();
      setNotice("Signed out all sessions. This browser is still signed in.");
    } catch (problem) {
      if (problem instanceof ApiError && problem.status === 401) onSignOut();
      else setNotice(problem instanceof ApiError ? problem.message : "Couldn't do that.");
    }
  }, [onSignOut]);

  // Debounced so typing in the search box doesn't hammer the server.
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), query ? 180 : 0);
    return () => window.clearTimeout(timer);
  }, [load, query]);

  const working = useMemo(
    () => entries.some((entry) => entry.locked || entry.active !== null),
    [entries],
  );
  usePolling(() => void load({ quiet: true }), working);

  useEffect(() => { if (revision) void load({ quiet: true }); }, [revision, load]);

  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "k") {
        event.preventDefault();
        searchRef.current?.focus();
        searchRef.current?.select();
      }
    };
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, []);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 5000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const toggleTag = (tag: string) =>
    setActiveTags((current) =>
      current.includes(tag) ? current.filter((t) => t !== tag) : [...current, tag],
    );

  const create = async (draft: EntryDraft) => {
    setSaving(true);
    setSaveError(null);
    try {
      await api.create(draft);
      setComposing(false);
      await load({ quiet: true });
    } catch (problem) {
      setSaveError(problem instanceof ApiError ? problem.message : "Couldn't save that.");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (entry: EntrySummary) => {
    // Off the shelf straight away. Waiting for the round trip leaves the card
    // sitting there looking like the press didn't land.
    setEntries((current) => current.filter((one) => one.id !== entry.id));
    try {
      await api.remove(entry.id);
      setNotice(`Deleted “${entry.title}”.`);
    } catch (problem) {
      setNotice(problem instanceof ApiError ? problem.message : "Couldn't delete that.");
      await load({ quiet: true });
    }
  };

  const filtering = Boolean(query.trim() || activeTags.length);

  return (
    <div className="shell">
      <header className="topbar glass glass--thin">
        <div className="topbar__brand">
          <picture>
            <source srcSet="/brand/oneread-mark-dark-128.png" media="(prefers-color-scheme: dark)" />
            <img className="topbar__mark" src="/brand/oneread-mark-128.png" alt="Oneread" width={128} height={128} />
          </picture>
        </div>

        <div className="topbar__search">
          <SearchGlyph />
          <input
            ref={searchRef}
            className="topbar__field"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search titles, text and tags"
            aria-label="Search your library"
            type="search"
          />
          {query ? (
            <button type="button" className="btn btn--quiet" onClick={() => setQuery("")}>
              Clear
            </button>
          ) : null}
        </div>

        <div className="topbar__right">
          <button type="button" className="btn btn--primary" onClick={() => setComposing(true)}>
            New entry
          </button>
          <details className="usermenu">
            <summary className="btn btn--quiet">{user.username}</summary>
            <div className="menu__pop glass glass--thin">
              <button type="button" onClick={onSignOut}>Sign out</button>
              <button type="button" onClick={() => void revokeSessions()}>
                Sign out all sessions
              </button>
              <button
                type="button"
                onClick={() => {
                  const next = analytics === "granted" ? "denied" : "granted";
                  setConsent(next);
                  setNotice(
                    next === "granted"
                      ? "Usage analytics on. Recording starts from here."
                      : "Usage analytics off. Recording stopped and the cookies are gone.",
                  );
                }}
              >
                {analytics === "granted" ? "Turn off usage analytics" : "Turn on usage analytics"}
              </button>
            </div>
          </details>
        </div>
      </header>

      {knownTags.length ? (
        <nav className="tagbar" aria-label="Filter by tag">
          {knownTags.map((tag) => (
            <button
              key={tag}
              type="button"
              className="chip"
              aria-pressed={activeTags.includes(tag)}
              onClick={() => toggleTag(tag)}
            >
              {tag}
            </button>
          ))}
          {activeTags.length ? (
            <button type="button" className="btn btn--quiet" onClick={() => setActiveTags([])}>
              Reset
            </button>
          ) : null}
        </nav>
      ) : null}

      {notice ? <p className="notice glass glass--thin">{notice}</p> : null}

      <main className="grid">
        {loading && !entries.length ? (
          <p className="hint grid__msg">Getting your library…</p>
        ) : entries.length ? (
          entries.map((entry) => (
            <EntryCard
              key={entry.id}
              summary={entry}
              onOpen={onOpen}
              onTagClick={toggleTag}
              onDelete={(entry) => void remove(entry)}
            />
          ))
        ) : filtering ? (
          <div className="empty glass glass--thin">
            <h2>Nothing matches that</h2>
            <p className="hint">Try a shorter word, or clear the tag filters.</p>
          </div>
        ) : (
          <div className="empty glass glass--thin">
            <h2>Your library is empty</h2>
            <p className="hint">
              Paste in an article, a chapter, a set of notes. Give it a title, pick a
              voice, and it comes back as audio with subtitles.
            </p>
            <button type="button" className="btn btn--primary" onClick={() => setComposing(true)}>
              Add the first one
            </button>
          </div>
        )}
      </main>

      {composing ? (
        <EntryEditor
          meta={meta}
          entry={null}
          knownTags={knownTags}
          busy={saving}
          error={saveError}
          onSave={(draft) => void create(draft)}
          onClose={() => { setComposing(false); setSaveError(null); }}
        />
      ) : null}
    </div>
  );
}

function SearchGlyph() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" className="topbar__glyph">
      <circle cx="7" cy="7" r="4.4" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M10.4 10.4 14 14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}
