// The sign-in screens' quick checks, in the server's own words (app/auth_flows.py).
export const MIN_PASSWORD_LENGTH = 8;
export const RULES = {
  email: "Enter a valid email address.",
  short: `Password must be at least ${String(MIN_PASSWORD_LENGTH)} characters.`,
  mismatch: "Passwords do not match.",
} as const;
