export type RetentionSegment =
  | "NO_VISITS"
  | "NEW"
  | "RETURNING"
  | "DUE_FOR_RETURN"
  | "INACTIVE";

export const RETENTION_SEGMENT_LABELS: Record<RetentionSegment, string> = {
  NO_VISITS: "No Visits Yet",
  NEW: "New",
  RETURNING: "Returning",
  DUE_FOR_RETURN: "Due for Return",
  INACTIVE: "Inactive",
};

export function retentionSegmentLabel(segment: RetentionSegment | string): string {
  return (
    RETENTION_SEGMENT_LABELS[segment as RetentionSegment] ||
    String(segment).replaceAll("_", " ")
  );
}

export function retentionSegmentExplanation(summary: {
  segment: RetentionSegment | string;
  days_since_last_visit: number | null;
  return_after_days: number;
  inactive_after_days: number;
}): string | null {
  const days = summary.days_since_last_visit;
  if (summary.segment === "DUE_FOR_RETURN" && days !== null) {
    return `This customer has not visited in ${days} days. Your return window is set to ${summary.return_after_days} days.`;
  }
  if (summary.segment === "INACTIVE" && days !== null) {
    return `This customer has not visited in ${days} days. Your inactive threshold is ${summary.inactive_after_days} days.`;
  }
  if (summary.segment === "NO_VISITS") {
    return "This customer has no completed visits yet.";
  }
  if (summary.segment === "NEW") {
    return "This customer has completed one visit.";
  }
  if (summary.segment === "RETURNING" && days !== null) {
    return `This customer last visited ${days} days ago, within your return window.`;
  }
  return null;
}
