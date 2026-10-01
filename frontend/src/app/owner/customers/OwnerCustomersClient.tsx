"use client";

import { CustomerRetentionProfile } from "@/components/owner/CustomerRetentionProfile";
import {
  OwnerApiError,
  OwnerShell,
  useOwnerToken,
} from "@/components/owner/OwnerShell";
import { friendlyApiMessage } from "@/lib/api/client";
import {
  getCustomerRetentionSummary,
  getOwnerMe,
  getRetentionSettings,
  listBusinesses,
  listCustomers,
  updateRetentionSettings,
} from "@/lib/api/ownerApi";
import type {
  CustomerSummary,
  RetentionSegment,
  RetentionSettings,
  RetentionSummary,
} from "@/lib/api/types";
import { RETENTION_SEGMENT_LABELS } from "@/lib/customers/retentionLabels";
import { useCallback, useEffect, useState } from "react";

const SEGMENT_FILTERS: { value: "" | RetentionSegment; label: string }[] = [
  { value: "", label: "All" },
  { value: "NEW", label: RETENTION_SEGMENT_LABELS.NEW },
  { value: "RETURNING", label: RETENTION_SEGMENT_LABELS.RETURNING },
  { value: "DUE_FOR_RETURN", label: RETENTION_SEGMENT_LABELS.DUE_FOR_RETURN },
  { value: "INACTIVE", label: RETENTION_SEGMENT_LABELS.INACTIVE },
  { value: "NO_VISITS", label: RETENTION_SEGMENT_LABELS.NO_VISITS },
];

export function OwnerCustomersClient() {
  const token = useOwnerToken();
  const [businessId, setBusinessId] = useState("");
  const [businessName, setBusinessName] = useState("");
  const [isOwner, setIsOwner] = useState(false);
  const [segment, setSegment] = useState<"" | RetentionSegment>("");
  const [customers, setCustomers] = useState<CustomerSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [summary, setSummary] = useState<RetentionSummary | null>(null);
  const [settings, setSettings] = useState<RetentionSettings | null>(null);
  const [returnAfter, setReturnAfter] = useState("30");
  const [inactiveAfter, setInactiveAfter] = useState("90");
  const [delayHours, setDelayHours] = useState("24");
  const [automationEnabled, setAutomationEnabled] = useState(false);
  const [listError, setListError] = useState<unknown>(null);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [settingsMessage, setSettingsMessage] = useState("");
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [profileLoading, setProfileLoading] = useState(false);

  const loadCustomers = useCallback(async () => {
    if (!token) return;
    try {
      let biz = businessId;
      let name = businessName;
      if (!biz) {
        const list = await listBusinesses(token);
        biz = list.results?.[0]?.id || "";
        name = list.results?.[0]?.name || "";
        setBusinessId(biz);
        setBusinessName(name);
      }
      if (!biz) return;
      const me = await getOwnerMe(token);
      setIsOwner(me.membership?.role === "OWNER");
      const retention = await getRetentionSettings(biz, token);
      setSettings(retention);
      setReturnAfter(String(retention.return_after_days));
      setInactiveAfter(String(retention.inactive_after_days));
      setDelayHours(String(retention.due_message_delay_hours));
      setAutomationEnabled(Boolean(retention.enabled));
      const data = await listCustomers(biz, token, { segment });
      setCustomers(data.results || []);
      setListError(null);
    } catch (err) {
      setListError(err);
    }
  }, [token, businessId, businessName, segment]);

  useEffect(() => {
    void loadCustomers();
  }, [loadCustomers]);

  useEffect(() => {
    if (!token || !businessId || !selectedId) {
      setSummary(null);
      setProfileError(null);
      return;
    }
    const controller = new AbortController();
    setProfileLoading(true);
    setProfileError(null);
    void getCustomerRetentionSummary(
      businessId,
      selectedId,
      token,
      controller.signal,
    )
      .then((data) => {
        setSummary(data);
        setProfileLoading(false);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        setSummary(null);
        setProfileError(friendlyApiMessage(err));
        setProfileLoading(false);
      });
    return () => controller.abort();
  }, [token, businessId, selectedId]);

  async function saveSettings() {
    if (!token || !businessId || !isOwner) return;
    setSettingsBusy(true);
    setSettingsError(null);
    setSettingsMessage("");
    try {
      const next = await updateRetentionSettings(businessId, token, {
        return_after_days: Number(returnAfter),
        inactive_after_days: Number(inactiveAfter),
        due_message_delay_hours: Number(delayHours),
        enabled: automationEnabled,
      });
      setSettings(next);
      setReturnAfter(String(next.return_after_days));
      setInactiveAfter(String(next.inactive_after_days));
      setDelayHours(String(next.due_message_delay_hours));
      setAutomationEnabled(Boolean(next.enabled));
      setSettingsMessage("Retention thresholds saved.");
      await loadCustomers();
      if (selectedId) {
        const refreshed = await getCustomerRetentionSummary(
          businessId,
          selectedId,
          token,
        );
        setSummary(refreshed);
      }
    } catch (err) {
      setSettingsError(friendlyApiMessage(err));
    } finally {
      setSettingsBusy(false);
    }
  }

  const selected = customers.find((row) => row.id === selectedId) || null;

  return (
    <OwnerShell title="Customers" businessName={businessName}>
      {listError ? <OwnerApiError error={listError} /> : null}

      <section className="owner-card" aria-label="Retention settings">
        <h2>Retention thresholds</h2>
        <p className="muted">
          Configuration defaults for classifying visit history. These are not
          predictions.
        </p>
        <div className="owner-retention-settings">
          <label>
            Return after (days)
            <input
              type="number"
              min={1}
              value={returnAfter}
              disabled={!isOwner}
              onChange={(e) => setReturnAfter(e.target.value)}
            />
          </label>
          <label>
            Inactive after (days)
            <input
              type="number"
              min={1}
              value={inactiveAfter}
              disabled={!isOwner}
              onChange={(e) => setInactiveAfter(e.target.value)}
            />
          </label>
          <label>
            Due-for-return delay (hours)
            <input
              type="number"
              min={1}
              value={delayHours}
              disabled={!isOwner}
              onChange={(e) => setDelayHours(e.target.value)}
            />
          </label>
          <label>
            Retention automation
            <select
              value={automationEnabled ? "on" : "off"}
              disabled={!isOwner}
              onChange={(e) => setAutomationEnabled(e.target.value === "on")}
            >
              <option value="off">Off</option>
              <option value="on">On</option>
            </select>
          </label>
        </div>
        {isOwner ? (
          <button
            type="button"
            className="primary"
            disabled={settingsBusy}
            onClick={() => void saveSettings()}
          >
            {settingsBusy ? "Saving…" : "Save thresholds"}
          </button>
        ) : (
          <p className="muted">
            Only owners can edit thresholds
            {settings
              ? ` (return ${settings.return_after_days} / inactive ${settings.inactive_after_days}).`
              : "."}
          </p>
        )}
        {settingsError ? (
          <p className="state error" role="alert">
            {settingsError}
          </p>
        ) : null}
        {settingsMessage ? <p className="muted">{settingsMessage}</p> : null}
      </section>

      <section className="owner-card">
        <h2>Customers</h2>
        <label>
          Segment
          <select
            value={segment}
            onChange={(e) => {
              setSelectedId(null);
              setSegment((e.target.value || "") as "" | RetentionSegment);
            }}
          >
            {SEGMENT_FILTERS.map((option) => (
              <option key={option.label} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <p className="muted">
          Select a customer to view completed visit history.
        </p>
        {customers.length === 0 ? (
          <p className="muted">No customers yet.</p>
        ) : (
          <ul className="owner-simple-list">
            {customers.map((row) => (
              <li key={row.id}>
                <button
                  type="button"
                  className={
                    selectedId === row.id
                      ? "ghost owner-customer-select active"
                      : "ghost owner-customer-select"
                  }
                  onClick={() => setSelectedId(row.id)}
                >
                  <strong>{row.full_name}</strong>
                  <span className="muted">
                    {" "}
                    · {row.total_visits} visit
                    {row.total_visits === 1 ? "" : "s"}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {selectedId ? (
        <CustomerRetentionProfile
          summary={summary}
          loading={profileLoading}
          error={profileError}
          customerName={selected?.full_name}
        />
      ) : (
        <p className="muted">Choose a customer to open visit history.</p>
      )}
    </OwnerShell>
  );
}
