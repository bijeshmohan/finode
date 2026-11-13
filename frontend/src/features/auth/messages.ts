// What a person reads when a sign-in screen fails: the server's own words wherever it gave them.
import { ApiError } from "../../api/client";

export const UNREACHABLE = "finode can't be reached. Check your connection.";
const SOMETHING_WRONG = "Something went wrong. Please try again.";

/** The quick checks made before sending, in the server's own words (app/auth_flows.py). */
export const MIN_PASSWORD_LENGTH = 8;
export const RULES = {
  email: "Enter a valid email address.",
  short: `Password must be at least ${String(MIN_PASSWORD_LENGTH)} characters.`,
  mismatch: "Passwords do not match.",
} as const;

export function messageOf(error: unknown): string {
  if (!(error instanceof ApiError)) return UNREACHABLE;
  const { detail } = error;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string") {
    return detail.message;
  }
  return SOMETHING_WRONG;
}

/** The `code` the sign-in routes add to some refusals ("link-invalid": a spent or expired reset link). */
export function codeOf(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  const { detail } = error;
  return detail && typeof detail === "object" && "code" in detail && typeof detail.code === "string"
    ? detail.code
    : null;
}
