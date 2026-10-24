import type { Highlight } from "./types";

export const HIGHLIGHT_TYPES = [
  { id: "Ace", label: "Ace" },
  { id: "4K", label: "4K" },
  { id: "3K", label: "3K" },
  { id: "2K", label: "2K" },
  { id: "Clutch", label: "Clutch" },
  { id: "Wallbang", label: "Wallbang" },
  { id: "Smoke", label: "Through smoke" },
  { id: "Noscope", label: "Noscope" },
  { id: "Blind", label: "Blind" },
  { id: "Opening", label: "Opening" },
] as const;

export type HighlightTypeId = (typeof HIGHLIGHT_TYPES)[number]["id"];

const KNOWN = new Set<string>(HIGHLIGHT_TYPES.map((item) => item.id));
const MULTI_KILL = new Set(["Ace", "4K", "3K", "2K"]);

/** Badge plus the notes inside a multi-kill, so a 4K wallbang still matches Wallbang. */
export function highlightTypes(highlight: Highlight): HighlightTypeId[] {
  const found = new Set<HighlightTypeId>();
  if (MULTI_KILL.has(highlight.type)) found.add(highlight.type as HighlightTypeId);
  else if (highlight.type.startsWith("1v")) found.add("Clutch");
  else if (KNOWN.has(highlight.type)) found.add(highlight.type as HighlightTypeId);

  const detail = highlight.detail.toLowerCase();
  if (detail.includes("wallbang")) found.add("Wallbang");
  if (/(^|[^a-z])smoke([^a-z]|$)/.test(detail)) found.add("Smoke");
  if (detail.includes("noscope")) found.add("Noscope");
  if (detail.includes("blind")) found.add("Blind");
  if (detail.includes("opening")) found.add("Opening");
  if (detail.includes("clutch")) found.add("Clutch");

  return HIGHLIGHT_TYPES.map((item) => item.id).filter((id) => found.has(id));
}

export function matchesTypeFilter(highlight: Highlight, selected: readonly string[]): boolean {
  if (selected.length === 0) return true;
  return highlightTypes(highlight).some((kind) => selected.includes(kind));
}
