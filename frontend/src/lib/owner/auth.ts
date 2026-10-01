/** Shared owner auth helpers (Bearer access token in localStorage). */

export const OWNER_TOKEN_KEY = "ba_access_token";

export function getOwnerToken(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(OWNER_TOKEN_KEY) || "";
}

export function setOwnerToken(token: string) {
  window.localStorage.setItem(OWNER_TOKEN_KEY, token);
}

export function clearOwnerToken() {
  window.localStorage.removeItem(OWNER_TOKEN_KEY);
}

export function authHeaders(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}
