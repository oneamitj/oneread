/**
 * What kind of document a filename names, and a mark for it.
 *
 * The marks are drawn rather than borrowed from the emoji table on purpose.
 * Emoji render as somebody else's colour cartoons, at whatever size and style
 * the operating system feels like, and one of those next to this app's
 * monochrome glyphs looks like a sticker on a window. These inherit the text
 * colour and line weight of everything around them.
 */

export interface Kind {
  id: string;
  /** What a person would call it, not the MIME type. */
  label: string;
}

const BY_EXTENSION: Record<string, Kind> = {
  ".doc": { id: "doc", label: "Word" },
  ".docx": { id: "doc", label: "Word" },
  ".odt": { id: "doc", label: "OpenDocument" },
  ".rtf": { id: "doc", label: "Rich text" },
  ".pdf": { id: "pdf", label: "PDF" },
  ".ppt": { id: "slides", label: "PowerPoint" },
  ".pptx": { id: "slides", label: "PowerPoint" },
  ".odp": { id: "slides", label: "OpenDocument slides" },
  ".xls": { id: "sheet", label: "Excel" },
  ".xlsx": { id: "sheet", label: "Excel" },
  ".ods": { id: "sheet", label: "OpenDocument sheet" },
  ".csv": { id: "sheet", label: "CSV" },
  ".tsv": { id: "sheet", label: "TSV" },
  ".md": { id: "markdown", label: "Markdown" },
  ".markdown": { id: "markdown", label: "Markdown" },
  ".html": { id: "web", label: "Web page" },
  ".htm": { id: "web", label: "Web page" },
  ".txt": { id: "text", label: "Plain text" },
};

const UNKNOWN: Kind = { id: "text", label: "Document" };

export function kindOf(filename: string): Kind {
  const dot = filename.lastIndexOf(".");
  if (dot <= 0) return UNKNOWN;
  return BY_EXTENSION[filename.slice(dot).toLowerCase()] ?? UNKNOWN;
}

export function FileKind({ kind }: { kind: Kind }) {
  return (
    <span className="filepill__mark" aria-hidden="true">
      {MARKS[kind.id] ?? MARKS.text}
    </span>
  );
}

const page = (
  <path
    d="M9.2 1.8H4.6A1.4 1.4 0 0 0 3.2 3.2v9.6a1.4 1.4 0 0 0 1.4 1.4h6.8a1.4 1.4 0 0 0 1.4-1.4V5.6L9.2 1.8Z"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.3"
    strokeLinejoin="round"
  />
);

const fold = (
  <path
    d="M9.2 2v3.6h3.6"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.3"
    strokeLinejoin="round"
  />
);

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16">
      {children}
    </svg>
  );
}

const MARKS: Record<string, React.ReactNode> = {
  // A page with writing on it.
  text: (
    <Frame>
      {page}
      {fold}
      <path d="M5.4 8.4h5M5.4 11h3.2" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </Frame>
  ),
  // Same page, with a heading rule to say it's a written document.
  doc: (
    <Frame>
      {page}
      {fold}
      <path
        d="M5.4 8.2h5M5.4 10.4h5M5.4 12.4h2.8"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
      />
    </Frame>
  ),
  // The bookmark ribbon PDF readers all draw.
  pdf: (
    <Frame>
      {page}
      {fold}
      <path
        d="M6.4 8.2h3.2v4l-1.6-1.2-1.6 1.2v-4Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
    </Frame>
  ),
  // A screen on a stand.
  slides: (
    <Frame>
      <rect
        x="2.4"
        y="3"
        width="11.2"
        height="7.6"
        rx="1.4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.3"
      />
      <path d="M8 10.6v2.6M6 13.4h4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </Frame>
  ),
  // Rows and columns.
  sheet: (
    <Frame>
      <rect
        x="2.4"
        y="2.8"
        width="11.2"
        height="10.4"
        rx="1.4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.3"
      />
      <path d="M2.4 6.4h11.2M6.6 6.4v6.8" stroke="currentColor" strokeWidth="1.3" />
    </Frame>
  ),
  // A heading rule over body text: a hash sign is four strokes inside four
  // pixels, and comes out as a smudge at this size.
  markdown: (
    <Frame>
      {page}
      {fold}
      <path d="M5.4 8.4h3.4" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" />
      <path
        d="M5.4 11h5M5.4 12.9h3"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
      />
    </Frame>
  ),
  web: (
    <Frame>
      <circle cx="8" cy="8" r="5.6" fill="none" stroke="currentColor" strokeWidth="1.3" />
      <path
        d="M2.4 8h11.2M8 2.4c1.6 1.8 2.4 3.7 2.4 5.6S9.6 11.8 8 13.6C6.4 11.8 5.6 9.9 5.6 8s.8-3.8 2.4-5.6Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.3"
      />
    </Frame>
  ),
};
