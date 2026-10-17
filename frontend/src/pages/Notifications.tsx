import { useState } from "react";
import { api, Notice, post } from "../api";
import { useAuth } from "../auth";
import { Badge, ErrorBox, Field, fmtDateTime, Loading, OkBox, useAction, useLoad } from "../ui";

interface Summary { sent: number; failed: number; pending: number }

export default function Notifications() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [status, setStatus] = useState("");
  const summary = useLoad(() => api<Summary>("/api/notifications/summary"), []);
  const list = useLoad(() => api<Notice[]>(`/api/notifications?limit=100${status ? `&status=${status}` : ""}`), [status]);
  const act = useAction();

  function refresh() { list.reload(); summary.reload(); }

  async function retryOne(n: Notice) {
    if (await act.run(() => post(`/api/notifications/${n.id}/retry`), "Retried.")) refresh();
  }
  async function retryAll() {
    if (await act.run(() => post(`/api/notifications/retry-failed`), "Retried all failed notifications.")) refresh();
  }

  return (
    <>
      <h2>Notifications</h2>
      <div className="grid" style={{ marginBottom: 16 }}>
        <div className="stat"><b>{summary.data?.sent ?? "-"}</b><span>Sent</span></div>
        <div className="stat"><b>{summary.data?.failed ?? "-"}</b><span>Failed</span></div>
        <div className="stat"><b>{summary.data?.pending ?? "-"}</b><span>Pending</span></div>
      </div>
      <ErrorBox message={act.error} />
      <OkBox message={act.notice} />
      <div className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          <Field label="Status">
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All</option><option value="sent">Sent</option><option value="failed">Failed</option><option value="pending">Pending</option>
            </select>
          </Field>
          {isAdmin && <button onClick={retryAll} disabled={act.busy}>Retry all failed</button>}
        </div>
        <Loading show={list.loading} />
        <ErrorBox message={list.error} />
        <div className="scroll">
          <table>
            <thead><tr><th>Created</th><th>To</th><th>Type</th><th>Subject</th><th>Status</th><th>Tries</th>{isAdmin && <th></th>}</tr></thead>
            <tbody>
              {(list.data ?? []).map((n) => (
                <tr key={n.id}>
                  <td>{fmtDateTime(n.created_at)}</td><td>{n.recipient_email}</td><td>{n.type}</td><td>{n.subject}</td>
                  <td><Badge value={n.status} />{n.last_error && <div className="muted">{n.last_error}</div>}</td>
                  <td>{n.attempts}</td>
                  {isAdmin && <td>{n.status !== "sent" && <button className="small" onClick={() => retryOne(n)} disabled={act.busy}>Retry</button>}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
