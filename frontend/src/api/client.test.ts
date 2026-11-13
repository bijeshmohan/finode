import { describe, expect, it, vi } from "vitest";

import { ApiError, data, makeClient } from "./client";
import { queryClient, retry } from "./queryClient";

function stubFetch(status: number, body: unknown) {
  const seen: Request[] = [];
  const fetch = vi.fn((input: Request) => {
    seen.push(input);
    return Promise.resolve(
      new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
    );
  });
  return { fetch: fetch as unknown as typeof globalThis.fetch, seen };
}

describe("the API client", () => {
  it("sends the cookie and the app header", async () => {
    const { fetch, seen } = stubFetch(200, {});
    const client = makeClient({ baseUrl: "https://api.example.com", fetch, onUnauthorized: vi.fn() });
    await client.GET("/api/profile/");
    expect(seen[0]?.credentials).toBe("include");
    expect(seen[0]?.headers.get("X-Finode")).toBe("1");
    expect(seen[0]?.url).toBe("https://api.example.com/api/profile/");
  });

  it("a 401 calls onUnauthorized", async () => {
    const { fetch } = stubFetch(401, { detail: "missing authentication token" });
    const onUnauthorized = vi.fn();
    const client = makeClient({ baseUrl: "http://localhost", fetch, onUnauthorized });
    await client.GET("/api/profile/");
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("a 401 from sign-in itself (a wrong password) does not leave the page", async () => {
    const { fetch } = stubFetch(401, { detail: { message: "Invalid email or password." } });
    const onUnauthorized = vi.fn();
    const client = makeClient({ baseUrl: "http://localhost", fetch, onUnauthorized });
    await client.POST("/api/auth/sign-in", { body: { email: "a@b.co", password: "x" } });
    await client.GET("/api/auth/session");
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("data() throws ApiError with the status and detail", async () => {
    const { fetch } = stubFetch(400, { detail: "nope" });
    const client = makeClient({ baseUrl: "http://localhost", fetch, onUnauthorized: vi.fn() });
    const failed = data(client.GET("/api/profile/"));
    await expect(failed).rejects.toBeInstanceOf(ApiError);
    await expect(failed).rejects.toMatchObject({ status: 400, detail: "nope" });
  });

  it("data() returns the body of a success", async () => {
    const { fetch } = stubFetch(200, { first_name: "Ada" });
    const client = makeClient({ baseUrl: "http://localhost", fetch, onUnauthorized: vi.fn() });
    await expect(data(client.GET("/api/profile/"))).resolves.toMatchObject({ first_name: "Ada" });
  });
});

describe("the query client", () => {
  it("is the one the app uses", () => {
    expect(queryClient.getDefaultOptions().queries?.retry).toBe(retry);
  });

  it("does not retry what the server refused", () => {
    expect(retry(0, new ApiError(404, "not found"))).toBe(false);
  });

  it("retries a server failure or a lost connection, twice", () => {
    expect(retry(0, new ApiError(503, "down"))).toBe(true);
    expect(retry(0, new TypeError("Failed to fetch"))).toBe(true);
    expect(retry(2, new TypeError("Failed to fetch"))).toBe(false);
  });
});
