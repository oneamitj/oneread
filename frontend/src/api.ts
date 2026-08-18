import type {
  Entry,
  EntryDraft,
  EntryList,
  Estimate,
  Meta,
  ReadingRequest,
  Rendition,
  RenditionDetail,
  SegmentList,
  Session,
  TextFormat,
  Upload,
  User,
} from "./types";

/** Thrown for any non-2xx response. `message` is already reader-ready. */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

const FALLBACK: Record<number, string> = {
  401: "Sign in to continue.",
  403: "That request was blocked. Reload the page and try again.",
  404: "That entry is gone.",
  409: "The audio isn't ready yet.",
  413: "That file is bigger than the limit.",
  422: "That file couldn't be read.",
  429: "Too many requests. Give it a minute.",
  500: "The server had a problem. Try again in a moment.",
  // nginx answers these itself while the app is down or restarting, with its
  // own HTML page rather than the `{"message": "..."}` every route produces.
  502: "The server is restarting. Try again in a moment.",
  503: "The server is restarting. Try again in a moment.",
};

function send(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: {
      // The server refuses writes without this. A cross-site form can't set it.
      "X-Requested-With": "oneread",
      // A file upload has to keep the multipart type the browser generates,
      // boundary and all. Forcing JSON onto it makes the body unreadable.
      ...(init.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...init.headers,
    },
  });
}

async function failure(response: Response): Promise<ApiError> {
  let message = FALLBACK[response.status] ?? "Something went wrong.";
  try {
    const body = await response.json();
    if (typeof body?.message === "string" && body.message) message = body.message;
  } catch {
    /* no JSON body, keep the fallback */
  }
  return new ApiError(response.status, message);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await send(path, init);
  if (!response.ok) throw await failure(response);
  if (response.status === 204) return undefined as T;
  try {
    return (await response.json()) as T;
  } catch {
    // A 2xx that isn't JSON means something between here and the route
    // answered instead of the route: a proxy redirect followed into the HTML
    // shell, a captive portal, a cached page. Raising the parse error as-is
    // hands the caller a `SyntaxError` it can't tell apart from a bug of its
    // own, and every caller then shows its most generic sentence.
    throw new ApiError(response.status, "The server sent an answer we couldn't read.");
  }
}

export const api = {
  meta: () => request<Meta>("/api/meta"),

  me: () => request<User>("/api/auth/me"),

  signIn: (username: string, password: string) =>
    request<Session>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  signOut: () => request<void>("/api/auth/logout", { method: "POST" }),

  /** Drop every other session for this account. This browser stays signed in. */
  revokeSessions: () => request<void>("/api/auth/revoke-sessions", { method: "POST" }),

  list: (query: string, tags: string[]) => {
    const params = new URLSearchParams();
    if (query.trim()) params.set("q", query.trim());
    tags.forEach((tag) => params.append("tag", tag));
    const suffix = params.toString();
    return request<EntryList>(`/api/entries${suffix ? `?${suffix}` : ""}`);
  },

  /** The full entry: text, spoken version and every cue. */
  get: (id: string) => request<Entry>(`/api/entries/${id}`),

  create: (draft: EntryDraft) =>
    request<Entry>("/api/entries", { method: "POST", body: JSON.stringify(draft) }),

  update: (id: string, draft: EntryDraft) =>
    request<Entry>(`/api/entries/${id}`, { method: "PUT", body: JSON.stringify(draft) }),

  remove: (id: string) => request<void>(`/api/entries/${id}`, { method: "DELETE" }),

  /** What a reading will cost, before anyone commits half an hour of CPU to it. */
  estimate: (id: string, plan: ReadingRequest) => {
    const params = new URLSearchParams({ scope: plan.scope });
    if (plan.mode) params.set("mode", plan.mode);
    if (plan.minutes) params.set("minutes", String(plan.minutes));
    if (plan.scope === "range") {
      params.set("start", String(plan.start ?? 0));
      if (plan.end != null) params.set("end", String(plan.end));
    }
    if (plan.speed != null) params.set("speed", String(plan.speed));
    return request<Estimate>(`/api/entries/${id}/estimate?${params}`);
  },

  /** Every sentence the reader will produce, with a guess at its timing. */
  segments: (id: string, speed?: number) => {
    const params = speed != null ? `?speed=${speed}` : "";
    return request<SegmentList>(`/api/entries/${id}/segments${params}`);
  },

  read: (id: string, plan: ReadingRequest) =>
    request<Rendition>(`/api/entries/${id}/renditions`, {
      method: "POST",
      body: JSON.stringify(plan),
    }),

  rendition: (id: string) => request<RenditionDetail>(`/api/renditions/${id}`),

  stop: (id: string) =>
    request<Rendition>(`/api/renditions/${id}/stop`, { method: "POST" }),

  dropRendition: (id: string) =>
    request<void>(`/api/renditions/${id}`, { method: "DELETE" }),

  /** A few seconds of the chosen voice, as a blob ready for an <audio> src. */
  preview: async (input: {
    voice: string;
    lang: string;
    speed: number;
    text: string;
    format: TextFormat;
  }): Promise<Blob> => {
    const response = await send("/api/preview", {
      method: "POST",
      body: JSON.stringify(input),
    });
    if (!response.ok) throw await failure(response);
    return await response.blob();
  },

  /** What the voice will say, once markdown is flattened. No audio involved. */
  spokenText: (text: string, format: TextFormat) =>
    request<{ text: string; characters: number }>("/api/preview/text", {
      method: "POST",
      body: JSON.stringify({ text, format }),
    }),

  /** Read a file on the server. Nothing is saved until the entry is created. */
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Upload>("/api/uploads", { method: "POST", body: form });
  },

  /** Throw away a file the editor decided against. */
  discardUpload: (id: string) =>
    request<void>(`/api/uploads/${id}`, { method: "DELETE" }),
};

export const audioUrl = (id: string) => `/api/renditions/${id}/audio`;
export const downloadUrl = (id: string) => `/api/renditions/${id}/audio?download=1`;
export const srtUrl = (id: string) => `/api/renditions/${id}/subtitles.srt`;
export const vttUrl = (id: string) => `/api/renditions/${id}/subtitles.vtt?download=1`;
export const sourceUrl = (id: string) => `/api/entries/${id}/source`;
export const spokenTextUrl = (id: string) => `/api/entries/${id}/text.txt`;
