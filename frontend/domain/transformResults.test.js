// Unit tests for domain/transformResults.js (test-coverage-8).
// Covers: priced vs unpriced ("Price not provided"), INFO/LOCAL skipping,
// selectionIndex assignment around skips, _source/_degraded honesty flags,
// and the regex fallbacks for itinerary (line ~70-71) and tour (~78-81).
import { describe, it, expect } from "vitest";
import { transformResults } from "./transformResults.js";

describe("transformResults — tickets", () => {
  it("formats priced tickets and marks them priced", () => {
    const r = transformResults({
      tickets: [{ tag: "PICK", name: "Grandstand", section: "T1", price: 450, currency: "EUR" }],
    });
    expect(r.ticket.items).toHaveLength(1);
    const item = r.ticket.items[0];
    expect(item.priced).toBe(true);
    expect(item.price).toBe("EUR 450");
    expect(item.pv).toBe(450);
    expect(item.selectionIndex).toBe(0);
  });

  it("marks an unpriced ticket as 'Price not provided' and priced=false (INCOMPLETE honesty)", () => {
    const r = transformResults({ tickets: [{ tag: "PICK", name: "GA" }] });
    const item = r.ticket.items[0];
    expect(item.priced).toBe(false);
    expect(item.price).toBe("Price not provided");
    expect(item.pv).toBe(0);
  });

  it("skips INFO tickets but keeps selectionIndex aligned to non-INFO items only", () => {
    const r = transformResults({
      tickets: [
        { tag: "INFO", name: "Note: gates open 9am" },
        { tag: "PICK", name: "Grandstand A", price: 300 },
        { tag: "ALT", name: "Grandstand B", price: 200 },
      ],
    });
    expect(r.ticket.items).toHaveLength(2);
    expect(r.ticket.items[0].main).toBe("Grandstand A");
    expect(r.ticket.items[0].selectionIndex).toBe(0);
    expect(r.ticket.items[1].selectionIndex).toBe(1);
  });

  it("defaults currency to EUR and provider to Formula 1 when absent", () => {
    const r = transformResults({ tickets: [{ name: "Seat", price: 100 }] });
    const item = r.ticket.items[0];
    expect(item.currency).toBe("EUR");
    expect(item.provider).toBe("Formula 1");
    expect(item.tag).toBe("PICK");
  });
});

describe("transformResults — transport", () => {
  it("skips INFO and LOCAL transport rows", () => {
    const r = transformResults({
      transport: [
        { tag: "INFO", summary: "info row" },
        { tag: "LOCAL", summary: "metro day pass" },
        { tag: "OUT", summary: "JFK -> MXP", price: 800, currency: "USD" },
      ],
    });
    expect(r.transport.items).toHaveLength(1);
    expect(r.transport.items[0].main).toBe("JFK -> MXP");
  });

  it("does NOT emit a transport card when every row is filtered out", () => {
    const r = transformResults({
      transport: [{ tag: "INFO", summary: "x" }, { tag: "LOCAL", summary: "y" }],
    });
    expect(r.transport).toBeUndefined();
  });

  it("flags degraded=true when _source is missing (honest degradation)", () => {
    const r = transformResults({ transport: [{ tag: "OUT", summary: "flight", price: 500 }] });
    expect(r.transport.items[0].degraded).toBe(true);
    expect(r.transport.items[0].source).toBe("mock");
  });

  it("flags degraded=false for a live source and degraded=true when _degraded set explicitly", () => {
    const live = transformResults({
      transport: [{ tag: "OUT", summary: "f", price: 500, _source: "google_flights" }],
    });
    expect(live.transport.items[0].degraded).toBe(false);
    expect(live.transport.items[0].source).toBe("google_flights");

    const flagged = transformResults({
      transport: [{ tag: "OUT", summary: "f", price: 500, _source: "google_flights", _degraded: true }],
    });
    expect(flagged.transport.items[0].degraded).toBe(true);
  });

  it("LOCAL still advances selectionIndex before being skipped", () => {
    // selectionIndex is incremented before the LOCAL skip, so a following OUT
    // row gets index 1 (matches the data-testid wiring in ResultCard).
    const r = transformResults({
      transport: [
        { tag: "LOCAL", summary: "metro" },
        { tag: "OUT", summary: "flight", price: 500 },
      ],
    });
    expect(r.transport.items).toHaveLength(1);
    expect(r.transport.items[0].selectionIndex).toBe(1);
  });
});

describe("transformResults — hotel", () => {
  it("formats priced hotel per-night and builds the distance/rating/nights sub", () => {
    const r = transformResults({
      hotel: [
        { tag: "NEAR", name: "Hotel X", price_per_night: 145, currency: "EUR", distance: "8km", rating: 4.5, nights: 5 },
      ],
    });
    const item = r.hotel.items[0];
    expect(item.price).toBe("EUR 145/n");
    expect(item.priced).toBe(true);
    expect(item.sub).toBe("8km · 4.5★ · 5n");
  });

  it("handles a missing nights value with the '?' fallback in sub", () => {
    const r = transformResults({ hotel: [{ name: "H", price_per_night: 100 }] });
    expect(r.hotel.items[0].sub).toContain("?n");
  });

  it("marks an unpriced hotel as not provided", () => {
    const r = transformResults({ hotel: [{ name: "H" }] });
    expect(r.hotel.items[0].priced).toBe(false);
    expect(r.hotel.items[0].price).toBe("Price not provided");
  });

  it("skips INFO hotel rows", () => {
    const r = transformResults({
      hotel: [{ tag: "INFO", name: "note" }, { tag: "NEAR", name: "Real", price_per_night: 100 }],
    });
    expect(r.hotel.items).toHaveLength(1);
    expect(r.hotel.items[0].main).toBe("Real");
  });
});

describe("transformResults — itinerary regex (line ~70-71)", () => {
  it("parses a well-formed 'Day N (Friday): ...' line", () => {
    const r = transformResults({ itinerary: ["Day 1 (Friday): Arrive and check in"] });
    expect(r.plan.items[0].tag).toBe("FRI");
    expect(r.plan.items[0].main).toBe("Arrive and check in");
  });

  it("falls back to D<index> tag and raw line when the format does not match", () => {
    const r = transformResults({ itinerary: ["Just a freeform note with no day prefix"] });
    expect(r.plan.items[0].tag).toBe("D1");
    expect(r.plan.items[0].main).toBe("Just a freeform note with no day prefix");
  });

  it("indexes fallback tags by position", () => {
    const r = transformResults({ itinerary: ["no match a", "no match b"] });
    expect(r.plan.items[0].tag).toBe("D1");
    expect(r.plan.items[1].tag).toBe("D2");
  });
});

describe("transformResults — tour regex (line ~78-81)", () => {
  it("parses a priced tour line 'Name (EUR 50) — desc'", () => {
    const r = transformResults({ tour: ["Colosseum Tour (50) — skip the line"] });
    const item = r.tour.items[0];
    expect(item.priced).toBe(true);
    expect(item.main).toBe("Colosseum Tour");
    expect(item.price).toBe("50");
    expect(item.pv).toBe(50);
    expect(item.sub).toBe("skip the line");
  });

  it("strips leading non-word chars from the parsed name", () => {
    const r = transformResults({ tour: ["• Vatican Museums (30) — guided"] });
    expect(r.tour.items[0].main).toBe("Vatican Museums");
  });

  it("falls back to a substring split when the line does not match the regex", () => {
    const longLine = "A".repeat(60);
    const r = transformResults({ tour: [longLine] });
    const item = r.tour.items[0];
    expect(item.priced).toBe(false);
    expect(item.pv).toBe(0);
    expect(item.price).toBe("");
    expect(item.main).toBe("A".repeat(40));
    expect(item.sub).toBe("A".repeat(20));
  });

  it("falls back to pv=0 when the parenthetical has no leading number", () => {
    const r = transformResults({ tour: ["Free Walk (free) — city center"] });
    const item = r.tour.items[0];
    // matches the regex; parseInt('free') is NaN -> pv falls back to 0.
    expect(item.pv).toBe(0);
    expect(item.price).toBe("free");
  });
});

describe("transformResults — empty / absent inputs", () => {
  it("returns an empty object for empty input", () => {
    expect(transformResults({})).toEqual({});
  });

  it("ignores empty arrays (no cards)", () => {
    const r = transformResults({ tickets: [], transport: [], hotel: [], itinerary: [], tour: [] });
    expect(r).toEqual({});
  });
});
