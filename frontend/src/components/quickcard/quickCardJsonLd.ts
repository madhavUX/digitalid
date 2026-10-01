import type { PublicQuickCard } from "@/lib/api/types";

export function quickCardJsonLd(data: PublicQuickCard) {
  const address = data.location.address;
  const openingHours = data.hours
    .filter((row) => !row.closed && row.opens_at && row.closes_at)
    .map((row) => `${row.label} ${row.opens_at}-${row.closes_at}`);

  return {
    "@context": "https://schema.org",
    "@type": "LocalBusiness",
    name: data.business.name,
    description: data.seo.description,
    url: data.actions.share_url,
    image: data.seo.og_image || undefined,
    telephone: data.location.phone || undefined,
    email: data.location.email || undefined,
    address: {
      "@type": "PostalAddress",
      streetAddress: [address.line1, address.line2].filter(Boolean).join(", ") || undefined,
      addressLocality: address.city || undefined,
      addressRegion: address.state || undefined,
      postalCode: address.postal_code || undefined,
      addressCountry: address.country || undefined,
    },
    openingHours: openingHours.length ? openingHours : undefined,
    makesOffer: data.services.map((service) => ({
      "@type": "Offer",
      name: service.name,
      price: service.price,
      priceCurrency: service.currency,
    })),
  };
}
