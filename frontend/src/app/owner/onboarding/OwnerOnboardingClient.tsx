"use client";

import { OwnerApiError, OwnerShell, useOwnerToken } from "@/components/owner/OwnerShell";
import { OwnerLaunchSetup } from "@/components/owner/OwnerLaunchSetup";
import { apiRequest } from "@/lib/api/client";
import { getBusinessSetup, listBusinesses, listLocations } from "@/lib/api/ownerApi";
import {
  createManagedQuickCard,
  getManagedQuickCard,
  publishManagedQuickCard,
  updateManagedQuickCard,
} from "@/lib/api/managedQuickCard";
import type { BusinessSetupStatus } from "@/lib/api/types";
import { authHeaders } from "@/lib/owner/auth";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

const STEPS = [
  { key: "business", label: "Business" },
  { key: "location", label: "Location" },
  { key: "services", label: "Services" },
  { key: "staff", label: "Staff" },
  { key: "availability", label: "Availability" },
  { key: "quickcard", label: "QuickCard" },
  { key: "publish", label: "Publish" },
  { key: "launch", label: "Launch" },
] as const;

type StepKey = (typeof STEPS)[number]["key"];

const WEEKDAYS = [
  { value: 0, label: "Monday" },
  { value: 1, label: "Tuesday" },
  { value: 2, label: "Wednesday" },
  { value: 3, label: "Thursday" },
  { value: 4, label: "Friday" },
  { value: 5, label: "Saturday" },
  { value: 6, label: "Sunday" },
];

type ServiceRow = {
  id: string;
  name: string;
  duration_minutes: number;
  price: string;
  currency: string;
  is_active: boolean;
  is_bookable_online: boolean;
};

type StaffRow = {
  id: string;
  display_name: string;
  title: string;
  is_active: boolean;
  is_bookable: boolean;
};

export function OwnerOnboardingClient() {
  const token = useOwnerToken();
  const router = useRouter();
  const [stepIndex, setStepIndex] = useState(0);
  const [businessId, setBusinessId] = useState("");
  const [locationId, setLocationId] = useState("");
  const [setup, setSetup] = useState<BusinessSetupStatus | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const [businessName, setBusinessName] = useState("");
  const [vertical, setVertical] = useState("SALON");
  const [locName, setLocName] = useState("");
  const [address1, setAddress1] = useState("");
  const [city, setCity] = useState("");
  const [stateName, setStateName] = useState("");
  const [country, setCountry] = useState("IN");
  const [timezone, setTimezone] = useState("Asia/Kolkata");
  const [phone, setPhone] = useState("");

  const [services, setServices] = useState<ServiceRow[]>([]);
  const [serviceForm, setServiceForm] = useState({
    name: "",
    duration_minutes: "30",
    price: "400",
    currency: "INR",
  });

  const [staff, setStaff] = useState<StaffRow[]>([]);
  const [staffForm, setStaffForm] = useState({ display_name: "", title: "" });
  const [staffServiceIds, setStaffServiceIds] = useState<Record<string, string[]>>({});

  const [availabilityStaffId, setAvailabilityStaffId] = useState("");
  const [dayHours, setDayHours] = useState(
    WEEKDAYS.map((d) => ({
      weekday: d.value,
      closed: d.value === 6,
      starts_at: "09:00",
      ends_at: d.value === 5 ? "19:00" : "18:00",
    })),
  );

  const [qc, setQc] = useState({
    slug: "",
    headline: "",
    description: "",
    phone: "",
    whatsapp: "",
    website_url: "",
    google_maps_url: "",
    instagram_url: "",
    facebook_url: "",
  });
  const [qcExists, setQcExists] = useState(false);

  const step = STEPS[stepIndex];

  const refreshSetup = useCallback(async () => {
    if (!token || !businessId) return;
    const status = await getBusinessSetup(businessId, token, locationId || null);
    setSetup(status);
    if (!locationId && status.location?.id) setLocationId(status.location.id);
  }, [token, businessId, locationId]);

  const bootstrap = useCallback(async () => {
    if (!token) return;
    setError(null);
    try {
      const businesses = await listBusinesses(token);
      if (businesses.results?.[0]) {
        const biz = businesses.results[0];
        setBusinessId(biz.id);
        setBusinessName(biz.name);
        setVertical(biz.vertical || "SALON");
        const locs = await listLocations(biz.id, token);
        if (locs.results?.[0]) {
          setLocationId(locs.results[0].id);
          setLocName(locs.results[0].name);
          setTimezone(locs.results[0].timezone || "Asia/Kolkata");
        }
      }
    } catch (err) {
      setError(err);
    }
  }, [token]);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    if (businessId) void refreshSetup().catch((err) => setError(err));
  }, [businessId, locationId, refreshSetup]);

  useEffect(() => {
    if (!token || !businessId || step.key !== "services") return;
    void apiRequest<{ results: ServiceRow[] }>(
      `/api/v1/businesses/${businessId}/services/`,
      { headers: authHeaders(token), query: { limit: 50 } },
    )
      .then((data) => setServices(data.results || []))
      .catch((err) => setError(err));
  }, [token, businessId, step.key, message]);

  useEffect(() => {
    if (!token || !businessId || (step.key !== "staff" && step.key !== "availability"))
      return;
    void apiRequest<{ results: StaffRow[] }>(
      `/api/v1/businesses/${businessId}/staff/`,
      {
        headers: authHeaders(token),
        query: { limit: 50, location_id: locationId || undefined },
      },
    )
      .then((data) => {
        setStaff(data.results || []);
        if (!availabilityStaffId && data.results?.[0]) {
          setAvailabilityStaffId(data.results[0].id);
        }
      })
      .catch((err) => setError(err));
  }, [token, businessId, locationId, step.key, message, availabilityStaffId]);

  useEffect(() => {
    if (
      !token ||
      !businessId ||
      !locationId ||
      (step.key !== "quickcard" && step.key !== "publish")
    )
      return;
    void getManagedQuickCard(businessId, locationId, token)
      .then((card) => {
        setQcExists(true);
        setQc({
          slug: card.slug,
          headline: card.headline,
          description: card.description,
          phone: card.phone,
          whatsapp: card.whatsapp,
          website_url: card.website_url,
          google_maps_url: card.google_maps_url,
          instagram_url: card.instagram_url,
          facebook_url: card.facebook_url,
        });
      })
      .catch(() => setQcExists(false));
  }, [token, businessId, locationId, step.key]);

  const progressLabel = useMemo(
    () => `Step ${stepIndex + 1} of ${STEPS.length}`,
    [stepIndex],
  );

  async function saveBusiness() {
    if (!token || !businessName.trim()) {
      setMessage("Business name is required.");
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      if (businessId) {
        await apiRequest(`/api/v1/businesses/${businessId}/`, {
          method: "PATCH",
          headers: authHeaders(token),
          body: { name: businessName.trim(), vertical },
        });
      } else {
        const created = await apiRequest<{ id: string; name: string }>(
          "/api/v1/businesses/",
          {
            method: "POST",
            headers: authHeaders(token),
            body: { name: businessName.trim(), vertical },
          },
        );
        setBusinessId(created.id);
      }
      setStepIndex(1);
      await refreshSetup();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function saveLocation() {
    if (!token || !businessId || !locName.trim()) {
      setMessage("Location name is required.");
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const body = {
        name: locName.trim(),
        address_line1: address1,
        city,
        state: stateName,
        country,
        timezone,
        phone,
      };
      if (locationId) {
        await apiRequest(`/api/v1/businesses/${businessId}/locations/${locationId}/`, {
          method: "PATCH",
          headers: authHeaders(token),
          body,
        });
      } else {
        const created = await apiRequest<{ id: string }>(
          `/api/v1/businesses/${businessId}/locations/`,
          { method: "POST", headers: authHeaders(token), body },
        );
        setLocationId(created.id);
      }
      setStepIndex(2);
      await refreshSetup();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function addService() {
    if (!token || !businessId || !locationId || !serviceForm.name.trim()) return;
    setBusy(true);
    try {
      const created = await apiRequest<{ id: string }>(
        `/api/v1/businesses/${businessId}/services/`,
        {
          method: "POST",
          headers: authHeaders(token),
          body: {
            name: serviceForm.name.trim(),
            duration_minutes: Number(serviceForm.duration_minutes),
            price: serviceForm.price,
            currency: serviceForm.currency,
            is_bookable_online: true,
            is_active: true,
          },
        },
      );
      await apiRequest(
        `/api/v1/businesses/${businessId}/services/${created.id}/service-locations/`,
        {
          method: "POST",
          headers: authHeaders(token),
          body: { location_id: locationId },
        },
      );
      setServiceForm({ name: "", duration_minutes: "30", price: "400", currency: "INR" });
      setMessage("Service added");
      await refreshSetup();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function addStaffMember() {
    if (!token || !businessId || !locationId || !staffForm.display_name.trim()) return;
    setBusy(true);
    try {
      const created = await apiRequest<{ id: string }>(
        `/api/v1/businesses/${businessId}/staff/`,
        {
          method: "POST",
          headers: authHeaders(token),
          body: {
            display_name: staffForm.display_name.trim(),
            title: staffForm.title,
            location_id: locationId,
            is_active: true,
            is_bookable: true,
          },
        },
      );
      const assignIds =
        (staffServiceIds._new || []).length > 0
          ? staffServiceIds._new
          : services.map((s) => s.id);
      for (const serviceId of assignIds) {
        await apiRequest(`/api/v1/businesses/${businessId}/staff/${created.id}/services/`, {
          method: "POST",
          headers: authHeaders(token),
          body: { service_id: serviceId },
        });
      }
      setStaffForm({ display_name: "", title: "" });
      setMessage("Staff added");
      await refreshSetup();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function saveAvailability() {
    if (!token || !businessId || !locationId || !availabilityStaffId) {
      setMessage("Select a staff member.");
      return;
    }
    setBusy(true);
    try {
      for (const day of dayHours) {
        if (day.closed) continue;
        await apiRequest(
          `/api/v1/businesses/${businessId}/staff/${availabilityStaffId}/availability/`,
          {
            method: "POST",
            headers: authHeaders(token),
            body: {
              location_id: locationId,
              weekday: day.weekday,
              starts_at: `${day.starts_at}:00`,
              ends_at: `${day.ends_at}:00`,
            },
          },
        );
      }
      setMessage("Availability saved");
      setStepIndex(5);
      await refreshSetup();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function saveQuickCard() {
    if (!token || !businessId || !locationId) return;
    setBusy(true);
    try {
      if (qcExists) {
        // eslint-disable-next-line @typescript-eslint/no-unused-vars -- slug immutable
        const { slug, ...patch } = qc;
        await updateManagedQuickCard(businessId, locationId, token, patch);
      } else {
        await createManagedQuickCard(businessId, locationId, token, {
          ...qc,
          slug: qc.slug || undefined,
        });
        setQcExists(true);
      }
      setMessage("QuickCard saved");
      setStepIndex(6);
      await refreshSetup();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function publishAndContinue() {
    if (!token || !businessId || !locationId) return;
    setBusy(true);
    try {
      await publishManagedQuickCard(businessId, locationId, token);
      await refreshSetup();
      setStepIndex(7);
      setMessage("QuickCard published — finish launch setup");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <OwnerShell title="Setup">
        <p />
      </OwnerShell>
    );
  }

  return (
    <OwnerShell title="Business setup" businessName={setup?.business.name}>
      {error ? <OwnerApiError error={error} /> : null}
      <p className="muted">{progressLabel}</p>
      <div className="owner-progress" aria-hidden>
        <span style={{ width: `${((stepIndex + 1) / STEPS.length) * 100}%` }} />
      </div>
      <ol className="owner-steps">
        {STEPS.map((item, index) => (
          <li key={item.key} className={index === stepIndex ? "current" : undefined}>
            <button
              type="button"
              className="ghost"
              disabled={index > stepIndex}
              onClick={() => setStepIndex(index)}
            >
              {index + 1}. {item.label}
            </button>
          </li>
        ))}
      </ol>
      {message ? (
        <p className="muted" aria-live="polite">
          {message}
        </p>
      ) : null}

      {step.key === "business" ? (
        <section className="owner-card">
          <h2>Business</h2>
          <label>
            Business name
            <input
              value={businessName}
              onChange={(e) => setBusinessName(e.target.value)}
              required
            />
          </label>
          <label>
            Type
            <select value={vertical} onChange={(e) => setVertical(e.target.value)}>
              <option value="SALON">Salon</option>
              <option value="SPA">Spa</option>
              <option value="BARBER">Barber</option>
              <option value="CLINIC">Clinic</option>
              <option value="DENTAL">Dental</option>
              <option value="GYM">Gym</option>
              <option value="RESTAURANT">Restaurant</option>
              <option value="OTHER">Other</option>
            </select>
          </label>
          <button type="button" className="primary" disabled={busy} onClick={() => void saveBusiness()}>
            Save & continue
          </button>
        </section>
      ) : null}

      {step.key === "location" ? (
        <section className="owner-card">
          <h2>Location</h2>
          <label>
            Location name
            <input value={locName} onChange={(e) => setLocName(e.target.value)} />
          </label>
          <label>
            Address
            <input value={address1} onChange={(e) => setAddress1(e.target.value)} />
          </label>
          <label>
            City
            <input value={city} onChange={(e) => setCity(e.target.value)} />
          </label>
          <label>
            State
            <input value={stateName} onChange={(e) => setStateName(e.target.value)} />
          </label>
          <label>
            Country
            <input value={country} onChange={(e) => setCountry(e.target.value)} />
          </label>
          <label>
            Timezone
            <input value={timezone} onChange={(e) => setTimezone(e.target.value)} />
          </label>
          <label>
            Phone
            <input value={phone} onChange={(e) => setPhone(e.target.value)} />
          </label>
          <div className="actions">
            <button type="button" className="ghost" onClick={() => setStepIndex(0)}>
              Back
            </button>
            <button type="button" className="primary" disabled={busy} onClick={() => void saveLocation()}>
              Save & continue
            </button>
          </div>
        </section>
      ) : null}

      {step.key === "services" ? (
        <section className="owner-card">
          <h2>Services</h2>
          <ul className="owner-simple-list">
            {services.map((svc) => (
              <li key={svc.id}>
                <strong>{svc.name}</strong> · {svc.duration_minutes} min · ₹{svc.price}
              </li>
            ))}
          </ul>
          <label>
            Service name
            <input
              value={serviceForm.name}
              onChange={(e) => setServiceForm((s) => ({ ...s, name: e.target.value }))}
            />
          </label>
          <label>
            Duration (minutes)
            <input
              value={serviceForm.duration_minutes}
              onChange={(e) =>
                setServiceForm((s) => ({ ...s, duration_minutes: e.target.value }))
              }
            />
          </label>
          <label>
            Price
            <input
              value={serviceForm.price}
              onChange={(e) => setServiceForm((s) => ({ ...s, price: e.target.value }))}
            />
          </label>
          <div className="actions">
            <button type="button" className="ghost" onClick={() => setStepIndex(1)}>
              Back
            </button>
            <button type="button" className="ghost" disabled={busy} onClick={() => void addService()}>
              + Add service
            </button>
            <button
              type="button"
              className="primary"
              disabled={services.length === 0}
              onClick={() => setStepIndex(3)}
            >
              Continue
            </button>
          </div>
        </section>
      ) : null}

      {step.key === "staff" ? (
        <section className="owner-card">
          <h2>Staff</h2>
          <ul className="owner-simple-list">
            {staff.map((member) => (
              <li key={member.id}>
                <strong>{member.display_name}</strong>
                {member.title ? ` · ${member.title}` : ""}
              </li>
            ))}
          </ul>
          <label>
            Staff name
            <input
              value={staffForm.display_name}
              onChange={(e) => setStaffForm((s) => ({ ...s, display_name: e.target.value }))}
            />
          </label>
          <label>
            Title
            <input
              value={staffForm.title}
              onChange={(e) => setStaffForm((s) => ({ ...s, title: e.target.value }))}
            />
          </label>
          <fieldset>
            <legend>Assign services</legend>
            {services.map((svc) => {
              const selected = (staffServiceIds._new || services.map((s) => s.id)).includes(
                svc.id,
              );
              return (
                <label key={svc.id} className="owner-check">
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={(e) => {
                      const current = new Set(staffServiceIds._new || services.map((s) => s.id));
                      if (e.target.checked) current.add(svc.id);
                      else current.delete(svc.id);
                      setStaffServiceIds({ _new: [...current] });
                    }}
                  />
                  {svc.name}
                </label>
              );
            })}
          </fieldset>
          <div className="actions">
            <button type="button" className="ghost" onClick={() => setStepIndex(2)}>
              Back
            </button>
            <button type="button" className="ghost" disabled={busy} onClick={() => void addStaffMember()}>
              + Add staff
            </button>
            <button
              type="button"
              className="primary"
              disabled={staff.length === 0}
              onClick={() => setStepIndex(4)}
            >
              Continue
            </button>
          </div>
        </section>
      ) : null}

      {step.key === "availability" ? (
        <section className="owner-card">
          <h2>Availability</h2>
          <label>
            Staff
            <select
              value={availabilityStaffId}
              onChange={(e) => setAvailabilityStaffId(e.target.value)}
            >
              {staff.map((member) => (
                <option key={member.id} value={member.id}>
                  {member.display_name}
                </option>
              ))}
            </select>
          </label>
          <ul className="owner-hours-edit">
            {dayHours.map((day, index) => (
              <li key={day.weekday}>
                <span>{WEEKDAYS[index].label}</span>
                <label className="owner-check">
                  <input
                    type="checkbox"
                    checked={!day.closed}
                    onChange={(e) =>
                      setDayHours((rows) =>
                        rows.map((row, i) =>
                          i === index ? { ...row, closed: !e.target.checked } : row,
                        ),
                      )
                    }
                  />
                  Open
                </label>
                {!day.closed ? (
                  <>
                    <input
                      type="time"
                      value={day.starts_at}
                      onChange={(e) =>
                        setDayHours((rows) =>
                          rows.map((row, i) =>
                            i === index ? { ...row, starts_at: e.target.value } : row,
                          ),
                        )
                      }
                    />
                    <input
                      type="time"
                      value={day.ends_at}
                      onChange={(e) =>
                        setDayHours((rows) =>
                          rows.map((row, i) =>
                            i === index ? { ...row, ends_at: e.target.value } : row,
                          ),
                        )
                      }
                    />
                  </>
                ) : (
                  <span className="muted">Closed</span>
                )}
              </li>
            ))}
          </ul>
          <div className="actions">
            <button type="button" className="ghost" onClick={() => setStepIndex(3)}>
              Back
            </button>
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() => void saveAvailability()}
            >
              Save & continue
            </button>
          </div>
        </section>
      ) : null}

      {step.key === "quickcard" ? (
        <section className="owner-card">
          <h2>QuickCard</h2>
          <p className="muted">
            Or manage full details on the{" "}
            <Link href="/owner/quickcard">QuickCard page</Link>.
          </p>
          {!qcExists ? (
            <label>
              Slug
              <input
                value={qc.slug}
                onChange={(e) => setQc((s) => ({ ...s, slug: e.target.value }))}
                placeholder="ksn-salon"
              />
            </label>
          ) : (
            <p>
              Slug: <code>{qc.slug}</code>
            </p>
          )}
          {(
            [
              ["headline", "Headline"],
              ["description", "Description"],
              ["phone", "Phone"],
              ["whatsapp", "WhatsApp"],
              ["website_url", "Website"],
              ["google_maps_url", "Google Maps"],
              ["instagram_url", "Instagram"],
              ["facebook_url", "Facebook"],
            ] as const
          ).map(([key, label]) => (
            <label key={key}>
              {label}
              <input
                value={qc[key]}
                onChange={(e) => setQc((s) => ({ ...s, [key]: e.target.value }))}
              />
            </label>
          ))}
          <div className="actions">
            <button type="button" className="ghost" onClick={() => setStepIndex(4)}>
              Back
            </button>
            <button type="button" className="primary" disabled={busy} onClick={() => void saveQuickCard()}>
              Save & continue
            </button>
          </div>
        </section>
      ) : null}

      {step.key === "publish" ? (
        <section className="owner-card">
          <h2>Publish</h2>
          <p>Your BookAnything page</p>
          <ul className="owner-checklist">
            {STEPS.slice(0, 6).map((item) => (
              <li key={item.key}>
                {setup?.steps[item.key as keyof BusinessSetupStatus["steps"]]
                  ? "✓"
                  : "○"}{" "}
                {item.label}
              </li>
            ))}
          </ul>
          {setup && !setup.ready && setup.blocking_reasons.length ? (
            <p className="state error" role="status">
              {setup.blocking_reasons[0]}
            </p>
          ) : (
            <p>You&apos;re ready to accept bookings.</p>
          )}
          <div className="actions">
            <button type="button" className="ghost" onClick={() => setStepIndex(5)}>
              Back
            </button>
            <button
              type="button"
              className="primary"
              disabled={busy || !setup?.steps.quickcard}
              onClick={() => void publishAndContinue()}
            >
              Publish & continue
            </button>
          </div>
        </section>
      ) : null}

      {step.key === "launch" && businessId && locationId ? (
        <OwnerLaunchSetup
          token={token}
          businessId={businessId}
          locationId={locationId}
          busy={busy}
          onBusy={setBusy}
          onMessage={setMessage}
          onError={setError}
          showFinish
          onBack={() => setStepIndex(6)}
          onFinish={() => router.push("/owner/dashboard")}
        />
      ) : null}
    </OwnerShell>
  );
}
