import { ReactNode, useEffect, useState } from "react";
import { ApiError } from "./api";

export function errMsg(e: unknown): string {
  if (e instanceof ApiError) {
    const d = e.details;
    if (Array.isArray(d) && d.length) {
      const lines = d
        .map((x: { field?: string; name?: string; issue?: string }) => [x.field || x.name, x.issue].filter(Boolean).join(": "))
        .filter(Boolean);
      if (lines.length) return `${e.message} (${lines.join("; ")})`;
    }
    return e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    fn()
      .then((d) => { if (alive) { setData(d); setError(""); } })
      .catch((e) => { if (alive) setError(errMsg(e)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, loading, reload: () => setTick((t) => t + 1) };
}

export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function run(fn: () => Promise<unknown>, okMessage = ""): Promise<boolean> {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
      setNotice(okMessage);
      return true;
    } catch (e) {
      setError(errMsg(e));
      return false;
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, notice, run };
}

export function Loading({ show }: { show: boolean }) {
  return show ? <p className="muted">Loading. The first request can take up to a minute while the system starts.</p> : null;
}
export function ErrorBox({ message }: { message: string }) {
  return message ? <div className="alert error">{message}</div> : null;
}
export function OkBox({ message }: { message: string }) {
  return message ? <div className="alert ok">{message}</div> : null;
}
export function Badge({ value }: { value: string }) {
  return <span className={`badge b-${value}`}>{value}</span>;
}
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <div><label>{label}</label>{children}</div>;
}

export const fmtDateTime = (iso: string) =>
  new Date(iso).toLocaleString("en-PH", { timeZone: "Asia/Manila", dateStyle: "medium", timeStyle: "short" });
export const fmtDate = (iso: string) =>
  new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("en-PH", { dateStyle: "medium" });
// A <input type="datetime-local"> value is read as Philippine time.
export const toManilaIso = (local: string) => (local.length === 16 ? `${local}:00+08:00` : local);

export function PageHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="page-head">
      <h1>{title}</h1>
      {subtitle && <p>{subtitle}</p>}
    </div>
  );
}
export function EmptyRow({ show, cols, text }: { show: boolean; cols: number; text: string }) {
  return show ? <tr><td colSpan={cols} className="empty">{text}</td></tr> : null;
}
export const roleLabel = (role: string) => (role === "admin" ? "Administrator" : role === "nurse" ? "Clinic nurse" : "Student");
export const todayManila = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Manila" });
export const fmtTime = (iso: string) =>
  new Date(iso).toLocaleTimeString("en-PH", { timeZone: "Asia/Manila", hour: "numeric", minute: "2-digit" });
