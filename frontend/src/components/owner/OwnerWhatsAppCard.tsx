"use client";

import {
  connectWhatsApp,
  createWhatsAppTemplate,
  deleteWhatsAppTemplate,
  disconnectWhatsApp,
  getWhatsAppConnection,
  listWhatsAppTemplates,
  listWhatsAppInboundMessages,
  syncWhatsAppTemplates,
} from "@/lib/api/ownerApi";
import type {
  WhatsAppConnectionStatus,
  WhatsAppInboundMessage,
  WhatsAppTemplate,
} from "@/lib/api/types";
import { useCallback, useEffect, useState } from "react";

type Props = {
  token: string;
  businessId: string;
  busy?: boolean;
  onBusy?: (value: boolean) => void;
  onMessage?: (message: string) => void;
  onError?: (error: unknown) => void;
};

const PURPOSE_CATEGORY: Record<string, string> = {
  BOOKING_CONFIRMATION: "CONFIRMATION",
  BOOKING_CONFIRMED: "CONFIRMATION",
  BOOKING_RESCHEDULED: "CONFIRMATION",
  BOOKING_CANCELLED: "CONFIRMATION",
  REVIEW_REQUEST: "REVIEW_REQUEST",
  APPOINTMENT_REMINDER: "REMINDER",
};

const STATUS_LABEL: Record<string, string> = {
  CONNECTED: "Connected",
  DISCONNECTED: "Disconnected",
  REAUTH_REQUIRED: "Reauth required",
  ERROR: "Error",
};

export function OwnerWhatsAppCard({
  token,
  businessId,
  busy = false,
  onBusy,
  onMessage,
  onError,
}: Props) {
  const [status, setStatus] = useState<WhatsAppConnectionStatus | null>(null);
  const [templates, setTemplates] = useState<WhatsAppTemplate[]>([]);
  const [accessToken, setAccessToken] = useState("");
  const [phoneNumberId, setPhoneNumberId] = useState("");
  const [businessAccountId, setBusinessAccountId] = useState("");
  const [displayPhone, setDisplayPhone] = useState("");
  const [templateName, setTemplateName] = useState("");
  const [templateBody, setTemplateBody] = useState("");
  const [purpose, setPurpose] = useState("BOOKING_CONFIRMATION");
  const [inbound, setInbound] = useState<WhatsAppInboundMessage[]>([]);
  const [inboundCount, setInboundCount] = useState(0);
  const [inboundOffset, setInboundOffset] = useState(0);
  const [inboundPhone, setInboundPhone] = useState("");
  const [inboundStatus, setInboundStatus] = useState("");
  const [inboundState, setInboundState] = useState<"loading" | "ready" | "error">("loading");
  const inboundLimit = 10;

  const load = useCallback(async () => {
    if (!token || !businessId) return;
    try {
      const data = await getWhatsAppConnection(businessId, token);
      setStatus(data);
      if (data.connected) {
        const page = await listWhatsAppTemplates(businessId, token);
        setTemplates(page.results || []);
      } else {
        setTemplates([]);
      }
    } catch (err) {
      onError?.(err);
    }
  }, [token, businessId, onError]);

  const loadInbound = useCallback(async () => {
    if (!token || !businessId) return;
    setInboundState("loading");
    try {
      const page = await listWhatsAppInboundMessages(businessId, token, {
        limit: inboundLimit,
        offset: inboundOffset,
        phone: inboundPhone,
        processing_status: inboundStatus,
        message_type: "TEXT",
      });
      setInbound(page.results || []);
      setInboundCount(page.count || 0);
      setInboundState("ready");
    } catch (err) {
      setInboundState("error");
      onError?.(err);
    }
  }, [token, businessId, inboundOffset, inboundPhone, inboundStatus, onError]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void loadInbound();
  }, [loadInbound]);

  async function connect() {
    onBusy?.(true);
    try {
      const data = await connectWhatsApp(businessId, token, {
        access_token: accessToken,
        phone_number_id: phoneNumberId,
        business_account_id: businessAccountId,
        display_phone_number: displayPhone || undefined,
      });
      setAccessToken("");
      setStatus(data);
      onMessage?.("WhatsApp connected");
      await load();
    } catch (err) {
      onError?.(err);
    } finally {
      onBusy?.(false);
    }
  }

  async function disconnect() {
    onBusy?.(true);
    try {
      const data = await disconnectWhatsApp(businessId, token);
      setStatus(data);
      setTemplates([]);
      onMessage?.("WhatsApp disconnected");
    } catch (err) {
      onError?.(err);
    } finally {
      onBusy?.(false);
    }
  }

  async function addTemplate() {
    onBusy?.(true);
    try {
      await createWhatsAppTemplate(businessId, token, {
        name: templateName,
        language: "en",
        purpose,
        category: PURPOSE_CATEGORY[purpose] || "CUSTOM",
        status: "DRAFT",
        body: templateBody,
        variables: ["customer_name", "appointment_reference"],
      });
      setTemplateName("");
      setTemplateBody("");
      onMessage?.("Template saved");
      await load();
    } catch (err) {
      onError?.(err);
    } finally {
      onBusy?.(false);
    }
  }

  async function syncTemplates() {
    onBusy?.(true);
    try {
      await syncWhatsAppTemplates(businessId, token);
      onMessage?.("Templates synced");
      await load();
    } catch (err) {
      onError?.(err);
    } finally {
      onBusy?.(false);
    }
  }

  async function removeTemplate(id: string) {
    onBusy?.(true);
    try {
      await deleteWhatsAppTemplate(businessId, token, id);
      onMessage?.("Template removed");
      await load();
    } catch (err) {
      onError?.(err);
    } finally {
      onBusy?.(false);
    }
  }

  if (!status) {
    return <p className="muted">Loading WhatsApp…</p>;
  }

  const label = STATUS_LABEL[status.status] || status.status;

  return (
    <section className="owner-card" aria-label="WhatsApp Business">
      <h2>WhatsApp Business</h2>
      <p className="owner-metric-value">{label}</p>
      {status.verified_name ? <p>Name: {status.verified_name}</p> : null}
      {status.display_phone_number ? (
        <p>
          Phone: <code>{status.display_phone_number}</code>
        </p>
      ) : null}
      {status.message_counts ? (
        <p className="muted">
          Messages: {status.message_counts.QUEUED || 0} queued,{" "}
          {status.message_counts.SENT || 0} sent, {status.message_counts.FAILED || 0}{" "}
          failed
          {status.message_counts.DELIVERED
            ? `, ${status.message_counts.DELIVERED} delivered`
            : ""}
          {status.message_counts.READ ? `, ${status.message_counts.READ} read` : ""}
        </p>
      ) : null}
      <p>
        24-hour reminder:{" "}
        {status.reminder_24h?.status === "ENABLED" ? "Enabled" : "Not configured"}
        {status.reminder_24h ? ` · ${status.reminder_24h.upcoming_count} upcoming` : ""}
      </p>
      <p>
        1-hour reminder:{" "}
        {status.reminder_1h?.status === "ENABLED" ? "Enabled" : "Not configured"}
        {status.reminder_1h ? ` · ${status.reminder_1h.upcoming_count} upcoming` : ""}
      </p>
      <p>
        Delayed review request:{" "}
        {status.review_request?.status === "ENABLED" ? "Enabled" : "Not configured"}
        {status.review_request?.delay_hours != null
          ? ` · ${status.review_request.delay_hours}h delay`
          : ""}
      </p>
      <p className="muted">Inbound messages: {status.inbound_count || 0}</p>
      <section aria-label="Inbound Messages">
        <h3>Inbound Messages</h3>
        <label>
          Phone
          <input
            value={inboundPhone}
            onChange={(e) => {
              setInboundOffset(0);
              setInboundPhone(e.target.value);
            }}
          />
        </label>
        <label>
          Status
          <select
            value={inboundStatus}
            onChange={(e) => {
              setInboundOffset(0);
              setInboundStatus(e.target.value);
            }}
          >
            <option value="">Any</option>
            <option value="RECEIVED">Received</option>
            <option value="IGNORED">Ignored</option>
          </select>
        </label>
        {inboundState === "loading" ? <p className="muted">Loading messages…</p> : null}
        {inboundState === "error" ? (
          <p className="muted">Inbound messages could not be loaded.</p>
        ) : null}
        {inboundState === "ready" && inbound.length === 0 ? (
          <p className="muted">No inbound messages</p>
        ) : null}
        {inboundState === "ready" && inbound.length > 0 ? (
          <ul>
            {inbound.map((item) => (
              <li key={item.id}>
                <span>{item.customer_name || "Unknown WhatsApp Contact"}</span>
                <span>{item.text ? `"${item.text}"` : ""}</span>
                <span>{item.message_type}</span>
                <span>
                  {item.provider_timestamp
                    ? new Date(item.provider_timestamp).toLocaleString("en-GB", {
                        day: "numeric",
                        month: "short",
                        year: "numeric",
                        hour: "numeric",
                        minute: "2-digit",
                      })
                    : ""}
                </span>
                <span>{item.processing_status}</span>
              </li>
            ))}
          </ul>
        ) : null}
        <button
          type="button"
          className="ghost"
          disabled={inboundOffset === 0}
          onClick={() => setInboundOffset(Math.max(0, inboundOffset - inboundLimit))}
        >
          Previous
        </button>
        <button
          type="button"
          className="ghost"
          disabled={inboundOffset + inboundLimit >= inboundCount}
          onClick={() => setInboundOffset(inboundOffset + inboundLimit)}
        >
          Next
        </button>
      </section>
      {status.last_error_message ? (
        <p className="muted">{status.last_error_message}</p>
      ) : null}

      {status.status === "REAUTH_REQUIRED" || status.status === "DISCONNECTED" ? (
        <div className="owner-field">
          <label htmlFor="wa-token">Access token</label>
          <input
            id="wa-token"
            type="password"
            autoComplete="off"
            value={accessToken}
            onChange={(e) => setAccessToken(e.target.value)}
          />
          <label htmlFor="wa-phone-id">Phone number ID</label>
          <input
            id="wa-phone-id"
            value={phoneNumberId}
            onChange={(e) => setPhoneNumberId(e.target.value)}
          />
          <label htmlFor="wa-waba">Business account ID</label>
          <input
            id="wa-waba"
            value={businessAccountId}
            onChange={(e) => setBusinessAccountId(e.target.value)}
          />
          <label htmlFor="wa-display">Display phone</label>
          <input
            id="wa-display"
            value={displayPhone}
            placeholder="+919876543210"
            onChange={(e) => setDisplayPhone(e.target.value)}
          />
          <button
            type="button"
            className="primary"
            disabled={busy || !status.connect_available || !accessToken}
            onClick={() => void connect()}
          >
            {status.status === "REAUTH_REQUIRED" ? "Reconnect WhatsApp" : "Connect WhatsApp"}
          </button>
        </div>
      ) : null}

      {status.connected ? (
        <>
          <button
            type="button"
            className="ghost"
            disabled={busy}
            onClick={() => void disconnect()}
          >
            Disconnect
          </button>
          <button
            type="button"
            className="ghost"
            disabled={busy}
            onClick={() => void syncTemplates()}
          >
            Sync Templates
          </button>
          <h3>Templates</h3>
          <ul>
            {templates.map((item) => (
              <li key={item.id}>
                {item.name} · {item.purpose || item.category} · {item.language} · {item.status}
                {item.provider_status ? ` · Meta ${item.provider_status}` : ""}
                <button
                  type="button"
                  className="ghost"
                  disabled={busy}
                  onClick={() => void removeTemplate(item.id)}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
          <div className="owner-field">
            <label htmlFor="wa-template-name">Template name</label>
            <input
              id="wa-template-name"
              value={templateName}
              onChange={(e) => setTemplateName(e.target.value)}
            />
            <label htmlFor="wa-purpose">Purpose</label>
            <select
              id="wa-purpose"
              value={purpose}
              onChange={(e) => setPurpose(e.target.value)}
            >
              <option value="BOOKING_CONFIRMATION">Booking confirmation</option>
              <option value="BOOKING_CONFIRMED">Booking confirmed</option>
              <option value="BOOKING_RESCHEDULED">Booking rescheduled</option>
              <option value="BOOKING_CANCELLED">Booking cancelled</option>
              <option value="REVIEW_REQUEST">Review request</option>
              <option value="APPOINTMENT_REMINDER">Appointment reminder</option>
            </select>
            <label htmlFor="wa-template-body">Body</label>
            <input
              id="wa-template-body"
              value={templateBody}
              onChange={(e) => setTemplateBody(e.target.value)}
            />
            <button
              type="button"
              className="primary"
              disabled={busy || !templateName}
              onClick={() => void addTemplate()}
            >
              Add template
            </button>
          </div>
        </>
      ) : null}
    </section>
  );
}
