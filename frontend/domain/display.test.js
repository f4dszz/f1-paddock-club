// Unit tests for domain/display.js helpers (test-coverage-8).
// Covers sourceLabel/sourceColor (known + unknown fallback), linkActionLabel
// (homepage+medium special case + table lookups + default), constraintLabels,
// and describeConstraintMatch (every key branch + generic fallback).
import { describe, it, expect } from "vitest";
import {
  sourceLabel,
  sourceColor,
  linkActionLabel,
  constraintLabels,
  describeConstraintMatch,
  SOURCE_LABELS,
} from "./display.js";

describe("sourceLabel", () => {
  it("maps known sources to their honest label text", () => {
    expect(sourceLabel("google_flights")).toBe("Live · SerpAPI");
    expect(sourceLabel("llm_estimate")).toBe("Estimated · LLM");
    expect(sourceLabel("mock")).toBe("Mock data");
  });

  it("falls back to the raw source string when unknown", () => {
    expect(sourceLabel("some_new_provider")).toBe("some_new_provider");
  });

  it("falls back to 'unknown' for null/empty source", () => {
    expect(sourceLabel("")).toBe("unknown");
    expect(sourceLabel(null)).toBe("unknown");
    expect(sourceLabel(undefined)).toBe("unknown");
  });

  it("every SOURCE_LABELS entry has matching label text", () => {
    for (const [src, def] of Object.entries(SOURCE_LABELS)) {
      expect(sourceLabel(src)).toBe(def.text);
    }
  });
});

describe("sourceColor", () => {
  it("maps known sources to their color", () => {
    expect(sourceColor("google_hotels")).toBe("#22C55E");
    expect(sourceColor("llm_estimate")).toBe("#F59E0B");
    expect(sourceColor("mock")).toBe("#6B7280");
  });

  it("falls back to grey for unknown/empty source", () => {
    expect(sourceColor("nope")).toBe("#6B7280");
    expect(sourceColor("")).toBe("#6B7280");
    expect(sourceColor(undefined)).toBe("#6B7280");
  });
});

describe("linkActionLabel", () => {
  it("uses the external-provider phrasing for homepage + medium confidence", () => {
    expect(linkActionLabel({ linkType: "homepage", bookingConfidence: "medium" })).toBe(
      "Open external provider site",
    );
  });

  it("uses the homepage table label when confidence is not medium", () => {
    expect(linkActionLabel({ linkType: "homepage", bookingConfidence: "high" })).toBe(
      "Open provider homepage",
    );
  });

  it("maps known link types to their action labels", () => {
    expect(linkActionLabel({ linkType: "deeplink" })).toBe("Open direct provider link");
    expect(linkActionLabel({ linkType: "official_ticket_page" })).toBe("Open official ticket page");
    expect(linkActionLabel({ linkType: "flight_search" })).toBe("Open flight search");
  });

  it("falls back to 'Open provider' for an unknown link type", () => {
    expect(linkActionLabel({ linkType: "mystery" })).toBe("Open provider");
  });

  it("handles null/undefined item without throwing", () => {
    expect(linkActionLabel(null)).toBe("Open provider");
    expect(linkActionLabel(undefined)).toBe("Open provider");
    expect(linkActionLabel({})).toBe("Open provider");
  });
});

describe("constraintLabels", () => {
  it("returns an empty array for null / no constraints", () => {
    expect(constraintLabels(null)).toEqual([]);
    expect(constraintLabels({})).toEqual([]);
  });

  it("labels direct-only, brands, dietary, accessibility, and avoid-luxury", () => {
    const labels = constraintLabels({
      direct_only: true,
      allowed_hotel_brands: ["Marriott", "Hilton"],
      dietary: "vegetarian",
      accessibility: true,
      avoid_luxury: true,
    });
    expect(labels).toContain("Direct flights only");
    expect(labels).toContain("Hotels: Marriott / Hilton");
    expect(labels).toContain("Dietary: vegetarian");
    expect(labels).toContain("Accessibility");
    expect(labels).toContain("Avoid luxury");
  });

  it("labels a non-balanced budget strategy but omits 'balanced'", () => {
    expect(constraintLabels({ budget_strategy: "luxury" })).toContain("Budget: luxury");
    expect(constraintLabels({ budget_strategy: "balanced" })).toEqual([]);
  });

  it("omits an empty allowed_hotel_brands array", () => {
    expect(constraintLabels({ allowed_hotel_brands: [] })).toEqual([]);
  });
});

describe("describeConstraintMatch", () => {
  it("describes direct_only when truthy", () => {
    expect(describeConstraintMatch("direct_only", true)).toBe("Direct flights only");
  });

  it("describes a matched hotel brand object", () => {
    expect(describeConstraintMatch("allowed_hotel_brands", { matched: "Marriott" })).toBe(
      "Hotel brand: Marriott",
    );
  });

  it("falls back to 'matched' when the brand object lacks .matched", () => {
    expect(describeConstraintMatch("allowed_hotel_brands", {})).toBe("Hotel brand: matched");
  });

  it("describes accessibility requested vs not required", () => {
    expect(describeConstraintMatch("accessibility", true)).toBe("Accessibility requested");
    expect(describeConstraintMatch("accessibility", false)).toBe("Accessibility not required");
  });

  it("describes avoid_luxury when truthy", () => {
    expect(describeConstraintMatch("avoid_luxury", true)).toBe("Avoid luxury");
  });

  it("describes a dietary string", () => {
    expect(describeConstraintMatch("dietary", "vegan")).toBe("Dietary: vegan");
  });

  it("describes a non-string dietary as matched", () => {
    expect(describeConstraintMatch("dietary", true)).toBe("Dietary: matched");
  });

  it("falls back to key: value for unknown keys (object stringified)", () => {
    expect(describeConstraintMatch("custom", { a: 1 })).toBe('custom: {"a":1}');
    expect(describeConstraintMatch("custom", "x")).toBe("custom: x");
  });
});
