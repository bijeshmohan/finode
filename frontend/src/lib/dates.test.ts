import { describe, expect, it } from "vitest";

import { dateCases } from "./cases";
import { dateChip, friendlyDate, shortDate } from "./dates";

describe("days are written as the server writes them, against the server's today", () => {
  it.each(dateCases.friendlyDate)("friendlyDate(%s, today %s) → %s", (day, today, expected) => {
    expect(friendlyDate(day, today)).toBe(expected);
  });
  it.each(dateCases.shortDate)("shortDate(%s, today %s) → %s", (day, today, expected) => {
    expect(shortDate(day, today)).toBe(expected);
  });
  it.each(dateCases.dateChip)("dateChip(%s, today %s) → %s", (day, today, expected) => {
    expect(dateChip(day, today)).toBe(expected);
  });

  it("ignores the device's own clock and time zone", () => {
    const zone = process.env.TZ;
    process.env.TZ = "Pacific/Kiritimati"; // UTC+14: already tomorrow for most of the world
    try {
      expect(friendlyDate("2026-11-13", "2026-11-13")).toBe("Today");
      expect(shortDate("2026-01-01", "2026-01-01")).toBe("1 Jan");
    } finally {
      process.env.TZ = zone;
    }
  });
});
