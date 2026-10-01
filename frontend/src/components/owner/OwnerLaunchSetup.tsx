"use client";

import { OwnerGoogleBusinessCard } from "@/components/owner/OwnerGoogleBusinessCard";
import { OwnerWhatsAppCard } from "@/components/owner/OwnerWhatsAppCard";
import {
  getBusinessLaunchProfile,
  publishWebsite,
  updateBusinessLaunchProfile,
} from "@/lib/api/ownerApi";
import type { BusinessLaunchStatus } from "@/lib/api/types";
import { useCallback, useEffect, useState } from "react";

type Props = {
  token: string;
  businessId: string;
  locationId: string;
  busy?: boolean;
  onBusy?: (value: boolean) => void;
  onMessage?: (message: string) => void;
  onError?: (error: unknown) => void;
  onReadyChange?: (launch: BusinessLaunchStatus) => void;
  showFinish?: boolean;
  onFinish?: () => void;
  onBack?: () => void;
};

const CHECKLIST_LABELS: { key: string; label: string }[] = [
  { key: "business", label: "Business" },
  { key: "location", label: "Location" },
  { key: "services", label: "Services" },
  { key: "staff", label: "Staff" },
  { key: "availability", label: "Availability" },
  { key: "template", label: "Template" },
  { key: "quickcard", label: "QuickCard" },
  { key: "booking", label: "Booking" },
];

export function OwnerLaunchSetup({
  token,
  businessId,
  locationId,
  busy = false,
  onBusy,
  onMessage,
  onError,
  onReadyChange,
  showFinish = false,
  onFinish,
  onBack,
}: Props) {
  const [launch, setLaunch] = useState<BusinessLaunchStatus | null>(null);
  const [templateKey, setTemplateKey] = useState("");
  const [subdomain, setSubdomain] = useState("");
  const [customDomain, setCustomDomain] = useState("");
  const [googleUrl, setGoogleUrl] = useState("");
  const [reviewUrl, setReviewUrl] = useState("");
  const [googleStatus, setGoogleStatus] = useState("NOT_STARTED");

  const load = useCallback(async () => {
    if (!token || !businessId || !locationId) return;
    try {
      const data = await getBusinessLaunchProfile(businessId, token, locationId);
      setLaunch(data);
      setTemplateKey(data.template.key || "");
      setSubdomain(data.domain.subdomain || "");
      setCustomDomain(data.domain.custom_domain || "");
      setGoogleUrl(data.google_business.url || "");
      setReviewUrl(data.google_business.review_url || "");
      setGoogleStatus(data.google_business.status || "NOT_STARTED");
      onReadyChange?.(data);
    } catch (err) {
      onError?.(err);
    }
  }, [token, businessId, locationId, onError, onReadyChange]);

  useEffect(() => {
    void load();
  }, [load]);

  async function save(partial: Record<string, unknown>, message: string) {
    onBusy?.(true);
    try {
      const result = await updateBusinessLaunchProfile(
        businessId,
        token,
        partial,
        locationId,
      );
      setLaunch(result.launch);
      onReadyChange?.(result.launch);
      onMessage?.(message);
    } catch (err) {
      onError?.(err);
    } finally {
      onBusy?.(false);
    }
  }

  async function publish() {
    onBusy?.(true);
    try {
      await publishWebsite(businessId, token, locationId);
      const data = await getBusinessLaunchProfile(businessId, token, locationId);
      setLaunch(data);
      onReadyChange?.(data);
      onMessage?.("Website published");
    } catch (err) {
      onError?.(err);
    } finally {
      onBusy?.(false);
    }
  }

  if (!launch) {
    return <p className="muted">Loading launch setup…</p>;
  }

  return (
    <div className="owner-launch-setup">
      <section className="owner-card">
        <h2>Choose your website design</h2>
        <fieldset className="owner-radio-group owner-template-grid">
          <legend className="sr-only">Website template</legend>
          {launch.template.options.map((option) => (
            <label
              key={option.key}
              className={`owner-template-card${templateKey === option.key ? " selected" : ""}`}
            >
              <input
                type="radio"
                name="template"
                value={option.key}
                checked={templateKey === option.key}
                onChange={() => setTemplateKey(option.key)}
                aria-label={option.label}
              />
              <span className="owner-template-preview" aria-hidden>
                {option.label}
              </span>
              <span>
                <strong>{option.label}</strong>
                <br />
                <span className="muted">{option.description}</span>
              </span>
            </label>
          ))}
        </fieldset>
        <div className="actions">
          <button
            type="button"
            className="primary"
            disabled={busy || !templateKey}
            onClick={() =>
              void save({ template_key: templateKey }, "Template saved")
            }
          >
            Save template
          </button>
          <a
            className="ghost"
            href={`/owner/website/preview?business_id=${encodeURIComponent(businessId)}&location_id=${encodeURIComponent(locationId)}`}
          >
            Preview website
          </a>
        </div>
      </section>

      <section className="owner-card">
        <h2>Domain</h2>
        <p className="muted">BookAnything URL</p>
        <label>
          Subdomain
          <div className="owner-inline-field">
            <input
              value={subdomain}
              onChange={(e) => setSubdomain(e.target.value)}
              aria-label="BookAnything subdomain"
            />
            <span className="muted">.{launch.domain.site_root_domain}</span>
          </div>
        </label>
        {launch.domain.subdomain_hostname ? (
          <p>
            <code>{launch.domain.subdomain_hostname}</code>
          </p>
        ) : null}
        <label>
          Custom domain (optional)
          <input
            value={customDomain}
            onChange={(e) => setCustomDomain(e.target.value)}
            placeholder="www.ksnsalon.com"
          />
        </label>
        <p className="muted">Status: {launch.domain.status}</p>
        <button
          type="button"
          className="primary"
          disabled={busy}
          onClick={() =>
            void save(
              { subdomain, custom_domain: customDomain },
              "Domain saved",
            )
          }
        >
          Save domain
        </button>
      </section>

      <section className="owner-card">
        <h2>Google Business Profile URL</h2>
        <p className="muted">
          Optional manual Maps URL for your Launch checklist. OAuth connection is
          managed below.
        </p>
        <label>
          Google Business Profile URL
          <input
            value={googleUrl}
            onChange={(e) => setGoogleUrl(e.target.value)}
            placeholder="https://maps.google.com/…"
          />
        </label>
        <label>
          Google review URL
          <input
            value={reviewUrl}
            onChange={(e) => setReviewUrl(e.target.value)}
            placeholder="https://search.google.com/local/writereview?placeid=…"
          />
        </label>
        <p className="muted">
          Used only for delayed review requests. This is not the Maps or website URL
          above.
        </p>
        <label>
          Status
          <select
            value={googleStatus}
            onChange={(e) => setGoogleStatus(e.target.value)}
          >
            <option value="NOT_STARTED">Not started</option>
            <option value="IN_PROGRESS">In progress</option>
            <option value="READY">Ready</option>
            <option value="VERIFIED">Verified (owner-claimed)</option>
          </select>
        </label>
        <button
          type="button"
          className="primary"
          disabled={busy}
          onClick={() =>
            void save(
              {
                google_business_url: googleUrl,
                google_review_url: reviewUrl,
                google_business_status: googleStatus,
              },
              "Google setup saved",
            )
          }
        >
          Save Google setup
        </button>
      </section>

      <OwnerGoogleBusinessCard
        token={token}
        businessId={businessId}
        locationId={locationId}
        busy={busy}
        onBusy={onBusy}
        onMessage={onMessage}
        onError={onError}
      />

      <section className="owner-card">
        <h2>WhatsApp</h2>
        <p>
          {launch.whatsapp.configured ? "✓ Connected" : "Not configured yet"}
        </p>
        <p className="muted">Status: {launch.whatsapp.status}</p>
      </section>
      <OwnerWhatsAppCard
        token={token}
        businessId={businessId}
        busy={busy}
        onBusy={onBusy}
        onMessage={onMessage}
        onError={onError}
      />

      <section className="owner-card">
        <h2>Launch checklist</h2>
        <div className="owner-progress" aria-hidden>
          <span style={{ width: `${launch.progress}%` }} />
        </div>
        <ul className="owner-checklist">
          {CHECKLIST_LABELS.map((item) => (
            <li key={item.key}>
              {launch.checklist[item.key] ? "✓" : "○"} {item.label}
            </li>
          ))}
        </ul>
        <p className="owner-metric-value">{launch.ready ? "READY" : "IN PROGRESS"}</p>
        {launch.blocking_reasons[0] ? (
          <p className="muted">{launch.blocking_reasons[0]}</p>
        ) : null}
        <p className="muted">
          Website: {launch.website.status}
          {launch.launch_status === "LIVE" ? " · Live" : ""}
        </p>
        <div className="actions">
          {onBack ? (
            <button type="button" className="ghost" onClick={onBack}>
              Back
            </button>
          ) : null}
          <a
            className="ghost"
            href={`/owner/website/preview?business_id=${encodeURIComponent(businessId)}&location_id=${encodeURIComponent(locationId)}`}
          >
            Preview Website
          </a>
          {launch.ready && launch.launch_status !== "LIVE" ? (
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() => void publish()}
            >
              Publish website
            </button>
          ) : null}
          {launch.launch_status === "LIVE" &&
          (launch.profile?.public_url || launch.domain.subdomain_hostname) ? (
            <a
              className="primary"
              href={
                launch.profile?.public_url ||
                `https://${launch.domain.subdomain_hostname}`
              }
              target="_blank"
              rel="noreferrer"
            >
              View Website
            </a>
          ) : null}
          <a className="ghost" href="/owner/website">
            Manage Website
          </a>
          {showFinish ? (
            <button
              type="button"
              className="ghost"
              disabled={busy || !launch.ready}
              onClick={onFinish}
            >
              Continue to Dashboard
            </button>
          ) : null}
        </div>
      </section>
    </div>
  );
}
