// What a person reads when a call fails: the server's own words wherever it gave them.
import { ApiError } from "./client";

export const UNREACHABLE = "finode can't be reached. Check your connection.";
const SOMETHING_WRONG = "Something went wrong. Please try again.";

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
