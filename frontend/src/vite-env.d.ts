/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Microsoft Clarity project id. Unset falls back to the production id. */
  readonly VITE_CLARITY_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
