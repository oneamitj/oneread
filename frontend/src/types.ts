export type TextFormat = "plain" | "markdown";

export type RenditionStatus =
  | "pending"
  | "processing"
  | "ready"
  | "stopped"
  | "failed";

export type Scope = "sample" | "range" | "full";

/**
 * How the text is cut up before it reaches the voice. "sentence" is one
 * sentence per go, and one subtitle line per sentence. "paragraph" hands the
 * voice several sentences at once so it runs them together the way a reader
 * would; a subtitle line then covers the whole group.
 */
export type ReadingMode = "sentence" | "paragraph";

export interface Cue {
  i: number;
  start: number;
  end: number;
  text: string;
}

/** One reading of a document. An entry collects as many as you make. */
export interface Rendition {
  id: string;
  entry_id: string;
  scope: Scope;
  mode: ReadingMode;
  limit_s: number | null;
  status: RenditionStatus;
  stop_requested: boolean;
  complete: boolean;
  progress: number;
  segments_done: number;
  segments_total: number;
  /** Sentences in the whole document, for working out what share this covers. */
  document_segments: number;
  /** The first sentence, so two same-length recordings are tellable apart. */
  opening: string | null;
  duration_s: number | null;
  spoken_chars: number;
  wall_s: number | null;
  error: string | null;
  voice: string;
  lang: string;
  speed: number;
  format: TextFormat;
  start_segment: number;
  end_segment: number | null;
  /** The entry leads with this one, so it can't be removed on its own. */
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface RenditionDetail extends Rendition {
  cues: Cue[] | null;
}

/** What the grid draws. The text and the cues are fetched per entry. */
export interface EntrySummary {
  id: string;
  title: string;
  excerpt: string;
  body_chars: number;
  format: TextFormat;
  tags: string[];
  voice: string;
  lang: string;
  speed: number;
  locked: boolean;
  rendition_count: number;
  /** The reading the card plays: the most complete one there is. */
  playable: Rendition | null;
  /** Whatever is running right now, if anything. */
  active: Rendition | null;
  created_at: string;
  updated_at: string;
}

/** The file an entry's text was taken out of, when there was one. */
export interface SourceFile {
  name: string;
  media_type: string;
  bytes: number;
}

/** A file that has been read, waiting for the editor to do something with it. */
export interface Upload {
  id: string;
  filename: string;
  media_type: string;
  bytes: number;
  kind: string;
  format: TextFormat;
  title: string;
  text: string;
  truncated: boolean;
}

export interface Entry {
  id: string;
  title: string;
  body: string;
  format: TextFormat;
  spoken: string | null;
  tags: string[];
  voice: string;
  lang: string;
  speed: number;
  source: SourceFile | null;
  locked: boolean;
  renditions: Rendition[];
  created_at: string;
  updated_at: string;
}

export interface EntryDraft {
  title: string;
  body: string;
  format: TextFormat;
  tags: string[];
  voice: string;
  lang: string;
  speed: number;
  sample_minutes?: number | null;
  /** A file already read by the server, to keep alongside the entry. */
  upload_id?: string | null;
}

export interface EntryList {
  entries: EntrySummary[];
  tags: string[];
  total: number;
}

export interface Segment {
  i: number;
  text: string;
  chars: number;
  start_s: number;
  end_s: number;
}

export interface SegmentList {
  segments: Segment[];
  audio_s: number;
  measured: boolean;
}

export interface ReadingRequest {
  scope: Scope;
  mode?: ReadingMode;
  minutes?: number | null;
  start?: number;
  end?: number | null;
  voice?: string;
  lang?: string;
  speed?: number;
}

export interface Estimate {
  scope: Scope;
  audio_s: number;
  wall_s: number;
  segments: number;
  characters: number;
  measured: boolean;
}

export interface User {
  id: string;
  username: string;
  created_at: string;
}

export interface Session {
  user: User;
  created: boolean;
}

export interface Voice {
  id: string;
  label: string;
  gender: string;
}

export interface Meta {
  voices: Voice[];
  languages: string[];
  default_voice: string;
  default_lang: string;
  default_speed: number;
  max_text_chars: number;
  min_speed: number;
  max_speed: number;
  formats: TextFormat[];
  sample_minutes: number;
  sample_minute_choices: number[];
  allow_registration: boolean;
  upload_types: UploadType[];
  max_upload_bytes: number;
}

export interface UploadType {
  ext: string;
  label: string;
  kind: string;
}
