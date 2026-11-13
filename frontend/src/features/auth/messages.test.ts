import { describe, expect, it } from "vitest";

import { ApiError } from "../../api/client";
import { messageOf, UNREACHABLE } from "./messages";

describe("messageOf says what the server said", () => {
  it("reads the sign-in routes' message", () => {
    expect(messageOf(new ApiError(401, { message: "Invalid email or password.", code: null }))).toBe(
      "Invalid email or password.",
    );
  });

  it("reads a plain detail", () => {
    expect(messageOf(new ApiError(400, "nope"))).toBe("nope");
  });

  it("says so when finode cannot be reached", () => {
    expect(messageOf(new TypeError("Failed to fetch"))).toBe(UNREACHABLE);
  });

  it("falls back to a plain sentence", () => {
    expect(messageOf(new ApiError(500, null))).toBe("Something went wrong. Please try again.");
  });
});
