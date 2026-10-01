import type { PublicSalonSite } from "@/lib/api/types";

export function formatMoney(price: string, currency: string) {
  const amount = Number(price);
  if (Number.isFinite(amount) && currency === "INR") {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 0,
    }).format(amount);
  }
  return `${currency} ${price}`;
}

export function whatsappHref(phone: string) {
  const digits = phone.replace(/\D/g, "");
  return `https://wa.me/${digits}`;
}

export function telHref(phone: string) {
  return `tel:${phone.replace(/\s+/g, "")}`;
}

export function localBusinessJsonLd(data: PublicSalonSite) {
  const address = data.location.address_parts;
  const openingHours = data.hours
    .filter((row) => !row.closed && row.opens_at && row.closes_at)
    .map((row) => {
      const day = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][
        row.weekday
      ];
      return `${day} ${row.opens_at}-${row.closes_at}`;
    });

  return {
    "@context": "https://schema.org",
    "@type": "LocalBusiness",
    name: data.business.name,
    description: data.seo.description,
    url: data.site.url,
    image: data.seo.og_image || undefined,
    telephone: data.contact.phone || undefined,
    address: {
      "@type": "PostalAddress",
      streetAddress: [address.line1, address.line2].filter(Boolean).join(", ") || undefined,
      addressLocality: address.city || undefined,
      addressRegion: address.state || undefined,
      postalCode: address.postal_code || undefined,
      addressCountry: address.country || undefined,
    },
    openingHours: openingHours.length ? openingHours : undefined,
  };
}
