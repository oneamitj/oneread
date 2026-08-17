import { useState } from "react";

interface Props {
  tags: string[];
  onChange: (tags: string[]) => void;
  suggestions?: string[];
  max?: number;
}

export function TagInput({ tags, onChange, suggestions = [], max = 12 }: Props) {
  const [draft, setDraft] = useState("");

  const add = (raw: string) => {
    const tag = raw.trim().replace(/^#/, "").slice(0, 32);
    if (!tag || tags.length >= max) return;
    if (tags.some((existing) => existing.toLowerCase() === tag.toLowerCase())) return;
    onChange([...tags, tag]);
  };

  const remove = (tag: string) => onChange(tags.filter((t) => t !== tag));

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      add(draft);
      setDraft("");
    } else if (event.key === "Backspace" && !draft && tags.length) {
      onChange(tags.slice(0, -1));
    }
  };

  const unused = suggestions.filter(
    (tag) => !tags.some((existing) => existing.toLowerCase() === tag.toLowerCase()),
  );

  return (
    <div className="taginput">
      <div className="taginput__box field">
        {tags.map((tag) => (
          <span key={tag} className="chip chip--static">
            {tag}
            <button
              type="button"
              className="chip__x"
              onClick={() => remove(tag)}
              aria-label={`Remove tag ${tag}`}
            >
              &times;
            </button>
          </span>
        ))}
        <input
          className="taginput__input"
          value={draft}
          placeholder={tags.length ? "" : "recipes, bedtime, work"}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          onBlur={() => { add(draft); setDraft(""); }}
          aria-label="Tags"
        />
      </div>
      {unused.length ? (
        <div className="taginput__suggest">
          {unused.slice(0, 8).map((tag) => (
            <button key={tag} type="button" className="chip" onClick={() => add(tag)}>
              + {tag}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
