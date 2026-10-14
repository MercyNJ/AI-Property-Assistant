import { describe, expect, it } from "vitest";
import { bedroomLabel, capitalise, describeToolCall, formatKes } from "./format";

describe("formatKes", () => {
  it("groups thousands and has no decimals", () => {
    expect(formatKes(80000)).toBe("KES 80,000");
    expect(formatKes(350000)).toBe("KES 350,000");
    expect(formatKes(7000.6)).toBe("KES 7,001");
  });
});

describe("bedroomLabel", () => {
  it("names zero-bedroom types and counts the rest", () => {
    expect(bedroomLabel("studio", 0)).toBe("Studio");
    expect(bedroomLabel("bedsitter", 0)).toBe("Bedsitter");
    expect(bedroomLabel("apartment", 3)).toBe("3 bed");
  });
});

describe("capitalise", () => {
  it("upper-cases only the first letter", () => {
    expect(capitalise("maisonette")).toBe("Maisonette");
    expect(capitalise("")).toBe("");
  });
});

const search = (args: Record<string, unknown>) => describeToolCall({ name: "search_properties", arguments: args });

describe("describeToolCall", () => {
  it("summarises a full search in reading order", () => {
    expect(
      search({
        location: "Ruiru",
        property_type: "apartment",
        min_bedrooms: 3,
        max_bedrooms: 3,
        max_price_kes: 80000,
        furnished: true,
        keywords: "pool",
      }),
    ).toBe('Searched listings: Ruiru · apartment · 3 bed · up to KES 80,000 · furnished · "pool"');
  });

  it("distinguishes exact, minimum and maximum bedrooms", () => {
    expect(search({ min_bedrooms: 2, max_bedrooms: 2 })).toBe("Searched listings: 2 bed");
    expect(search({ min_bedrooms: 2 })).toBe("Searched listings: 2+ bed");
    expect(search({ max_bedrooms: 2 })).toBe("Searched listings: up to 2 bed");
    expect(search({ min_bedrooms: 1, max_bedrooms: 3 })).toBe("Searched listings: 1+ bed · up to 3 bed");
  });

  it("shows unfurnished and bathrooms, and 'all' with no filters", () => {
    expect(search({ furnished: false, min_bathrooms: 2 })).toBe("Searched listings: 2+ bath · unfurnished");
    expect(search({})).toBe("Searched listings: all");
  });

  it("labels the other tools", () => {
    expect(describeToolCall({ name: "get_property", arguments: { property_id: 27 } })).toBe("Looked up listing #27");
    expect(describeToolCall({ name: "compare_properties", arguments: { property_ids: [2, 4] } })).toBe(
      "Compared listings #2, #4",
    );
    expect(describeToolCall({ name: "search_locations", arguments: { query: "Ruiru" } })).toBe(
      'Checked locations matching "Ruiru"',
    );
    expect(describeToolCall({ name: "search_locations", arguments: { query: null } })).toBe(
      "Checked supported locations",
    );
  });

  it("falls back to generic labels when arguments couldn't be parsed", () => {
    // The backend sends {} for unparseable arguments; this used to crash the UI.
    expect(describeToolCall({ name: "get_property", arguments: {} })).toBe("Looked up a listing");
    expect(describeToolCall({ name: "compare_properties", arguments: {} })).toBe("Compared listings");
    expect(describeToolCall({ name: "compare_properties", arguments: { property_ids: "2,4" } })).toBe(
      "Compared listings",
    );
  });
});
