const CTAS = new Set(["book", "whatsapp", "call", "directions", "review", "share"]);
const seenPageViews = new Set<string>();

export function resetQuickCardAnalyticsForTests() {
  seenPageViews.clear();
}

export function trackPageView(slug: string) {
  if (!slug || seenPageViews.has(slug)) return;
  seenPageViews.add(slug);
  send(slug, { event_type: "PAGE_VIEW" });
}

export function trackCta(slug: string, cta: string) {
  const key = cta.trim().toLowerCase();
  if (!slug || !CTAS.has(key)) return;
  send(slug, { event_type: "CTA_CLICK", cta: key });
}

function send(slug: string, body: { event_type: string; cta?: string }) {
  const path = `/api/v1/public/quickcards/${encodeURIComponent(slug)}/events/`;
  void fetch(path, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body),
    credentials: "omit",
    cache: "no-store",
    keepalive: true,
  }).catch(() => undefined);
}
