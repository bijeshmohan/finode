import { afterEach, describe, expect, it } from "vitest";

import { chooseTheme, readTheme } from "./theme";

afterEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("the theme", () => {
  it("matches the device until one is chosen", () => {
    expect(readTheme()).toBe("auto");
  });

  it("a choice is kept in this browser and set on the page at once", () => {
    chooseTheme("dark");
    expect(localStorage.getItem("finode_theme")).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(readTheme()).toBe("dark");
  });

  it("matching the device again takes the choice off", () => {
    chooseTheme("light");
    chooseTheme("auto");
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(readTheme()).toBe("auto");
  });

  it("something else in storage is matching the device", () => {
    localStorage.setItem("finode_theme", "purple");
    expect(readTheme()).toBe("auto");
  });
});
