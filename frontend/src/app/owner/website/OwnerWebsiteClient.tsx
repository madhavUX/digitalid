"use client";

import { OwnerApiError, OwnerShell, useOwnerToken } from "@/components/owner/OwnerShell";
import {
  getWebsiteStatus,
  listBusinesses,
  listLocations,
  publishWebsite,
  unpublishWebsite,
  updateBusinessLaunchProfile,
} from "@/lib/api/ownerApi";
import type { WebsiteManagementStatus, WebsiteTemplateKey } from "@/lib/api/types";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

const TEMPLATES: { key: WebsiteTemplateKey; label: string }[] = [
  { key: "SALON_MODERN", label: "Salon Modern" },
  { key: "SALON_CLASSIC", label: "Salon Classic" },
  { key: "SALON_LUXURY", label: "Salon Luxury" },
];

function templateLabel(key: string | null) {
  return TEMPLATES.find((t) => t.key === key)?.label || key || "Not selected";
}

function statusLabel(status: WebsiteManagementStatus | null) {
  if (!status) return "—";
  if (status.domain_status === "FAILED") return "FAILED";
  if (status.domain_status === "PROVISIONING") return "PROVISIONING";
  if (status.website_status === "PUBLISHED" && status.launch_status === "LIVE") {
    return "LIVE";
  }
  return "NOT PUBLISHED";
}

export function OwnerWebsiteClient() {
  const token = useOwnerToken();
  const search = useSearchParams();
  const [businessId, setBusinessId] = useState(search.get("business_id") || "");
  const [locationId, setLocationId] = useState(search.get("location_id") || "");
  const [businessName, setBusinessName] = useState("");
  const [locations, setLocations] = useState<{ id: string; name: string }[]>([]);
  const [status, setStatus] = useState<WebsiteManagementStatus | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [showTemplates, setShowTemplates] = useState(false);
  const [templateKey, setTemplateKey] = useState("");

  const load = useCallback(async () => {
    if (!token) return;
    setError(null);
    try {
      let biz = businessId;
      if (!biz) {
        const list = await listBusinesses(token);
        biz = list.results?.[0]?.id || "";
        setBusinessId(biz);
        setBusinessName(list.results?.[0]?.name || "");
      }
      if (!biz) {
        setStatus(null);
        return;
      }
      const locs = await listLocations(biz, token);
      const locRows = (locs.results || []).map((l) => ({ id: l.id, name: l.name }));
      setLocations(locRows);
      const loc = locationId || locRows[0]?.id || "";
      if (!locationId && loc) setLocationId(loc);
      if (!loc) {
        setStatus(null);
        return;
      }
      const website = await getWebsiteStatus(biz, token, loc);
      setStatus(website);
      setTemplateKey(website.template_key || "");
    } catch (err) {
      setError(err);
    }
  }, [token, businessId, locationId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function copyUrl() {
    if (!status?.public_url) return;
    try {
      await navigator.clipboard.writeText(status.public_url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  async function onPublish() {
    if (!token || !businessId || !locationId) return;
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      const result = await publishWebsite(businessId, token, locationId);
      setStatus(result);
      setMessage("Website published");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function onUnpublish() {
    if (!token || !businessId || !locationId) return;
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      const result = await unpublishWebsite(businessId, token, locationId);
      setStatus(result);
      setMessage("Website unpublished");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function onSaveTemplate() {
    if (!token || !businessId || !locationId || !templateKey) return;
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      await updateBusinessLaunchProfile(
        businessId,
        token,
        { template_key: templateKey },
        locationId,
      );
      await load();
      setShowTemplates(false);
      setMessage("Template updated");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const isLive =
    status?.website_status === "PUBLISHED" && status?.launch_status === "LIVE";
  const previewHref = `/owner/website/preview?business_id=${encodeURIComponent(businessId)}&location_id=${encodeURIComponent(locationId)}`;

  if (!token) {
    return (
      <OwnerShell>
        <p />
      </OwnerShell>
    );
  }

  return (
    <OwnerShell
      title="Website"
      businessName={businessName}
      locations={locations}
      locationId={locationId}
      onLocationChange={(id) => setLocationId(id)}
    >
      {error ? <OwnerApiError error={error} /> : null}
      {message ? (
        <p className="muted" aria-live="polite">
          {message}
        </p>
      ) : null}

      {!status && !error ? <p className="muted">Loading website…</p> : null}

      {status ? (
        <section className="owner-card" aria-label="Website status">
          <h2>Website</h2>
          <p>
            Status: <span className="owner-metric-value">{statusLabel(status)}</span>
          </p>
          <p>Template: {templateLabel(status.template_key)}</p>
          {status.public_url ? (
            <p>
              Website URL: <code>{status.public_url}</code>
            </p>
          ) : null}
          {status.subdomain_hostname ? (
            <p>
              Subdomain: <code>{status.subdomain_hostname}</code>
            </p>
          ) : null}

          <div className="actions">
            {isLive && status.public_url ? (
              <a
                className="primary"
                href={status.public_url}
                target="_blank"
                rel="noreferrer"
              >
                Open Website
              </a>
            ) : null}
            {status.public_url ? (
              <button type="button" className="ghost" onClick={() => void copyUrl()}>
                {copied ? "Copied" : "Copy Website URL"}
              </button>
            ) : null}
            <Link className="ghost" href={previewHref}>
              Preview
            </Link>
            <button
              type="button"
              className="ghost"
              disabled={busy}
              onClick={() => setShowTemplates((v) => !v)}
            >
              Change Template
            </button>
            {isLive ? (
              <button
                type="button"
                className="ghost"
                disabled={busy}
                onClick={() => void onUnpublish()}
              >
                Unpublish
              </button>
            ) : (
              <button
                type="button"
                className="primary"
                disabled={busy}
                onClick={() => void onPublish()}
              >
                Publish Website
              </button>
            )}
          </div>

          {showTemplates ? (
            <fieldset className="owner-radio-group owner-template-grid">
              <legend>Choose template</legend>
              {TEMPLATES.map((option) => (
                <label
                  key={option.key}
                  className={`owner-template-card${templateKey === option.key ? " selected" : ""}`}
                >
                  <input
                    type="radio"
                    name="website-template"
                    value={option.key}
                    checked={templateKey === option.key}
                    onChange={() => setTemplateKey(option.key)}
                    aria-label={option.label}
                  />
                  <span>
                    <strong>{option.label}</strong>
                  </span>
                </label>
              ))}
              <div className="actions">
                <button
                  type="button"
                  className="primary"
                  disabled={busy || !templateKey}
                  onClick={() => void onSaveTemplate()}
                >
                  Save template
                </button>
              </div>
            </fieldset>
          ) : null}
        </section>
      ) : null}

      <p className="muted">
        <Link href="/owner/onboarding">Launch setup</Link>
        {" · "}
        <Link href="/owner/dashboard">Dashboard</Link>
      </p>
    </OwnerShell>
  );
}
