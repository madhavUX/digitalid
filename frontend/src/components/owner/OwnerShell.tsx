"use client";

import { ApiError, apiRequest, friendlyApiMessage } from "@/lib/api/client";
import {
  clearOwnerToken,
  getOwnerToken,
  setOwnerToken,
} from "@/lib/owner/auth";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useState,
} from "react";

const NAV = [
  { href: "/owner/dashboard", label: "Dashboard" },
  { href: "/owner/bookings", label: "Bookings" },
  { href: "/owner/calendar", label: "Calendar" },
  { href: "/owner/customers", label: "Customers" },
  { href: "/owner/services", label: "Services" },
  { href: "/owner/staff", label: "Staff" },
  { href: "/owner/quickcard", label: "QuickCard" },
  { href: "/owner/website", label: "Website" },
  { href: "/owner/booking-plans", label: "Regular Bookings" },
  { href: "/owner/onboarding", label: "Setup" },
  { href: "/owner/settings", label: "Settings" },
];

type Props = {
  children: ReactNode;
  title?: string;
  businessName?: string;
  locationName?: string;
  locations?: { id: string; name: string }[];
  locationId?: string;
  onLocationChange?: (id: string) => void;
};

export function OwnerShell({
  children,
  title,
  businessName,
  locationName,
  locations = [],
  locationId,
  onLocationChange,
}: Props) {
  const pathname = usePathname();
  const router = useRouter();
  const [token, setToken] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setToken(getOwnerToken());
    setReady(true);
  }, []);

  const login = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      setBusy(true);
      setError(null);
      try {
        const data = await apiRequest<{ access: string }>("/api/v1/auth/login/", {
          method: "POST",
          body: { email, password },
        });
        setOwnerToken(data.access);
        setToken(data.access);
      } catch (err) {
        setError(friendlyApiMessage(err));
      } finally {
        setBusy(false);
      }
    },
    [email, password],
  );

  if (!ready) {
    return (
      <main className="owner-shell">
        <p className="muted">Loading…</p>
      </main>
    );
  }

  if (!token) {
    return (
      <main className="owner-shell owner-login">
        <form className="owner-card" onSubmit={login}>
          <p className="eyebrow">BookAnything</p>
          <h1>Owner sign in</h1>
          <p className="muted">Manage your business, bookings, and QuickCard.</p>
          {error ? (
            <p className="state error" role="alert">
              {error}
            </p>
          ) : null}
          <label>
            Email
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="username"
            />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
            />
          </label>
          <button className="primary" type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </main>
    );
  }

  return (
    <div className="owner-app">
      <header className="owner-top">
        <div className="owner-top-brand">
          <Link href="/owner/dashboard" className="owner-logo">
            BookAnything
          </Link>
          {businessName ? <span className="owner-biz">{businessName}</span> : null}
          {locations.length > 1 && onLocationChange ? (
            <label className="owner-loc-select">
              <span className="sr-only">Location</span>
              <select
                value={locationId || ""}
                onChange={(e) => onLocationChange(e.target.value)}
              >
                {locations.map((loc) => (
                  <option key={loc.id} value={loc.id}>
                    {loc.name}
                  </option>
                ))}
              </select>
            </label>
          ) : locationName ? (
            <span className="muted">{locationName}</span>
          ) : null}
        </div>
        <button
          type="button"
          className="owner-menu-btn"
          aria-expanded={menuOpen}
          aria-controls="owner-nav"
          onClick={() => setMenuOpen((v) => !v)}
        >
          Menu
        </button>
        <button
          type="button"
          className="ghost owner-signout"
          onClick={() => {
            clearOwnerToken();
            setToken("");
            router.push("/owner/dashboard");
          }}
        >
          Sign out
        </button>
      </header>
      <div className="owner-layout">
        <nav
          id="owner-nav"
          className={`owner-nav ${menuOpen ? "open" : ""}`}
          aria-label="Owner"
        >
          <ul>
            {NAV.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={pathname?.startsWith(item.href) ? "active" : undefined}
                  onClick={() => setMenuOpen(false)}
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <main className="owner-main">
          {title ? <h1 className="owner-page-title">{title}</h1> : null}
          {children}
        </main>
      </div>
    </div>
  );
}

export function useOwnerToken() {
  const [token, setToken] = useState("");
  useEffect(() => {
    setToken(getOwnerToken());
  }, []);
  return token;
}

export function OwnerApiError({ error }: { error: unknown }) {
  if (error instanceof ApiError && error.status === 403) {
    return (
      <p className="state error" role="alert">
        You don’t have permission to manage this business.
      </p>
    );
  }
  return (
    <p className="state error" role="alert">
      {friendlyApiMessage(error)}
    </p>
  );
}
