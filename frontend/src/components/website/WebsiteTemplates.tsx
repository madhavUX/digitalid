import type { PublicSalonSite } from "@/lib/api/types";
import Link from "next/link";
import { formatMoney, telHref, whatsappHref } from "./siteUtils";

type Props = {
  data: PublicSalonSite;
  preview?: boolean;
};

function BookButton({ data, className }: { data: PublicSalonSite; className?: string }) {
  return (
    <Link className={className || "ws-btn ws-btn-primary"} href={data.booking.path}>
      Book a Slot
    </Link>
  );
}

function SiteHeader({ data }: { data: PublicSalonSite }) {
  return (
    <header className="ws-header">
      <div className="ws-wrap ws-header-inner">
        <a className="ws-brand" href="#top">
          {data.business.logo_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={data.business.logo_url} alt="" className="ws-logo" />
          ) : null}
          <span>{data.business.name}</span>
        </a>
        <nav className="ws-nav" aria-label="Primary">
          <a href="#services">Services</a>
          {data.staff.length ? <a href="#team">Team</a> : null}
          <a href="#hours">Hours</a>
          <a href="#location">Location</a>
          <a href="#contact">Contact</a>
        </nav>
        <BookButton data={data} className="ws-btn ws-btn-primary ws-header-cta" />
      </div>
    </header>
  );
}

function ServicesSection({ data }: { data: PublicSalonSite }) {
  if (!data.services.length) return null;
  return (
    <section id="services" className="ws-section">
      <div className="ws-wrap">
        <h2>Services</h2>
        <p className="ws-lead">Bookable treatments at {data.location.name}.</p>
        <ul className="ws-services">
          {data.services.map((service) => (
            <li key={service.id}>
              <div>
                <h3>{service.name}</h3>
                {service.description ? <p>{service.description}</p> : null}
              </div>
              <div className="ws-service-meta">
                <span>{service.duration_minutes} min</span>
                <strong>{formatMoney(service.price, service.currency)}</strong>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function TeamSection({ data }: { data: PublicSalonSite }) {
  if (!data.staff.length) return null;
  return (
    <section id="team" className="ws-section ws-section-alt">
      <div className="ws-wrap">
        <h2>Our team</h2>
        <ul className="ws-team">
          {data.staff.map((member) => (
            <li key={member.id}>
              <div className="ws-avatar" aria-hidden>
                {member.photo_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={member.photo_url} alt="" />
                ) : (
                  <span>{member.display_name.slice(0, 1)}</span>
                )}
              </div>
              <h3>{member.display_name}</h3>
              {member.title ? <p className="ws-muted">{member.title}</p> : null}
              {member.bio ? <p>{member.bio}</p> : null}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function HoursSection({ data }: { data: PublicSalonSite }) {
  return (
    <section id="hours" className="ws-section">
      <div className="ws-wrap">
        <h2>Opening hours</h2>
        <ul className="ws-hours">
          {data.hours.map((row) => (
            <li key={row.weekday}>
              <span>{row.label}</span>
              <span>
                {row.closed
                  ? "Closed"
                  : `${row.opens_at} – ${row.closes_at}`}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function LocationSection({ data }: { data: PublicSalonSite }) {
  return (
    <section id="location" className="ws-section ws-section-alt">
      <div className="ws-wrap">
        <h2>Location</h2>
        <p className="ws-place">
          <strong>{data.business.name}</strong>
          <br />
          {data.location.name}
          {data.location.city ? `, ${data.location.city}` : ""}
        </p>
        {data.location.address ? <p>{data.location.address}</p> : null}
        {data.social.google_maps ? (
          <a className="ws-btn ws-btn-ghost" href={data.social.google_maps} target="_blank" rel="noreferrer">
            Directions
          </a>
        ) : null}
      </div>
    </section>
  );
}

function ContactSection({ data }: { data: PublicSalonSite }) {
  const hasContact =
    data.contact.phone || data.contact.whatsapp || data.social.instagram || data.social.facebook;
  if (!hasContact) return null;
  return (
    <section id="contact" className="ws-section">
      <div className="ws-wrap">
        <h2>Contact</h2>
        <div className="ws-actions">
          {data.contact.phone ? (
            <a className="ws-btn ws-btn-ghost" href={telHref(data.contact.phone)}>
              Call
            </a>
          ) : null}
          {data.contact.whatsapp ? (
            <a
              className="ws-btn ws-btn-ghost"
              href={whatsappHref(data.contact.whatsapp)}
              target="_blank"
              rel="noreferrer"
            >
              WhatsApp
            </a>
          ) : null}
          {data.social.instagram ? (
            <a className="ws-btn ws-btn-ghost" href={data.social.instagram} target="_blank" rel="noreferrer">
              Instagram
            </a>
          ) : null}
          {data.social.facebook ? (
            <a className="ws-btn ws-btn-ghost" href={data.social.facebook} target="_blank" rel="noreferrer">
              Facebook
            </a>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function Footer({ data }: { data: PublicSalonSite }) {
  return (
    <footer className="ws-footer">
      <div className="ws-wrap">
        <p>{data.business.name}</p>
        {data.quickcard?.path ? (
          <p>
            <Link href={data.quickcard.path}>QuickCard</Link>
          </p>
        ) : null}
        <p className="ws-muted">Powered by BookAnything</p>
      </div>
    </footer>
  );
}

function StickyBook({ data }: { data: PublicSalonSite }) {
  return (
    <div className="ws-sticky-book">
      <BookButton data={data} />
    </div>
  );
}

export function SalonModernTemplate({ data, preview }: Props) {
  return (
    <div className={`ws-root ws-modern${preview ? " ws-preview" : ""}`} id="top">
      {preview ? <div className="ws-preview-banner">Preview — not public</div> : null}
      <SiteHeader data={data} />
      <section className="ws-hero ws-hero-modern">
        <div className="ws-wrap ws-hero-grid">
          <div>
            <p className="ws-eyebrow">{data.business.category}</p>
            <h1>{data.hero.headline}</h1>
            <p className="ws-lead">{data.hero.tagline}</p>
            <div className="ws-actions">
              <BookButton data={data} />
              {data.contact.whatsapp ? (
                <a className="ws-btn ws-btn-ghost" href={whatsappHref(data.contact.whatsapp)}>
                  WhatsApp
                </a>
              ) : null}
            </div>
          </div>
          <div className={`ws-hero-visual${data.hero.cover_image_url ? "" : " ws-hero-fallback"}`}>
            {data.hero.cover_image_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={data.hero.cover_image_url} alt={`${data.business.name} salon`} />
            ) : (
              <div className="ws-hero-fallback-inner" aria-hidden>
                <span>{data.business.name}</span>
              </div>
            )}
          </div>
        </div>
      </section>
      <ServicesSection data={data} />
      {data.hero.description || data.business.description ? (
        <section className="ws-section ws-section-alt" id="about">
          <div className="ws-wrap">
            <h2>About</h2>
            <p className="ws-lead">{data.hero.description || data.business.description}</p>
          </div>
        </section>
      ) : null}
      <TeamSection data={data} />
      <HoursSection data={data} />
      <LocationSection data={data} />
      <ContactSection data={data} />
      <section className="ws-cta-final">
        <div className="ws-wrap">
          <h2>Ready for your next visit?</h2>
          <BookButton data={data} />
        </div>
      </section>
      <Footer data={data} />
      <StickyBook data={data} />
    </div>
  );
}

export function SalonClassicTemplate({ data, preview }: Props) {
  return (
    <div className={`ws-root ws-classic${preview ? " ws-preview" : ""}`} id="top">
      {preview ? <div className="ws-preview-banner">Preview — not public</div> : null}
      <SiteHeader data={data} />
      <section className="ws-hero ws-hero-classic">
        <div className="ws-wrap">
          <p className="ws-eyebrow">Established salon · {data.location.city || data.location.name}</p>
          <h1>{data.business.name}</h1>
          <p className="ws-lead">{data.hero.tagline}</p>
          <BookButton data={data} />
        </div>
      </section>
      <ServicesSection data={data} />
      {data.hero.description || data.business.description ? (
        <section className="ws-section" id="about">
          <div className="ws-wrap ws-classic-frame">
            <h2>About our salon</h2>
            <p>{data.hero.description || data.business.description}</p>
          </div>
        </section>
      ) : null}
      <TeamSection data={data} />
      <HoursSection data={data} />
      <LocationSection data={data} />
      <ContactSection data={data} />
      <section className="ws-cta-final ws-classic-cta">
        <div className="ws-wrap">
          <h2>Book your appointment</h2>
          <BookButton data={data} />
        </div>
      </section>
      <Footer data={data} />
      <StickyBook data={data} />
    </div>
  );
}

export function SalonLuxuryTemplate({ data, preview }: Props) {
  return (
    <div className={`ws-root ws-luxury${preview ? " ws-preview" : ""}`} id="top">
      {preview ? <div className="ws-preview-banner">Preview — not public</div> : null}
      <SiteHeader data={data} />
      <section className="ws-hero ws-hero-luxury">
        <div
          className="ws-luxury-backdrop"
          style={
            data.hero.cover_image_url
              ? { backgroundImage: `url(${data.hero.cover_image_url})` }
              : undefined
          }
        />
        <div className="ws-wrap ws-luxury-copy">
          <p className="ws-eyebrow">Luxury salon experience</p>
          <h1>{data.hero.headline}</h1>
          <p className="ws-lead">{data.hero.tagline}</p>
          <BookButton data={data} />
        </div>
      </section>
      <ServicesSection data={data} />
      <TeamSection data={data} />
      {data.hero.description || data.business.description ? (
        <section className="ws-section" id="about">
          <div className="ws-wrap">
            <h2>The experience</h2>
            <p className="ws-lead">{data.hero.description || data.business.description}</p>
          </div>
        </section>
      ) : null}
      <HoursSection data={data} />
      <LocationSection data={data} />
      <ContactSection data={data} />
      <section className="ws-cta-final ws-luxury-cta">
        <div className="ws-wrap">
          <h2>Reserve your time</h2>
          <BookButton data={data} />
        </div>
      </section>
      <Footer data={data} />
      <StickyBook data={data} />
    </div>
  );
}

export function WebsiteTemplateRenderer({ data, preview = false }: Props) {
  switch (data.template) {
    case "SALON_CLASSIC":
      return <SalonClassicTemplate data={data} preview={preview} />;
    case "SALON_LUXURY":
      return <SalonLuxuryTemplate data={data} preview={preview} />;
    case "SALON_MODERN":
    default:
      return <SalonModernTemplate data={data} preview={preview} />;
  }
}
