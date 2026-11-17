import { waitFor } from "@testing-library/react";
import type { RouteObject } from "react-router";
import { beforeEach, describe, expect, it } from "vitest";

import { account, ids } from "../features/accounts/fixtures";
import { renderApp, SIGNED_IN } from "../test/render";
import { routes } from "./router";
import type { RouteHandle } from "./title";

describe("the tab's title", () => {
  beforeEach(() => {
    document.title = "";
  });

  it("is the screen's name, then finode", async () => {
    renderApp("/accounts");
    await waitFor(() => {
      expect(document.title).toBe("Accounts · finode");
    });
  });

  it("is plain finode on Home", async () => {
    document.title = "Accounts · finode";
    renderApp("/");
    await waitFor(() => {
      expect(document.title).toBe("finode");
    });
  });

  it("names a missing page", async () => {
    renderApp("/no-such-page");
    await waitFor(() => {
      expect(document.title).toBe("Page not found · finode");
    });
  });

  it("names the sign-in screens", async () => {
    renderApp("/sign-in", {});
    await waitFor(() => {
      expect(document.title).toBe("Sign in · finode");
    });
  });

  it("is an account's own name once it has loaded", async () => {
    renderApp(`/accounts/${ids.hdfc}`, { ...SIGNED_IN, [`/api/views/accounts/${ids.hdfc}`]: [200, account()] });
    await waitFor(() => {
      expect(document.title).toBe("HDFC · finode");
    });
  });

  it("is the section's name while an account loads", async () => {
    renderApp(`/accounts/${ids.hdfc}`, { ...SIGNED_IN, [`/api/views/accounts/${ids.hdfc}`]: "never" });
    await waitFor(() => {
      expect(document.title).toBe("Accounts · finode");
    });
  });

  it("is set on every screen but Home and the old addresses", () => {
    const leaves = (list: RouteObject[]): RouteObject[] =>
      list.flatMap((route) => (route.children ? leaves(route.children) : [route]));
    const untitled = leaves(routes)
      .filter((route) => !(route.handle as RouteHandle | undefined)?.title)
      .map((route) => route.path);
    expect(untitled).toEqual(["/login", "/signup", "/", "/recurring/:recurringId", "/budget/group/:categoryId"]);
  });
});
