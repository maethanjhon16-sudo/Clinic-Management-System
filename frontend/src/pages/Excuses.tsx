import { useEffect, useState } from "react";
import { api, apiBlob, patch, post, Slip, Student } from "../api";
import InstructorPicker from "../InstructorPicker";
import { Badge, EmptyRow, ErrorBox, fmtDate, fmtDateTime, Loading, OkBox, PageHeader, useAction, useLoad } from "../ui";

function Qr({ id }: { id: string }) {
  const [url, setUrl] = useState("");
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let objectUrl = "";
    let alive = true;
    apiBlob(`/api/excuses/${id}/qr`)
      .then((blob) => { if (alive) { objectUrl = URL.createObjectURL(blob); setUrl(objectUrl); } })
      .catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [id]);
  if (failed) return <p className="muted">The QR code could not be loaded.</p>;
  return url ? <img className="qr" src={url} alt="QR code for this excuse slip" /> : <p className="muted">Loading QR code...</p>;
}

export default function Excuses() {
  const [selectedId, setSelectedId] = useState("");
  const [reason, setReason] = useState("");
  const slips = useLoad(() => api<Slip[]>("/api/excuses?limit=100"), []);
  const students = useLoad(() => api<Student[]>("/api/students?limit=200"), []);
  const act = useAction();

  const studentName = (id: string) => students.data?.find((s) => s.id === id)?.full_name ?? "Unknown student";
  const selected = slips.data?.find((s) => s.id === selectedId) ?? null;
  const link = selected ? `${window.location.origin}${window.location.pathname}#/verify/${selected.token}` : "";

  async function revoke() {
    if (!selected || !window.confirm("Revoke this excuse slip? Anyone who scans it will see that it was revoked.")) return;
    if (await act.run(() => patch<Slip>(`/api/excuses/${selected.id}/revoke`, { reason: reason || null }), "The slip was revoked.")) {
      setReason("");
      slips.reload();
    }
  }

  async function resend() {
    if (!selected) return;
    if (await act.run(() => post<Slip>(`/api/excuses/${selected.id}/notify-student`), "The student will be notified again shortly.")) slips.reload();
  }

  return (
    <>
      <PageHeader title="Excuse slips" subtitle="Slips are issued when a student is not fit to continue classes, at medicine pick-up or after a consultation." />
      <ErrorBox message={act.error} />
      <OkBox message={act.notice} />
      <div className="card">
        <Loading show={slips.loading} />
        <ErrorBox message={slips.error} />
        <div className="table-wrap">
          <table>
            <thead><tr><th>Student</th><th>Valid from</th><th>Valid until</th><th>Status</th><th>Student notified</th><th></th></tr></thead>
            <tbody>
              {(slips.data ?? []).map((s) => (
                <tr key={s.id}>
                  <td>{studentName(s.student_id)}</td><td>{fmtDate(s.valid_from)}</td><td>{fmtDate(s.valid_until)}</td>
                  <td><Badge value={s.effective_status} /></td>
                  <td>{s.student_notified ? "Yes" : "No"}</td>
                  <td><button className="small secondary" onClick={() => setSelectedId(s.id)}>View details</button></td>
                </tr>
              ))}
              <EmptyRow show={!slips.loading && (slips.data ?? []).length === 0} cols={6} text="No excuse slips have been issued yet." />
            </tbody>
          </table>
        </div>
      </div>
      {selected && (
        <div className="card">
          <h2>{studentName(selected.student_id)} <Badge value={selected.effective_status} /></h2>
          <p className="sub">Issued {fmtDateTime(selected.issued_at)}. Valid from {fmtDate(selected.valid_from)} to {fmtDate(selected.valid_until)}.</p>
          <div className="inline" style={{ alignItems: "flex-start", gap: 24 }}>
            <Qr id={selected.id} />
            <div style={{ flex: 1, minWidth: 260 }}>
              <p className="muted">Verification link: <a href={link} target="_blank" rel="noreferrer">{link}</a></p>
              {selected.status === "revoked" && <p>Revoked{selected.revoke_reason ? `: ${selected.revoke_reason}` : ""}</p>}
              <div className="actions" style={{ marginTop: 0 }}>
                <button className="secondary" onClick={resend} disabled={act.busy}>Notify student again</button>
              </div>
              {selected.status === "valid" && (
                <div className="inline" style={{ marginTop: 16 }}>
                  <div className="field" style={{ minWidth: 240 }}>
                    <label>Reason for revoking (optional)</label>
                    <input value={reason} onChange={(e) => setReason(e.target.value)} />
                  </div>
                  <button className="danger" onClick={revoke} disabled={act.busy}>Revoke slip</button>
                </div>
              )}
            </div>
          </div>
          <h3 className="section-title">Instructors</h3>
          <InstructorPicker slipId={selected.id} />
        </div>
      )}
    </>
  );
}
