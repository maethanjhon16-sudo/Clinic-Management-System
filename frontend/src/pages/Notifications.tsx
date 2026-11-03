import { useState } from "react";
import { api, Notice, post } from "../api";
import { useAuth } from "../auth";
import { Badge, EmptyRow, ErrorBox, fmtDateTime, Loading, OkBox, PageHeader, useAction, useLoad } from "../ui";

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
    if (await act.run(() => post(`/api/notifications/${n.id}/retry`), "The message was sent again.")) refresh();
  }
  async function retryAll() {
    if (await act.run(() => post(`/api/notifications/retry-failed`), "All failed messages were sent again.")) refresh();
  }

  return (
    <>
      <PageHeader title="Notifications" subtitle="Messages sent to students and instructors, and their delivery status." />
      <div className="stats">
        <div className="stat"><b>{summary.data?.sent ?? "-"}</b><span>Sent</span></div>
        <div className="stat"><b>{summary.data?.failed ?? "-"}</b><span>Failed</span></div>
        <div className="stat"><b>{summary.data?.pending ?? "-"}</b><span>Pending</span></div>
      </div>
      <div className="card">
        <div className="inline" style={{ marginBottom: 16 }}>
          <div className="field" style={{ minWidth: 200 }}>
            <label>Status</label>
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All messages</option><option value="sent">Sent</option><option value="failed">Failed</option><option value="pending">Pending</option>
            </select>
          </div>
          {isAdmin && <button onClick={retryAll} disabled={act.busy}>Retry all failed</button>}
        </div>
        <ErrorBox message={act.error} />
        <OkBox message={act.notice} />
        <Loading show={list.loading} />
        <ErrorBox message={list.error} />
        <div className="table-wrap">
          <table>
            <thead><tr><th>Created</th><th>Recipient</th><th>Subject</th><th>Status</th><th>Attempts</th><th></th></tr></thead>
            <tbody>
              {(list.data ?? []).map((n) => (
                <tr key={n.id}>
                  <td>{fmtDateTime(n.created_at)}</td><td>{n.recipient_email}</td><td>{n.subject}</td>
                  <td><Badge value={n.status} />{n.last_error && <div className="muted">{n.last_error}</div>}</td>
                  <td>{n.attempts}</td>
                  <td>{isAdmin && n.status !== "sent" && <button className="small" onClick={() => retryOne(n)} disabled={act.busy}>Retry</button>}</td>
                </tr>
              ))}
              <EmptyRow show={!list.loading && (list.data ?? []).length === 0} cols={6} text="No messages to show." />
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
