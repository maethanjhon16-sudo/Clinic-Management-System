export const API: string = (import.meta.env.VITE_API_URL as string | undefined) ?? "";

export type Role = "admin" | "doctor" | "nurse" | "student";
export interface User { id: string; email: string; full_name: string; role: Role; student_id: string | null; is_active: boolean }
export interface Student { id: string; student_number: string; full_name: string; email: string; program: string | null; year_level: number | null; contact_number: string | null; is_active: boolean }
export interface Doctor { id: string; full_name: string; specialization: string | null; email: string | null; is_active: boolean }
export interface Appointment { id: string; student_id: string; doctor_id: string; scheduled_at: string; reason: string | null; status: "scheduled" | "completed" | "cancelled" }
export interface Medicine { id: string; name: string; unit: string | null; stock: number; reorder_level: number; expiry_date: string | null; low_stock: boolean; expired: boolean }
export interface FollowUp { target: string; status: string; attempts: number; last_error: string | null }
export interface Consultation {
  id: string; appointment_id: string; student_id: string; doctor_id: string; notes: string | null;
  needs_excuse: boolean; rest_days: number | null; completed_at: string;
  prescriptions: { id: string; medicine_id: string; quantity: number; instructions: string | null }[];
  events: FollowUp[]; integration_status: string;
}
export interface Dispensing { id: string; prescription_id: string; consultation_id: string | null; student_id: string | null; medicine_id: string; quantity: number; status: string; created_at: string }
export interface Slip {
  id: string; consultation_id: string; student_id: string; token: string; valid_from: string; valid_until: string;
  status: string; effective_status: string; issued_at: string; revoked_at: string | null; revoke_reason: string | null;
  student_notified: boolean; recipients: { id: string; instructor_name: string; instructor_email: string }[];
}
export interface Notice { id: string; recipient_email: string; type: string; subject: string; status: string; attempts: number; last_error: string | null; created_at: string }
export interface VerifyResult { status: string; is_valid: boolean; student_name: string | null; student_number: string | null; valid_from: string; valid_until: string; issued_at: string; message: string }

export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

let token: string | null = null;
try { token = localStorage.getItem("clinic_token"); } catch { /* storage unavailable */ }
let onUnauthorized: (() => void) | null = null;

export function setToken(value: string | null) {
  token = value;
  try {
    if (value) localStorage.setItem("clinic_token", value);
    else localStorage.removeItem("clinic_token");
  } catch { /* storage unavailable */ }
}
export function setUnauthorizedHandler(fn: (() => void) | null) { onUnauthorized = fn; }

async function request(path: string, init: RequestInit = {}, auth = true): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (auth && token) headers.set("Authorization", `Bearer ${token}`);
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "NETWORK", "Cannot reach the server. It may still be waking up, so please try again in a minute.");
  }
  if (!res.ok) {
    let body: { code?: string; message?: string; details?: unknown; detail?: string } | null = null;
    try { body = await res.json(); } catch { /* not JSON */ }
    if (res.status === 401 && auth && token && onUnauthorized) onUnauthorized();
    throw new ApiError(res.status, body?.code ?? "ERROR", body?.message ?? body?.detail ?? `Request failed (${res.status})`, body?.details);
  }
  return res;
}

export async function api<T>(path: string, init?: RequestInit, auth = true): Promise<T> {
  const res = await request(path, init, auth);
  return (await res.json()) as T;
}
export async function apiBlob(path: string): Promise<Blob> {
  const res = await request(path);
  return res.blob();
}
const send = <T,>(method: string, path: string, data?: unknown) =>
  api<T>(path, { method, body: data === undefined ? undefined : JSON.stringify(data) });
export const post = <T,>(path: string, data?: unknown) => send<T>("POST", path, data);
export const put = <T,>(path: string, data?: unknown) => send<T>("PUT", path, data);
export const patch = <T,>(path: string, data?: unknown) => send<T>("PATCH", path, data);
export const del = <T,>(path: string) => send<T>("DELETE", path);
