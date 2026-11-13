// The build-time settings the app reads (Vite fills them from VITE_* environment variables).
interface ImportMetaEnv {
  /** Where the API is, e.g. https://api.example.com. Empty in development: Vite forwards /api to the local server. */
  readonly VITE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
