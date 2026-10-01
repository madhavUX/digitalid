"use client";

import {
  buildDateOptions,
  formatAddress,
  formatDateLabel,
  formatDuration,
  formatInTimezone,
  formatMoney,
  normalizePhoneInput,
} from "@/lib/booking/format";
import { createIdempotencyKey } from "@/lib/booking/idempotency";
import {
  createPublicAppointment,
  createPublicBookingPlan,
  getPublicAvailability,
} from "@/lib/api/publicBooking";
import { PaymentStep } from "@/components/booking/PaymentStep";
import { listPublicServices } from "@/lib/api/publicCatalog";
import { listPublicStaff } from "@/lib/api/publicStaff";
import type {
  PublicAppointment,
  PublicAppointmentCreateInput,
  PublicAvailabilityResponse,
  PublicLocation,
  PublicService,
  PublicSlot,
  PublicStaff,
} from "@/lib/api/types";
import { ApiError, friendlyApiMessage } from "@/lib/api/client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useTransition,
} from "react";

type Step =
  | "service"
  | "staff"
  | "datetime"
  | "booking_type"
  | "frequency"
  | "details"
  | "confirm"
  | "payment";

const STEPS: { id: Step; label: string }[] = [
  { id: "service", label: "Service" },
  { id: "staff", label: "Staff" },
  { id: "datetime", label: "Date & time" },
  { id: "booking_type", label: "Booking type" },
  { id: "frequency", label: "Frequency" },
  { id: "details", label: "Details" },
  { id: "confirm", label: "Confirm" },
  { id: "payment", label: "Payment" },
];

type BookingMode = "once" | "regular";
type PlanFrequency = "WEEK" | "MONTH";

const FREQUENCY_OPTIONS: {
  frequency: PlanFrequency;
  interval: number;
  label: string;
}[] = [
  { frequency: "WEEK", interval: 1, label: "Every week" },
  { frequency: "WEEK", interval: 2, label: "Every 2 weeks" },
  { frequency: "MONTH", interval: 1, label: "Every month" },
  { frequency: "MONTH", interval: 2, label: "Every 2 months" },
];

type Props = {
  location: PublicLocation;
  locationSlug: string;
  initialServices?: PublicService[];
  initialStaff?: PublicStaff[];
  prefillServiceId?: string | null;
  prefillStaffId?: string | null;
  attribution?: { source: string; ref: string } | null;
};

export function BookingFunnel({
  location,
  locationSlug,
  initialServices = [],
  initialStaff = [],
  prefillServiceId = null,
  prefillStaffId = null,
  attribution = null,
}: Props) {
  const router = useRouter();
  const [step, setStep] = useState<Step>("service");
  const [services, setServices] = useState<PublicService[]>(initialServices);
  const [staffList, setStaffList] = useState<PublicStaff[]>(initialStaff);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(
    initialServices.length === 0 || initialStaff.length === 0,
  );

  const [service, setService] = useState<PublicService | null>(null);
  const [staffId, setStaffId] = useState<string | null>(null); // null = Any staff
  const [date, setDate] = useState<string>("");
  const [slot, setSlot] = useState<PublicSlot | null>(null);
  const [availability, setAvailability] =
    useState<PublicAvailabilityResponse | null>(null);
  const [availabilityLoading, setAvailabilityLoading] = useState(false);
  const [availabilityError, setAvailabilityError] = useState<string | null>(null);

  const [customerName, setCustomerName] = useState("");
  const [customerPhone, setCustomerPhone] = useState("");
  const [customerEmail, setCustomerEmail] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const [bookingMode, setBookingMode] = useState<BookingMode>("once");
  const [planFrequency, setPlanFrequency] = useState<PlanFrequency>("MONTH");
  const [planInterval, setPlanInterval] = useState(1);
  const [planStaffPreference, setPlanStaffPreference] = useState<
    "SAME_STAFF" | "ANY_STAFF"
  >("ANY_STAFF");

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState(() => createIdempotencyKey());
  const [bookedAppointment, setBookedAppointment] = useState<PublicAppointment | null>(
    null,
  );
  const [, startTransition] = useTransition();
  const prefillApplied = useRef(false);

  const dateOptions = useMemo(
    () => buildDateOptions(location.timezone, 21),
    [location.timezone],
  );

  useEffect(() => {
    if (!date && dateOptions.length) setDate(dateOptions[0]);
  }, [date, dateOptions]);

  useEffect(() => {
    if (initialServices.length && initialStaff.length) return;
    let cancelled = false;
    (async () => {
      setCatalogLoading(true);
      setCatalogError(null);
      try {
        const [svc, stf] = await Promise.all([
          listPublicServices(locationSlug),
          listPublicStaff(locationSlug),
        ]);
        if (!cancelled) {
          setServices(svc);
          setStaffList(stf);
        }
      } catch (err) {
        if (!cancelled) setCatalogError(friendlyApiMessage(err));
      } finally {
        if (!cancelled) setCatalogLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [initialServices.length, initialStaff.length, locationSlug]);

  useEffect(() => {
    if (prefillApplied.current || !prefillServiceId || services.length === 0) return;
    const matched = services.find((s) => s.id === prefillServiceId);
    if (!matched) return;
    setService(matched);
    if (prefillStaffId === "any" || prefillStaffId === null) {
      setStaffId(null);
    } else if (prefillStaffId) {
      const staffOk = staffList.some(
        (member) =>
          member.id === prefillStaffId &&
          member.services.some((s) => s.id === matched.id),
      );
      setStaffId(staffOk ? prefillStaffId : null);
    }
    setStep("datetime");
    prefillApplied.current = true;
  }, [prefillServiceId, prefillStaffId, services, staffList]);

  const eligibleStaff = useMemo(() => {
    if (!service) return [];
    return staffList.filter((member) =>
      member.services.some((s) => s.id === service.id),
    );
  }, [service, staffList]);

  const loadAvailability = useCallback(async () => {
    if (!service || !date) return;
    setAvailabilityLoading(true);
    setAvailabilityError(null);
    try {
      const data = await getPublicAvailability({
        location_id: location.id,
        service_id: service.id,
        date,
        staff_id: staffId,
      });
      setAvailability(data);
      setSlot((current) => {
        if (!current) return null;
        const stillThere = data.slots.some((s) => s.start === current.start);
        return stillThere ? current : null;
      });
    } catch (err) {
      setAvailability(null);
      setAvailabilityError(friendlyApiMessage(err));
    } finally {
      setAvailabilityLoading(false);
    }
  }, [date, location.id, service, staffId]);

  useEffect(() => {
    if (step !== "datetime" && step !== "confirm") return;
    const handle = window.setTimeout(() => {
      void loadAvailability();
    }, 50);
    return () => window.clearTimeout(handle);
  }, [loadAvailability, step]);

  function goTo(next: Step) {
    setSubmitError(null);
    setFormError(null);
    setStep(next);
  }

  function selectService(next: PublicService) {
    setService(next);
    setStaffId(null);
    setSlot(null);
    setAvailability(null);
    goTo("staff");
  }

  function selectStaff(nextId: string | null) {
    setStaffId(nextId);
    setSlot(null);
    goTo("datetime");
  }

  function validateCustomer(): boolean {
    if (!customerName.trim()) {
      setFormError("Please enter your name.");
      return false;
    }
    const phone = normalizePhoneInput(customerPhone);
    if (phone.length < 10) {
      setFormError("Please enter a valid mobile number.");
      return false;
    }
    setFormError(null);
    return true;
  }

  const visibleSteps = useMemo(() => {
    let steps = STEPS;
    if (bookingMode === "once") {
      steps = steps.filter((s) => s.id !== "frequency");
    }
    if (!bookedAppointment?.payment_required && step !== "payment") {
      steps = steps.filter((s) => s.id !== "payment");
    }
    return steps;
  }, [bookingMode, bookedAppointment?.payment_required, step]);

  function goToSuccess(appointment: PublicAppointment) {
    startTransition(() => {
      const params = new URLSearchParams({
        ref: appointment.public_reference,
      });
      if (appointment.manage_token) {
        params.set("manage", appointment.manage_token);
      }
      router.push(
        `/book/${encodeURIComponent(locationSlug)}/success?${params.toString()}`,
      );
    });
  }

  async function submitBooking() {
    if (!service || !slot || submitting) return;
    if (!validateCustomer()) {
      goTo("details");
      return;
    }

    setSubmitting(true);
    setSubmitError(null);
    try {
      const customer = {
        name: customerName.trim(),
        phone: normalizePhoneInput(customerPhone),
        email: customerEmail.trim(),
      };
      const appointmentPayload: PublicAppointmentCreateInput = {
        location_id: location.id,
        service_id: service.id,
        staff_id: staffId,
        start: slot.start,
        customer,
      };
      if (
        (attribution?.source === "quickcard" || attribution?.source === "retention") &&
        attribution.ref
      ) {
        appointmentPayload.attribution_source = attribution.source;
        appointmentPayload.attribution_ref = attribution.ref;
      }
      const appointment =
        bookingMode === "regular"
          ? await createPublicBookingPlan(
              {
                location_id: location.id,
                service_id: service.id,
                staff_id: staffId,
                start: slot.start,
                customer,
                frequency: planFrequency,
                interval: planInterval,
                staff_preference: planStaffPreference,
              },
              idempotencyKey,
            )
          : await createPublicAppointment(appointmentPayload, idempotencyKey);
      setBookedAppointment(appointment);
      if (appointment.payment_required) {
        setStep("payment");
        return;
      }
      goToSuccess(appointment);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 409 || err.code === "SLOT_UNAVAILABLE")) {
        const message = friendlyApiMessage(err);
        setSlot(null);
        setIdempotencyKey(createIdempotencyKey());
        setStep("datetime");
        setFormError(null);
        setSubmitError(message);
        await loadAvailability();
      } else {
        setSubmitError(friendlyApiMessage(err));
      }
    } finally {
      setSubmitting(false);
    }
  }

  const selectedStaff = staffId
    ? eligibleStaff.find((s) => s.id === staffId) || null
    : null;

  const address = formatAddress(location.address);
  const stepIndex = visibleSteps.findIndex((s) => s.id === step);
  const frequencyLabel =
    FREQUENCY_OPTIONS.find(
      (o) => o.frequency === planFrequency && o.interval === planInterval,
    )?.label || "Every month";

  return (
    <div className="booking-shell">
      <header className="booking-hero">
        <div className="booking-hero-inner">
          <p className="eyebrow">Book an appointment</p>
          <div className="brand-row">
            {location.business.logo_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={location.business.logo_url}
                alt=""
                className="brand-logo"
              />
            ) : null}
            <div>
              <h1 className="brand-name">{location.business.name}</h1>
              <p className="location-line">
                {location.name}
                {address ? ` · ${address}` : ""}
              </p>
              {location.phone ? (
                <p className="location-meta">
                  <a href={`tel:${location.phone}`}>{location.phone}</a>
                </p>
              ) : null}
            </div>
          </div>
        </div>
      </header>

      <nav className="progress" aria-label="Booking progress">
        <ol>
          {visibleSteps.map((item, index) => {
            const done = index < stepIndex;
            const current = item.id === step;
            return (
              <li
                key={item.id}
                className={current ? "current" : done ? "done" : undefined}
                aria-current={current ? "step" : undefined}
              >
                <span className="step-num">{index + 1}</span>
                <span className="step-label">{item.label}</span>
              </li>
            );
          })}
        </ol>
      </nav>

      <div className="booking-layout">
        <main className="booking-main" aria-live="polite">
          {catalogLoading ? <p className="state">Loading services…</p> : null}
          {catalogError ? (
            <p className="state error" role="alert">
              {catalogError}
            </p>
          ) : null}

          {step === "service" && !catalogLoading ? (
            <section>
              <h2>Choose a service</h2>
              <p className="lede">Pick one service to continue.</p>
              <ul className="choice-list">
                {services.map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      className={`choice-card ${service?.id === item.id ? "selected" : ""}`}
                      onClick={() => selectService(item)}
                    >
                      <div className="choice-top">
                        <strong>{item.name}</strong>
                        <span>
                          {formatMoney(item.price, item.currency)}
                        </span>
                      </div>
                      {item.category ? (
                        <span className="chip">{item.category.name}</span>
                      ) : null}
                      {item.description ? (
                        <p className="muted">{item.description}</p>
                      ) : null}
                      <p className="muted">
                        {formatDuration(item.duration_minutes)}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
              {services.length === 0 ? (
                <p className="state">No bookable services at this location.</p>
              ) : null}
            </section>
          ) : null}

          {step === "staff" && service ? (
            <section>
              <h2>Who would you like?</h2>
              <p className="lede">Any available stylist, or someone specific.</p>
              <ul className="choice-list">
                <li>
                  <button
                    type="button"
                    className={`choice-card ${staffId === null ? "selected" : ""}`}
                    onClick={() => selectStaff(null)}
                  >
                    <strong>Any staff</strong>
                    <p className="muted">
                      We’ll assign the next available team member.
                    </p>
                  </button>
                </li>
                {eligibleStaff.map((member) => (
                  <li key={member.id}>
                    <button
                      type="button"
                      className={`choice-card staff-card ${staffId === member.id ? "selected" : ""}`}
                      onClick={() => selectStaff(member.id)}
                    >
                      {member.photo_url ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={member.photo_url}
                          alt=""
                          className="avatar"
                        />
                      ) : (
                        <span className="avatar placeholder" aria-hidden>
                          {member.display_name.slice(0, 1)}
                        </span>
                      )}
                      <div>
                        <strong>{member.display_name}</strong>
                        {member.title ? (
                          <p className="muted">{member.title}</p>
                        ) : null}
                        {member.bio ? (
                          <p className="muted">{member.bio}</p>
                        ) : null}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
              <div className="actions">
                <button type="button" className="ghost" onClick={() => goTo("service")}>
                  Back
                </button>
              </div>
            </section>
          ) : null}

          {step === "datetime" && service ? (
            <section>
              <h2>Pick a date & time</h2>
              <p className="lede">
                Times shown in {location.timezone.replace("_", " ")}.
              </p>
              <div className="date-strip" role="listbox" aria-label="Select date">
                {dateOptions.map((key) => (
                  <button
                    key={key}
                    type="button"
                    role="option"
                    aria-selected={date === key}
                    className={`date-chip ${date === key ? "selected" : ""}`}
                    onClick={() => {
                      setDate(key);
                      setSlot(null);
                    }}
                  >
                    {formatDateLabel(key, location.timezone)}
                  </button>
                ))}
              </div>

              {availabilityLoading ? (
                <p className="state">Checking availability…</p>
              ) : null}
              {availabilityError ? (
                <p className="state error" role="alert">
                  {availabilityError}
                </p>
              ) : null}
              {submitError ? (
                <p className="state error" role="alert">
                  {submitError}
                </p>
              ) : null}
              {!availabilityLoading &&
              !availabilityError &&
              availability &&
              availability.slots.length === 0 ? (
                <p className="state">
                  No times open on this date. Try another day.
                </p>
              ) : null}

              <ul className="slot-grid">
                {availability?.slots.map((item) => {
                  const label = formatInTimezone(item.start, location.timezone, {
                    hour: "numeric",
                    minute: "2-digit",
                  });
                  return (
                    <li key={item.start}>
                      <button
                        type="button"
                        className={`slot ${slot?.start === item.start ? "selected" : ""}`}
                        onClick={() => setSlot(item)}
                      >
                        {label}
                      </button>
                    </li>
                  );
                })}
              </ul>

              <div className="actions">
                <button type="button" className="ghost" onClick={() => goTo("staff")}>
                  Back
                </button>
                <button
                  type="button"
                  className="primary"
                  disabled={!slot}
                  onClick={() => {
                    setPlanStaffPreference(staffId ? "SAME_STAFF" : "ANY_STAFF");
                    goTo("booking_type");
                  }}
                >
                  Continue
                </button>
              </div>
            </section>
          ) : null}

          {step === "booking_type" ? (
            <section>
              <h2>Booking type</h2>
              <p className="lede">Book once, or set up a regular visit plan.</p>
              <ul className="choice-list">
                <li>
                  <button
                    type="button"
                    className={`choice-card ${bookingMode === "once" ? "selected" : ""}`}
                    onClick={() => setBookingMode("once")}
                  >
                    <strong>Book once</strong>
                    <span>A single appointment</span>
                  </button>
                </li>
                <li>
                  <button
                    type="button"
                    className={`choice-card ${bookingMode === "regular" ? "selected" : ""}`}
                    onClick={() => setBookingMode("regular")}
                    data-testid="book-regularly-option"
                  >
                    <strong>Book regularly</strong>
                    <span>Repeat this service — pay per visit</span>
                  </button>
                </li>
              </ul>
              <div className="actions">
                <button
                  type="button"
                  className="ghost"
                  onClick={() => goTo("datetime")}
                >
                  Back
                </button>
                <button
                  type="button"
                  className="primary"
                  onClick={() =>
                    goTo(bookingMode === "regular" ? "frequency" : "details")
                  }
                >
                  Continue
                </button>
              </div>
            </section>
          ) : null}

          {step === "frequency" ? (
            <section>
              <h2>How often?</h2>
              <p className="lede">Choose how often you want to return.</p>
              <ul className="choice-list">
                {FREQUENCY_OPTIONS.map((opt) => (
                  <li key={`${opt.frequency}-${opt.interval}`}>
                    <button
                      type="button"
                      className={`choice-card ${
                        planFrequency === opt.frequency &&
                        planInterval === opt.interval
                          ? "selected"
                          : ""
                      }`}
                      onClick={() => {
                        setPlanFrequency(opt.frequency);
                        setPlanInterval(opt.interval);
                      }}
                    >
                      {opt.label}
                    </button>
                  </li>
                ))}
              </ul>
              <fieldset className="choice-fieldset">
                <legend>Preferred staff</legend>
                <ul className="choice-list">
                  <li>
                    <button
                      type="button"
                      className={`choice-card ${planStaffPreference === "SAME_STAFF" ? "selected" : ""}`}
                      disabled={!staffId}
                      onClick={() => setPlanStaffPreference("SAME_STAFF")}
                    >
                      Same staff
                    </button>
                  </li>
                  <li>
                    <button
                      type="button"
                      className={`choice-card ${planStaffPreference === "ANY_STAFF" ? "selected" : ""}`}
                      onClick={() => setPlanStaffPreference("ANY_STAFF")}
                    >
                      Any staff
                    </button>
                  </li>
                </ul>
              </fieldset>
              {slot ? (
                <p className="muted">
                  Preferred time:{" "}
                  {formatInTimezone(slot.start, location.timezone, {
                    hour: "numeric",
                    minute: "2-digit",
                  })}
                </p>
              ) : null}
              <div className="actions">
                <button
                  type="button"
                  className="ghost"
                  onClick={() => goTo("booking_type")}
                >
                  Back
                </button>
                <button
                  type="button"
                  className="primary"
                  onClick={() => goTo("details")}
                >
                  Continue
                </button>
              </div>
            </section>
          ) : null}

          {step === "details" ? (
            <section>
              <h2>Your details</h2>
              <p className="lede">We’ll use these for your booking confirmation.</p>
              <form
                className="details-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (validateCustomer()) goTo("confirm");
                }}
              >
                <label>
                  Full name
                  <input
                    name="name"
                    autoComplete="name"
                    value={customerName}
                    onChange={(e) => setCustomerName(e.target.value)}
                    required
                  />
                </label>
                <label>
                  Mobile number
                  <input
                    name="phone"
                    autoComplete="tel"
                    inputMode="tel"
                    placeholder="9876543210"
                    value={customerPhone}
                    onChange={(e) => setCustomerPhone(e.target.value)}
                    required
                  />
                </label>
                <label>
                  Email <span className="optional">(optional)</span>
                  <input
                    name="email"
                    type="email"
                    autoComplete="email"
                    value={customerEmail}
                    onChange={(e) => setCustomerEmail(e.target.value)}
                  />
                </label>
                {formError ? (
                  <p className="state error" role="alert">
                    {formError}
                  </p>
                ) : null}
                <div className="actions">
                  <button
                    type="button"
                    className="ghost"
                    onClick={() =>
                      goTo(bookingMode === "regular" ? "frequency" : "booking_type")
                    }
                  >
                    Back
                  </button>
                  <button type="submit" className="primary">
                    Review booking
                  </button>
                </div>
              </form>
            </section>
          ) : null}

          {step === "confirm" && service && slot ? (
            <section>
              <h2>
                {bookingMode === "regular"
                  ? "Regular booking"
                  : "Confirm booking"}
              </h2>
              <p className="lede">
                {bookingMode === "regular"
                  ? "Each appointment is booked separately. You pay the business per visit."
                  : "Double-check the details, then book."}
              </p>
              <SummaryCard
                location={location}
                service={service}
                staffLabel={
                  bookingMode === "regular"
                    ? planStaffPreference === "SAME_STAFF"
                      ? selectedStaff?.display_name || "Same staff"
                      : "Any staff"
                    : selectedStaff?.display_name || "Any staff"
                }
                slot={slot}
              />
              {bookingMode === "regular" ? (
                <div className="summary-card" data-testid="regular-summary">
                  <p>
                    <strong>{frequencyLabel}</strong>
                  </p>
                  <p>
                    Preferred time:{" "}
                    {formatInTimezone(slot.start, location.timezone, {
                      hour: "numeric",
                      minute: "2-digit",
                    })}
                  </p>
                  <p>
                    Preferred staff:{" "}
                    {planStaffPreference === "SAME_STAFF"
                      ? "Same staff"
                      : "Any staff"}
                  </p>
                  <p>
                    First appointment:{" "}
                    {formatInTimezone(slot.start, location.timezone, {
                      day: "numeric",
                      month: "short",
                      hour: "numeric",
                      minute: "2-digit",
                    })}
                  </p>
                </div>
              ) : null}
              {submitError ? (
                <p className="state error" role="alert">
                  {submitError}
                </p>
              ) : null}
              <div className="actions">
                <button
                  type="button"
                  className="ghost"
                  onClick={() => goTo("details")}
                  disabled={submitting}
                >
                  Back
                </button>
                <button
                  type="button"
                  className="primary"
                  onClick={() => void submitBooking()}
                  disabled={submitting}
                  aria-busy={submitting}
                >
                  {submitting
                    ? "Booking…"
                    : bookingMode === "regular"
                      ? "Start regular booking"
                      : "Confirm booking"}
                </button>
              </div>
            </section>
          ) : null}

          {step === "payment" && bookedAppointment ? (
            <PaymentStep
              appointment={bookedAppointment}
              onPaid={() => goToSuccess(bookedAppointment)}
            />
          ) : null}
        </main>

        <aside className="booking-summary" aria-label="Booking summary">
          <h2>Summary</h2>
          <dl>
            <div>
              <dt>Service</dt>
              <dd>{service?.name || "—"}</dd>
            </div>
            <div>
              <dt>Staff</dt>
              <dd>
                {service
                  ? selectedStaff?.display_name || "Any staff"
                  : "—"}
              </dd>
            </div>
            <div>
              <dt>When</dt>
              <dd>
                {slot
                  ? `${formatDateLabel(date, location.timezone)} · ${formatInTimezone(slot.start, location.timezone, { hour: "numeric", minute: "2-digit" })}`
                  : date
                    ? formatDateLabel(date, location.timezone)
                    : "—"}
              </dd>
            </div>
            <div>
              <dt>Price</dt>
              <dd>
                {service
                  ? formatMoney(service.price, service.currency)
                  : "—"}
              </dd>
            </div>
          </dl>
        </aside>
      </div>
    </div>
  );
}

function SummaryCard({
  location,
  service,
  staffLabel,
  slot,
}: {
  location: PublicLocation;
  service: PublicService;
  staffLabel: string;
  slot: PublicSlot;
}) {
  return (
    <div className="summary-card">
      <p>
        <strong>{location.business.name}</strong>
        <br />
        {location.name}
      </p>
      <p>
        {service.name} · {formatDuration(service.duration_minutes)}
      </p>
      <p>{staffLabel}</p>
      <p>
        {formatInTimezone(slot.start, location.timezone, {
          weekday: "long",
          day: "numeric",
          month: "long",
          hour: "numeric",
          minute: "2-digit",
        })}
      </p>
      <p className="price">
        {formatMoney(service.price, service.currency)}
      </p>
    </div>
  );
}

export function BookingSuccessView({
  locationSlug,
  appointment,
  manageToken,
}: {
  locationSlug: string;
  appointment: PublicAppointment;
  manageToken?: string | null;
}) {
  return (
    <div className="booking-shell success-shell">
      <div className="success-card">
        <p className="eyebrow">You’re booked</p>
        <h1>Appointment confirmed</h1>
        <p className="lede">
          Reference <strong>{appointment.public_reference}</strong>
        </p>
        <dl className="success-dl">
          <div>
            <dt>Location</dt>
            <dd>{appointment.location}</dd>
          </div>
          <div>
            <dt>Service</dt>
            <dd>{appointment.service}</dd>
          </div>
          <div>
            <dt>Staff</dt>
            <dd>{appointment.staff}</dd>
          </div>
          <div>
            <dt>When</dt>
            <dd>
              {new Intl.DateTimeFormat("en-IN", {
                weekday: "long",
                day: "numeric",
                month: "long",
                hour: "numeric",
                minute: "2-digit",
              }).format(new Date(appointment.start))}
            </dd>
          </div>
          <div>
            <dt>Total</dt>
            <dd>{formatMoney(appointment.total, appointment.currency)}</dd>
          </div>
        </dl>
        <div className="actions">
          {manageToken ? (
            <Link
              className="primary"
              href={`/book/manage/${encodeURIComponent(manageToken)}`}
            >
              Manage your booking
            </Link>
          ) : null}
          <Link
            className={manageToken ? "ghost" : "primary"}
            href={`/book/${encodeURIComponent(locationSlug)}`}
          >
            Book another
          </Link>
        </div>
      </div>
    </div>
  );
}
