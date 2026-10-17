import { FormEvent, useEffect, useState } from "react";
import { api, apiBlob, patch, post, Slip, Student } from "../api";
import { Badge, ErrorBox, Field, fmtDate, fmtDateTime, Loading, OkBox, useAction, useLoad } from "../ui";

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
  if (failed) return <p className="muted">Could not load the QR code.</p>;
  return url ? <img className="qr" src={url} alt="QR code for this excuse slip" /> : <p className="muted">Loading QR code...</p>;
}

export default function Excuses() {
  const [selectedId, setSelectedId] = useState("");
  const [rec, setRec] = useState({ instructor_name: "", instructor_email: "" });
  const [reason, setReason] = useState("");
  const slips = useLoad(() => api<Slip[]>("/api/excuses?limit=100"), []);
  const students = useLoad(() => api<Student[]>("/api/students?limit=200"), []);
  const act = useAction();

  const studentName = (id: string) => students.data?.find((s) => s.id === id)?.full_name ?? id.slice(0, 8);
  const selected = slips.data?.find((s) => s.id === selectedId) ?? null;
  const link = selected ? `${window.location.origin}${window.location.pathname}#/verify/${selected.token}` : "";

  async function addRecipient(e: FormEvent) {
    e.preventDefault();
    if (!selected) return;
    const ok = await act.run(() => post<Slip>(`/api/excuses/${selected.id}/recipients`, rec), "Instructor added and notified.");
    if (ok) { setRec({ instructor_name: "", instructor_email: "" }); slips.reload(); }
  }

  async function revoke() {
    if (!selected || !window.confirm("Revoke this excuse slip? Anyone scanning it will see it as revoked.")) return;
    if (await act.run(() => patch<Slip>(`/api/excuses/${selected.id}/revoke`, { reason: reason || null }), "Slip revoked.")) {
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
      <h2>Excuse slips</h2>
      <p className="muted">Slips are issued automatically when a doctor completes a visit and marks that an excuse is needed.</p>
      <ErrorBox message={act.error} />
      <OkBox message={act.notice} />
      <div className="card">
        <Loading show={slips.loading} />
        <ErrorBox message={slips.error} />
        <div className="scroll">
          <table>
            <thead><tr><th>Student</th><th>Valid</th><th>Status</th><th>Student notified</th><th></th></tr></thead>
            <tbody>
              {(slips.data ?? []).map((s) => (
                <tr key={s.id}>
                  <td>{studentName(s.student_id)}</td>
                  <td>{fmtDate(s.valid_from)} to {fmtDate(s.valid_until)}</td>
                  <td><Badge value={s.effective_status} /></td>
                  <td>{s.student_notified ? "Yes" : "No"}</td>
                  <td><button className="small" onClick={() => setSelectedId(s.id)}>Open</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {selected && (
        <div className="card">
          <h3>{studentName(selected.student_id)} - <Badge value={selected.effective_status} /></h3>
          <div className="row" style={{ alignItems: "flex-start" }}>
            <Qr id={selected.id} />
            <div style={{ flex: 1, minWidth: 240 }}>
              <p>Valid {fmtDate(selected.valid_from)} to {fmtDate(selected.valid_until)}<br />
                <span className="muted">Issued {fmtDateTime(selected.issued_at)}</span></p>
              <p className="muted">Verification link: <a href={link} target="_blank" rel="noreferrer">{link}</a></p>
              {selected.status === "revoked" && <p>Revoked{selected.revoke_reason ? `: ${selected.revoke_reason}` : ""}</p>}
              <div className="row">
                <button className="secondary" onClick={resend} disabled={act.busy}>Notify student again</button>
              </div>
              {selected.status === "valid" && (
                <div className="row" style={{ marginTop: 10 }}>
                  <Field label="Reason for revoking (optional)"><input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
                  <button className="danger" onClick={revoke} disabled={act.busy}>Revoke slip</button>
                </div>
              )}
            </div>
          </div>
          <h3 style={{ marginTop: 16 }}>Instructors informed</h3>
          {selected.recipients.length === 0 && <p className="muted">None yet.</p>}
          <ul>{selected.recipients.map((r) => <li key={r.id}>{r.instructor_name} ({r.instructor_email})</li>)}</ul>
          {selected.status === "valid" && (
            <form className="row" onSubmit={addRecipient}>
              <Field label="Instructor name"><input value={rec.instructor_name} onChange={(e) => setRec({ ...rec, instructor_name: e.target.value })} required /></Field>
              <Field label="Instructor email"><input type="email" value={rec.instructor_email} onChange={(e) => setRec({ ...rec, instructor_email: e.target.value })} required /></Field>
              <button type="submit" disabled={act.busy}>Add and notify</button>
            </form>
          )}
        </div>
      )}
    </>
  );
}
