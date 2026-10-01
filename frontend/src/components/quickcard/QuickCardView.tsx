"use client";

import { formatMoney } from "@/lib/booking/format";
import type { PublicQuickCard, QuickCardActions } from "@/lib/api/types";
import Link from "next/link";
import { useEffect, useState } from "react";
import { trackCta, trackPageView } from "@/lib/quickcard/quickCardAnalytics";

function externalProps(href: string) {
  if (href.startsWith("tel:") || href.startsWith("/")) return {};
  return { target: "_blank", rel: "noopener noreferrer" };
}

function ContactActions({ actions }: { actions: QuickCardActions }) {
  const items: { href: string; label: string; cta: string }[] = [];
  if (actions.whatsapp_url) {
    items.push({ href: actions.whatsapp_url, label: "WhatsApp", cta: "whatsapp" });
  }
  if (actions.call_url) {
    items.push({ href: actions.call_url, label: "Call", cta: "call" });
  }
  if (actions.directions_url) {
    items.push({ href: actions.directions_url, label: "Directions", cta: "directions" });
  }
  return (
    <div className="qc-contact" aria-label="Contact">
      {items.map((item) => (
        <a
          key={item.cta}
          className="qc-contact-btn"
          href={item.href}
          data-cta={item.cta}
          {...externalProps(item.href)}
        >
          {item.label}
        </a>
      ))}
      <ShareButton />
    </div>
  );
}

function ShareButton() {
  const [status, setStatus] = useState("");

  async function shareCard() {
    const main = document.querySelector("[data-quickcard]");
    const name = main?.getAttribute("data-share-name") || "Business";
    const text = main?.getAttribute("data-share-text") || "";
    const url = window.location.href;
    const payload = { title: name, text: text ? `${text}\n${url}` : url, url };
    if (typeof navigator.share === "function") {
      try {
        await navigator.share(payload);
        setStatus("Shared");
        return;
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
      }
    }
    try {
      await navigator.clipboard.writeText([name, text, url].filter(Boolean).join("\n"));
      setStatus("Link copied");
    } catch {
      setStatus(url);
    }
  }

  return (
    <button type="button" className="qc-contact-btn" data-cta="share" onClick={() => void shareCard()}>
      {status || "Share"}
    </button>
  );
}

export function QuickCardView({ data }: { data: PublicQuickCard }) {
  const { quickcard: qc, business, services, staff, hours, booking, actions } = data;
  const logo = qc.logo_url || business.logo || "";
  const cover = qc.cover_image_url;
  const openDays = hours.filter((h) => !h.closed);
  const shortText = qc.headline || qc.description || business.description || "";
  const email = data.location.email?.trim();

  useEffect(() => {
    trackPageView(data.slug);
  }, [data.slug]);

  function onCta(event: React.MouseEvent) {
    const target = (event.target as HTMLElement | null)?.closest?.("[data-cta]");
    const cta = target?.getAttribute("data-cta");
    if (!cta) return;
    try {
      trackCta(data.slug, cta);
    } catch {
      // Navigation and share still run.
    }
  }

  return (
    <main
      className="qc-page"
      data-quickcard
      data-share-name={business.name}
      data-share-text={shortText}
      onClick={onCta}
    >
      <div
        className="qc-cover"
        style={cover ? { backgroundImage: `url(${cover})` } : undefined}
        role={cover ? "img" : undefined}
        aria-label={cover ? `${business.name} cover` : undefined}
      />
      <div className="qc-shell">
        <header className="qc-hero">
          {logo ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img className="qc-logo" src={logo} alt={`${business.name} logo`} />
          ) : (
            <div className="qc-logo qc-logo-fallback" aria-hidden>
              {business.name.slice(0, 1)}
            </div>
          )}
          <p className="qc-kicker">{business.vertical}</p>
          <h1>{business.name}</h1>
          {data.location.name && data.location.name !== business.name ? (
            <p className="qc-muted">{data.location.name}</p>
          ) : null}
          {qc.headline ? <p className="qc-headline">{qc.headline}</p> : null}
          {qc.description ? <p className="qc-lede">{qc.description}</p> : null}
          <Link
            className="qc-cta"
            href={actions.booking_url || booking.booking_path}
            data-testid="book-slot-cta"
            data-cta="book"
          >
            Book Now
          </Link>
        </header>

        <ContactActions actions={actions} />

        {actions.review_url ? (
          <p className="qc-review-cta">
            <a
              href={actions.review_url}
              data-cta="review"
              target="_blank"
              rel="noopener noreferrer"
            >
              Leave a Google Review
            </a>
          </p>
        ) : null}

        <section className="qc-section" aria-labelledby="qc-services">
          <h2 id="qc-services">Services</h2>
          {services.length === 0 ? (
            <p className="qc-muted">Services will appear here when published.</p>
          ) : (
            <ul className="qc-service-list">
              {services.map((service) => (
                <li key={service.id}>
                  <div>
                    <strong>{service.name}</strong>
                    {service.description ? <p>{service.description}</p> : null}
                    <span className="qc-muted">
                      {service.category ? `${service.category.name} · ` : ""}
                      {service.duration_minutes} minutes
                    </span>
                  </div>
                  <span className="qc-price">
                    {formatMoney(service.price, service.currency)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        {(business.description || business.address || email) && (
          <section className="qc-section" aria-labelledby="qc-about">
            <h2 id="qc-about">About</h2>
            {business.description ? <p>{business.description}</p> : null}
            {business.address ? <p>{business.address}</p> : null}
            {email ? (
              <p>
                <a href={`mailto:${email}`}>{email}</a>
              </p>
            ) : null}
          </section>
        )}

        {openDays.length > 0 ? (
          <section className="qc-section" aria-labelledby="qc-hours">
            <h2 id="qc-hours">Opening hours</h2>
            <ul className="qc-hours">
              {hours.map((day) => (
                <li key={day.weekday}>
                  <span>{day.label}</span>
                  <span>
                    {day.closed ? "Closed" : `${day.opens_at} – ${day.closes_at}`}
                  </span>
                </li>
              ))}
            </ul>
            <p className="qc-muted qc-fine">Hours reflect when staff are bookable online.</p>
          </section>
        ) : null}

        {staff.length > 0 ? (
          <section className="qc-section" aria-labelledby="qc-staff">
            <h2 id="qc-staff">Staff</h2>
            <ul className="qc-staff-list">
              {staff.map((member) => (
                <li key={member.id}>
                  <strong>{member.display_name}</strong>
                  {member.title ? <span className="qc-muted">{member.title}</span> : null}
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {(qc.instagram_url || qc.facebook_url || qc.website_url) && (
          <section className="qc-section" aria-labelledby="qc-social">
            <h2 id="qc-social">Links</h2>
            <div className="qc-social">
              {qc.instagram_url ? (
                <a href={qc.instagram_url} target="_blank" rel="noopener noreferrer">
                  Instagram
                </a>
              ) : null}
              {qc.facebook_url ? (
                <a href={qc.facebook_url} target="_blank" rel="noopener noreferrer">
                  Facebook
                </a>
              ) : null}
              {qc.website_url ? (
                <a href={qc.website_url} target="_blank" rel="noopener noreferrer">
                  Website
                </a>
              ) : null}
            </div>
          </section>
        )}

        <footer className="qc-footer">
          <p>{data.location.name}</p>
          <p className="qc-muted">Powered by QuickCard</p>
        </footer>
      </div>
      <div className="qc-sticky">
        <Link href={actions.booking_url || booking.booking_path} data-cta="book">
          Book Now
        </Link>
      </div>
    </main>
  );
}
