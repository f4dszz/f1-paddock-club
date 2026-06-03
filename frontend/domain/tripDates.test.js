// Unit tests for domain/tripDates.js (test-coverage-8 + BS-12).
// Co-located per task instruction (domain/<name>.test.js). Covers every
// error+warning branch of validateTripDates plus the BS-12 today-relative
// helpers (isPastIsoDate, pickUpcomingRace) and the all-races-past
// degradation path. A FIXED clock string is used everywhere a "today" is
// needed so this suite stays deterministic as the real calendar drifts.
import { describe, it, expect } from "vitest";
import {
  defaultTripDates,
  validateTripDates,
  isPastIsoDate,
  pickUpcomingRace,
} from "./tripDates.js";

// Frozen reference clock — never use the real Date.now() in assertions so
// the deterministic lane stays deterministic (BS-12).
const TODAY = "2026-06-03";

describe("defaultTripDates", () => {
  it("returns empty strings when no race date", () => {
    expect(defaultTripDates("")).toEqual({ depart: "", ret: "" });
    expect(defaultTripDates(undefined)).toEqual({ depart: "", ret: "" });
    expect(defaultTripDates(null)).toEqual({ depart: "", ret: "" });
  });

  it("offsets -2 / +3 days around race day (UTC)", () => {
    expect(defaultTripDates("2026-05-24")).toEqual({ depart: "2026-05-22", ret: "2026-05-27" });
  });

  it("handles month boundaries", () => {
    expect(defaultTripDates("2026-06-01")).toEqual({ depart: "2026-05-30", ret: "2026-06-04" });
  });

  it("handles year boundaries", () => {
    expect(defaultTripDates("2026-01-01")).toEqual({ depart: "2025-12-30", ret: "2026-01-04" });
  });

  it("returns empty offsets when race date is unparseable", () => {
    expect(defaultTripDates("not-a-date")).toEqual({ depart: "", ret: "" });
  });
});

describe("validateTripDates — error branches", () => {
  it("accepts empty (both blank) as valid with no warnings", () => {
    expect(validateTripDates("", "", "2026-05-24")).toEqual({
      valid: true,
      error: "",
      warnings: [],
    });
  });

  it("rejects when only depart is set", () => {
    const r = validateTripDates("2026-05-22", "", "2026-05-24");
    expect(r.valid).toBe(false);
    expect(r.error).toMatch(/both depart and return/i);
  });

  it("rejects when only return is set", () => {
    const r = validateTripDates("", "2026-05-27", "2026-05-24");
    expect(r.valid).toBe(false);
    expect(r.error).toMatch(/both depart and return/i);
  });

  it("rejects non YYYY-MM-DD format (depart)", () => {
    const r = validateTripDates("2026/05/22", "2026-05-27", "");
    expect(r.valid).toBe(false);
    expect(r.error).toMatch(/YYYY-MM-DD/);
  });

  it("rejects non YYYY-MM-DD format (return)", () => {
    const r = validateTripDates("2026-05-22", "05-27-2026", "");
    expect(r.valid).toBe(false);
    expect(r.error).toMatch(/YYYY-MM-DD/);
  });

  it("rejects a format-valid but calendar-invalid date (Feb 30)", () => {
    const r = validateTripDates("2026-02-30", "2026-03-05", "");
    expect(r.valid).toBe(false);
    expect(r.error).toMatch(/invalid/i);
  });

  it("rejects a format-valid but calendar-invalid return date (month 13)", () => {
    const r = validateTripDates("2026-05-22", "2026-13-01", "");
    expect(r.valid).toBe(false);
    // month 13 fails the YYYY-MM-DD round-trip check first or the parse — either
    // way it must be invalid, never a green pass.
    expect(r.error).toBeTruthy();
  });

  it("rejects depart == return (0-night / day-trip)", () => {
    const same = validateTripDates("2026-05-24", "2026-05-24", "");
    expect(same.valid).toBe(false);
    expect(same.error).toMatch(/strictly before/i);
  });

  it("rejects depart > return (reversed)", () => {
    const reversed = validateTripDates("2026-05-27", "2026-05-22", "");
    expect(reversed.valid).toBe(false);
    expect(reversed.error).toMatch(/strictly before/i);
  });

  it("rejects trips longer than 30 nights", () => {
    const r = validateTripDates("2026-05-01", "2026-06-15", "");
    expect(r.valid).toBe(false);
    expect(r.error).toMatch(/30 nights/);
  });

  it("accepts exactly 30 nights (boundary)", () => {
    const r = validateTripDates("2026-05-01", "2026-05-31", "");
    expect(r.valid).toBe(true);
    expect(r.error).toBe("");
  });

  it("accepts a 1-night trip (minimum)", () => {
    const r = validateTripDates("2026-05-24", "2026-05-25", "");
    expect(r.valid).toBe(true);
    expect(r.warnings).toEqual([]);
  });
});

describe("validateTripDates — warning branches", () => {
  it("warns when arriving after race day", () => {
    const r = validateTripDates("2026-05-25", "2026-05-28", "2026-05-24");
    expect(r.valid).toBe(true);
    expect(r.warnings.some((w) => /miss the Grand Prix/i.test(w))).toBe(true);
  });

  it("warns when leaving before race day", () => {
    const r = validateTripDates("2026-05-20", "2026-05-23", "2026-05-24");
    expect(r.valid).toBe(true);
    expect(r.warnings.some((w) => /won't see the race/i.test(w))).toBe(true);
  });

  it("warns on a long (>14 night) F1 weekend", () => {
    const r = validateTripDates("2026-05-01", "2026-05-20", "2026-05-10");
    expect(r.valid).toBe(true);
    expect(r.warnings.some((w) => /long F1 weekend/i.test(w))).toBe(true);
  });

  it("does NOT warn on a 14-night trip (boundary, not >14)", () => {
    const r = validateTripDates("2026-05-01", "2026-05-15", "2026-05-10");
    expect(r.valid).toBe(true);
    expect(r.warnings.some((w) => /long F1 weekend/i.test(w))).toBe(false);
  });

  it("ignores an unparseable raceDate (no race-relative warnings)", () => {
    const r = validateTripDates("2026-05-22", "2026-05-27", "not-a-date");
    expect(r.valid).toBe(true);
    expect(r.warnings).toEqual([]);
  });

  it("accepts a normal trip around race day with no warnings", () => {
    const r = validateTripDates("2026-05-22", "2026-05-27", "2026-05-24");
    expect(r).toEqual({ valid: true, error: "", warnings: [] });
  });
});

describe("validateTripDates — BS-12 today-relative branch", () => {
  it("does NOT add a past-date warning when no clock is supplied (3-arg legacy caller)", () => {
    // WelcomeForm calls validateTripDates(depart, ret, raceDate) with no 4th
    // arg; that path must stay byte-for-byte unchanged even for past dates.
    const r = validateTripDates("2020-01-01", "2020-01-05", "2020-01-03");
    expect(r.valid).toBe(true);
    expect(r.warnings.some((w) => /in the past/i.test(w))).toBe(false);
  });

  it("warns when depart is before the supplied clock", () => {
    const r = validateTripDates("2026-05-22", "2026-05-27", "2026-05-24", TODAY);
    expect(r.valid).toBe(true);
    expect(r.warnings.some((w) => /in the past/i.test(w))).toBe(true);
  });

  it("does NOT warn when depart is today-or-later relative to the clock", () => {
    const r = validateTripDates("2026-09-04", "2026-09-08", "2026-09-06", TODAY);
    expect(r.valid).toBe(true);
    expect(r.warnings.some((w) => /in the past/i.test(w))).toBe(false);
  });

  it("accepts a Date object as the clock", () => {
    const r = validateTripDates("2026-05-22", "2026-05-27", "2026-05-24", new Date(Date.UTC(2026, 5, 3)));
    expect(r.warnings.some((w) => /in the past/i.test(w))).toBe(true);
  });
});

describe("isPastIsoDate", () => {
  it("returns true for a date strictly before the clock", () => {
    expect(isPastIsoDate("2026-05-24", TODAY)).toBe(true);
  });

  it("returns false for the clock day itself (not strictly before)", () => {
    expect(isPastIsoDate(TODAY, TODAY)).toBe(false);
  });

  it("returns false for a future date", () => {
    expect(isPastIsoDate("2026-09-06", TODAY)).toBe(false);
  });

  it("treats an unparseable target as not-past (never silently degrades)", () => {
    expect(isPastIsoDate("garbage", TODAY)).toBe(false);
    expect(isPastIsoDate("", TODAY)).toBe(false);
  });

  it("returns false when the clock itself is unparseable", () => {
    expect(isPastIsoDate("2020-01-01", "not-a-date")).toBe(false);
  });

  it("accepts a Date object as the clock", () => {
    expect(isPastIsoDate("2026-05-24", new Date(Date.UTC(2026, 5, 3)))).toBe(true);
  });
});

describe("pickUpcomingRace", () => {
  const races = [
    { gp_name: "Past GP", race_date: "2026-03-01" },
    { gp_name: "Italian GP", race_date: "2026-09-06" },
    { gp_name: "Singapore GP", race_date: "2026-10-04" },
    { gp_name: "Recent Past GP", race_date: "2026-05-24" },
  ];

  it("returns the soonest race today-or-later", () => {
    const r = pickUpcomingRace(races, TODAY);
    expect(r).not.toBeNull();
    expect(r.gp_name).toBe("Italian GP");
  });

  it("includes a race scheduled for today (today-or-later, not strictly future)", () => {
    const r = pickUpcomingRace([{ gp_name: "Today GP", race_date: TODAY }], TODAY);
    expect(r.gp_name).toBe("Today GP");
  });

  it("skips entries without a parseable race_date", () => {
    const r = pickUpcomingRace(
      [{ gp_name: "Bad", race_date: "TBD" }, { gp_name: "Good", race_date: "2026-09-06" }],
      TODAY,
    );
    expect(r.gp_name).toBe("Good");
  });

  it("returns null when every race has passed (all-races-past degradation path)", () => {
    const allPast = [
      { gp_name: "A", race_date: "2026-03-01" },
      { gp_name: "B", race_date: "2026-05-24" },
    ];
    expect(pickUpcomingRace(allPast, TODAY)).toBeNull();
  });

  it("returns null for a non-array input", () => {
    expect(pickUpcomingRace(null, TODAY)).toBeNull();
    expect(pickUpcomingRace(undefined, TODAY)).toBeNull();
    expect(pickUpcomingRace({}, TODAY)).toBeNull();
  });

  it("returns null for an empty calendar", () => {
    expect(pickUpcomingRace([], TODAY)).toBeNull();
  });

  it("returns null when the clock is unparseable", () => {
    expect(pickUpcomingRace(races, "not-a-date")).toBeNull();
  });

  it("does not mutate the input array", () => {
    const snapshot = JSON.parse(JSON.stringify(races));
    pickUpcomingRace(races, TODAY);
    expect(races).toEqual(snapshot);
  });
});
