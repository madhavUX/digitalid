"use client";

import {
  disconnectGoogleBusiness,
  getGoogleBusinessAccounts,
  getGoogleBusinessLocations,
  getGoogleBusinessStatus,
  selectGoogleBusinessAccount,
  selectGoogleBusinessLocation,
  startGoogleBusinessConnect,
  syncGoogleBookingUrl,
} from "@/lib/api/ownerApi";
import type {
  GoogleBusinessAccountOption,
  GoogleBusinessLocationOption,
  GoogleBusinessStatus,
} from "@/lib/api/types";
import { useCallback, useEffect, useRef, useState } from "react";

type Props = {
  token: string;
  businessId: string;
  locationId: string;
  locationName?: string;
  busy?: boolean;
  onBusy?: (value: boolean) => void;
  onMessage?: (message: string) => void;
  onError?: (error: unknown) => void;
};

export function OwnerGoogleBusinessCard({
  token,
  businessId,
  locationId,
  locationName,
  busy = false,
  onBusy,
  onMessage,
  onError,
}: Props) {
  const [status, setStatus] = useState<GoogleBusinessStatus | null>(null);
  const [accounts, setAccounts] = useState<GoogleBusinessAccountOption[]>([]);
  const [locations, setLocations] = useState<GoogleBusinessLocationOption[]>([]);
  const [selectedAccount, setSelectedAccount] = useState("");
  const [selectedLocation, setSelectedLocation] = useState("");
  const [loadingSelection, setLoadingSelection] = useState(false);
  const selectionLoadedFor = useRef<string | null>(null);

  const loadStatus = useCallback(async () => {
    if (!token || !businessId || !locationId) return null;
    const data = await getGoogleBusinessStatus(businessId, locationId, token);
    setStatus(data);
    return data;
  }, [token, businessId, locationId]);

  const loadSelectionOptions = useCallback(
    async (current: GoogleBusinessStatus) => {
      const needsSelection =
        Boolean(current.selection_required) ||
        current.status === "LOCATION_SELECTION_REQUIRED" ||
        (Boolean(current.connected) && !current.location_selected);
      if (!needsSelection) return;

      const key = `${businessId}:${locationId}:${current.status}:${current.google_business_account?.name || ""}`;
      if (selectionLoadedFor.current === key) return;
      selectionLoadedFor.current = key;

      setLoadingSelection(true);
      try {
        const accountPayload = await getGoogleBusinessAccounts(
          businessId,
          locationId,
          token,
        );
        if (accountPayload.connection) setStatus(accountPayload.connection);
        setAccounts(accountPayload.accounts || []);
        const accountName =
          accountPayload.selected_account_name ||
          (accountPayload.accounts.length === 1
            ? accountPayload.accounts[0].name
            : "");
        setSelectedAccount(accountName);

        if (accountPayload.account_selection_required && !accountName) {
          setLocations([]);
          return;
        }

        if (!accountName) {
          setLocations([]);
          return;
        }

        const locationPayload = await getGoogleBusinessLocations(
          businessId,
          locationId,
          token,
          accountName,
        );
        if (locationPayload.connection) setStatus(locationPayload.connection);
        setLocations(locationPayload.locations || []);
        setSelectedLocation(
          locationPayload.selected_location_id ||
            (locationPayload.locations.length === 1
              ? locationPayload.locations[0].id
              : ""),
        );
      } catch (err) {
        selectionLoadedFor.current = null;
        onError?.(err);
      } finally {
        setLoadingSelection(false);
      }
    },
    [businessId, locationId, token, onError],
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await loadStatus();
        if (!cancelled && data) await loadSelectionOptions(data);
      } catch (err) {
        if (!cancelled) onError?.(err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadStatus, loadSelectionOptions, onError]);

  async function connect() {
    onBusy?.(true);
    try {
      const result = await startGoogleBusinessConnect(businessId, locationId, token);
      if (result.authorization_url) {
        window.location.href = result.authorization_url;
        return;
      }
      setStatus(result);
      selectionLoadedFor.current = null;
      onMessage?.(
        result.location_selected
          ? "Google connected"
          : "Google connected — select your Business Profile location",
      );
      await loadSelectionOptions(result);
    } catch (err) {
      onError?.(err);
    } finally {
      onBusy?.(false);
    }
  }

  async function chooseAccount() {
    if (!selectedAccount) return;
    onBusy?.(true);
    try {
      const result = await selectGoogleBusinessAccount(
        businessId,
        locationId,
        token,
        selectedAccount,
      );
      setStatus(result.connection);
      selectionLoadedFor.current = null;
      onMessage?.("Google Business account selected");
      await loadSelectionOptions(result.connection);
    } catch (err) {
      onError?.(err);
    } finally {
      onBusy?.(false);
    }
  }

  async function chooseLocation() {
    if (!selectedLocation) return;
    onBusy?.(true);
    try {
      const result = await selectGoogleBusinessLocation(
        businessId,
        locationId,
        token,
        {
          google_location_id: selectedLocation,
          google_account_name: selectedAccount || undefined,
        },
      );
      setStatus(result.connection);
      setLocations([]);
      onMessage?.("Google Business Profile location mapped");
    } catch (err) {
      onError?.(err);
    } finally {
      onBusy?.(false);
    }
  }

  async function disconnect() {
    onBusy?.(true);
    try {
      const result = await disconnectGoogleBusiness(businessId, locationId, token);
      setStatus(result);
      setAccounts([]);
      setLocations([]);
      setSelectedAccount("");
      setSelectedLocation("");
      onMessage?.("Google disconnected");
    } catch (err) {
      onError?.(err);
    } finally {
      onBusy?.(false);
    }
  }

  async function sync() {
    onBusy?.(true);
    try {
      const result = await syncGoogleBookingUrl(businessId, locationId, token);
      if (result.connection) setStatus(result.connection);
      onMessage?.(result.message || (result.success ? "Synced" : "Sync failed"));
    } catch (err) {
      onError?.(err);
    } finally {
      onBusy?.(false);
    }
  }

  if (!status) {
    return <p className="muted">Loading Google Business…</p>;
  }

  const reauth = status.status === "REAUTH_REQUIRED";
  const connected =
    status.connected ||
    status.status === "LOCATION_SELECTION_REQUIRED" ||
    status.status === "CONNECTED";
  const needsAccount =
    connected &&
    !status.location_selected &&
    accounts.length > 1 &&
    !status.google_business_account?.name;
  const needsLocation =
    connected &&
    !status.location_selected &&
    Boolean(selectedAccount || status.google_business_account?.name);

  return (
    <section className="owner-card" aria-label="Google Business">
      <h2>Google Business</h2>
      {locationName ? (
        <p className="muted">
          BookAnything location: <strong>{locationName}</strong>
        </p>
      ) : null}

      {reauth ? (
        <>
          <p className="owner-metric-value">Authorization expired</p>
          <p className="muted">Reconnect your Google account to continue.</p>
          <button
            type="button"
            className="primary"
            disabled={busy}
            onClick={() => void connect()}
          >
            Reconnect Google
          </button>
        </>
      ) : connected ? (
        <>
          <p>✓ Connected</p>
          {status.google_account?.email ? (
            <p>
              Google account: <code>{status.google_account.email}</code>
            </p>
          ) : null}

          {status.location_selected ? (
            <>
              <p>
                Mapped profile:{" "}
                <strong>
                  {status.google_location?.display_name ||
                    status.google_location_display_name ||
                    status.google_location_id}
                </strong>
              </p>
              {status.booking_url ? (
                <p className="muted">
                  Booking URL: <code>{status.booking_url}</code>
                </p>
              ) : null}
              {status.synced ? (
                <p>✓ Booking URL synced</p>
              ) : (
                <p className="muted">
                  Last sync: {status.last_sync_status || "NEVER"}
                  {status.last_synced_at ? ` · ${status.last_synced_at}` : ""}
                </p>
              )}
              <div className="actions">
                <button
                  type="button"
                  className="primary"
                  disabled={busy || !status.website_sync_available}
                  onClick={() => void sync()}
                >
                  Sync Website &amp; Booking URL
                </button>
                <button
                  type="button"
                  className="ghost"
                  disabled={busy}
                  onClick={() => void disconnect()}
                >
                  Disconnect
                </button>
              </div>
              {!status.website_sync_available ? (
                <p className="muted">
                  {status.sync_block_reason === "WEBSITE_NOT_PUBLISHED"
                    ? "Publish your website before syncing."
                    : "Sync is not available yet."}
                </p>
              ) : null}
            </>
          ) : (
            <>
              <p className="muted">
                Next step: select/confirm your Google Business Profile location.
              </p>
              {loadingSelection ? (
                <p className="muted">Loading Google profiles…</p>
              ) : null}

              {needsAccount || accounts.length > 1 ? (
                <div className="owner-field">
                  <label htmlFor="google-account">Google Business account</label>
                  <select
                    id="google-account"
                    value={selectedAccount}
                    disabled={busy}
                    onChange={(e) => setSelectedAccount(e.target.value)}
                  >
                    <option value="">Select account…</option>
                    {accounts.map((account) => (
                      <option key={account.name} value={account.name}>
                        {account.display_name}
                        {account.account_type ? ` (${account.account_type})` : ""}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="primary"
                    disabled={busy || !selectedAccount}
                    onClick={() => void chooseAccount()}
                  >
                    Use this account
                  </button>
                </div>
              ) : null}

              {needsLocation && locations.length > 0 ? (
                <div className="owner-field">
                  <label htmlFor="google-location">Google Business location</label>
                  <select
                    id="google-location"
                    value={selectedLocation}
                    disabled={busy}
                    onChange={(e) => setSelectedLocation(e.target.value)}
                  >
                    <option value="">Select location…</option>
                    {locations.map((loc) => (
                      <option key={loc.id} value={loc.id}>
                        {loc.title}
                        {loc.address ? ` — ${loc.address}` : ""}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="primary"
                    disabled={busy || !selectedLocation}
                    onClick={() => void chooseLocation()}
                  >
                    Map this location
                  </button>
                </div>
              ) : null}

              {!loadingSelection && accounts.length === 0 ? (
                <p className="muted">No Google Business accounts were returned.</p>
              ) : null}

              <div className="actions">
                <button
                  type="button"
                  className="ghost"
                  disabled={busy}
                  onClick={() => void disconnect()}
                >
                  Disconnect
                </button>
              </div>
            </>
          )}
        </>
      ) : (
        <>
          <p className="owner-metric-value">Not connected</p>
          <p className="muted">Connect your Google Business Profile</p>
          <button
            type="button"
            className="primary"
            disabled={busy || !status.oauth_available}
            onClick={() => void connect()}
          >
            Connect Google
          </button>
          {!status.oauth_available ? (
            <p className="muted">
              Google connection is not configured on this environment.
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
