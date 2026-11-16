import { afterEach, describe, expect, it, vi } from "vitest";

import { updateWhenHidden } from "./update";

function visibility(state: DocumentVisibilityState) {
  vi.spyOn(document, "visibilityState", "get").mockReturnValue(state);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("a new version of the app", () => {
  it("waits while the page is on screen, so nothing being typed is lost", () => {
    visibility("visible");
    const apply = vi.fn();
    updateWhenHidden(apply);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(apply).not.toHaveBeenCalled();
  });

  it("is put in once the page is left, and only once", () => {
    visibility("visible");
    const apply = vi.fn();
    updateWhenHidden(apply);
    visibility("hidden");
    document.dispatchEvent(new Event("visibilitychange"));
    document.dispatchEvent(new Event("visibilitychange"));
    expect(apply).toHaveBeenCalledTimes(1);
  });

  it("is put in at once when the page is already hidden", () => {
    visibility("hidden");
    const apply = vi.fn();
    updateWhenHidden(apply);
    expect(apply).toHaveBeenCalledTimes(1);
  });
});
