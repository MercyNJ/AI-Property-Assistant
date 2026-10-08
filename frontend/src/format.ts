import type { ToolCall } from "./types";

const kes = new Intl.NumberFormat("en-KE", { maximumFractionDigits: 0 });

export const formatKes = (n: number) => `KES ${kes.format(n)}`;

export function bedroomLabel(type: string, bedrooms: number) {
  if (bedrooms === 0) return type === "bedsitter" ? "Bedsitter" : "Studio";
  return `${bedrooms} bed`;
}

export const capitalise = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** Human-readable summary of what the assistant asked the backend for. */
export function describeToolCall({ name, arguments: a }: ToolCall): string {
  // Arguments are {} when the model's JSON couldn't be parsed.
  if (name === "get_property") return a.property_id != null ? `Looked up listing #${a.property_id}` : "Looked up a listing";
  if (name === "compare_properties") {
    const ids = Array.isArray(a.property_ids) ? a.property_ids : [];
    return ids.length ? `Compared listings ${ids.map((i) => `#${i}`).join(", ")}` : "Compared listings";
  }
  if (name === "search_locations") return a.query ? `Checked locations matching "${a.query}"` : "Checked supported locations";

  const parts: string[] = [];
  if (a.location) parts.push(String(a.location));
  if (a.property_type) parts.push(String(a.property_type));
  if (a.min_bedrooms != null && a.min_bedrooms === a.max_bedrooms) parts.push(`${a.min_bedrooms} bed`);
  else {
    if (a.min_bedrooms != null) parts.push(`${a.min_bedrooms}+ bed`);
    if (a.max_bedrooms != null) parts.push(`up to ${a.max_bedrooms} bed`);
  }
  if (a.min_bathrooms != null) parts.push(`${a.min_bathrooms}+ bath`);
  if (a.max_price_kes != null) parts.push(`up to ${formatKes(Number(a.max_price_kes))}`);
  if (a.furnished === true) parts.push("furnished");
  if (a.furnished === false) parts.push("unfurnished");
  if (a.keywords) parts.push(`"${a.keywords}"`);
  return `Searched listings: ${parts.length ? parts.join(" · ") : "all"}`;
}
