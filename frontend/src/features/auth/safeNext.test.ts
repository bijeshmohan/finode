import { describe, expect, it } from "vitest";

import { safeNext } from "./safeNext";

describe("safeNext only leads inside the app", () => {
  it.each(["/accounts", "/oauth/consent?authorization_id=x", "/budget?month=2026-11"])("%s is kept", (next) => {
    expect(safeNext(next)).toBe(next);
  });

  it.each([null, "", "//evil.example", "https://evil.example", "/\\evil.example", "javascript:alert(1)", "/sign-in"])(
    "%s goes Home",
    (next) => {
      expect(safeNext(next)).toBe("/");
    },
  );
});
