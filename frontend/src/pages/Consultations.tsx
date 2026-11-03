import { FormEvent, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, Appointment, Consultation, Medicine, post, Student } from "../api";
import { Badge, EmptyRow, ErrorBox, fmtDateTime, Loading, OkBox, PageHeader, useAction, useLoad } from "../ui";

interface Rx { medicine_id: string; quantity: string; instructions: string }

function FollowUps({ c }: { c: Consultation }) {
  const names: Record<string, string> = { appointment: "Appointment record", pharmacy: "Pharmacy", excuse: "Excuse slip" };
  return (
    <div>
      {c.events.map((e) => (
        <div key={e.target} style={{ marginBottom: 4 }}>
          {names[e.target] ?? e.target}: <Badge value={e.status} />
          {e.last_error && <span className="muted"> {e.last_error}</span>}
        </div>
      ))}
    </div>
  );
}

export default function Consultations() {
  const [params] = useSearchParams();
  const [form, setForm] = useState({ appointment_id: params.get("appointment") ?? "", notes: "", needs_excuse: false, rest_days: "1" });
  const [rx, setRx] = useState<Rx[]>([]);
  const [result, setResult] = useState<Consultation | null>(null);
  const appts = useLoad(() => api<Appointment[]>("/api/appointments?status=scheduled&limit=200"), []);
  const students = useLoad(() => api<Student[]>("/api/students?limit=200"), []);
  const meds = useLoad(() => api<Medicine[]>("/api/medicines?limit=500"), []);
  const history = useLoad(() => api<Consultation[]>("/api/consultations?limit=50"), []);
  const save = useAction();
  const retry = useAction();

  const studentName = (id: string) => students.data?.find((s) => s.id === id)?.full_name ?? "Unknown student";
  const medName = (id: string) => meds.data?.find((m) => m.id === id)?.name ?? "Unknown medicine";

  async function submit(e: FormEvent) {
    e.preventDefault();
    const body = {
      appointment_id: form.appointment_id,
      notes: form.notes || null,
      needs_excuse: form.needs_excuse,
      rest_days: form.needs_excuse ? Number(form.rest_days) : null,
      prescriptions: rx.filter((r) => r.medicine_id).map((r) => ({
        medicine_id: r.medicine_id, quantity: Number(r.quantity), instructions: r.instructions || null,
      })),
    };
    const ok = await save.run(async () => { setResult(await post<Consultation>("/api/consultations", body)); }, "The consultation was saved.");
    if (ok) {
      setForm({ appointment_id: "", notes: "", needs_excuse: false, rest_days: "1" });
      setRx([]);
      appts.reload(); history.reload(); meds.reload();
    }
  }

  async function retryFollowUps(c: Consultation) {
    if (await retry.run(() => post<Consultation>(`/api/consultations/${c.id}/retry`), "The pending steps were retried.")) history.reload();
  }

  const updateRx = (i: number, changes: Partial<Rx>) => setRx(rx.map((r, idx) => (idx === i ? { ...r, ...changes } : r)));

  return (
    <>
      <PageHeader title="Consultations" subtitle="Record a visit, issue medicine and, if needed, a medical excuse slip." />
      <form className="card" onSubmit={submit}>
        <h2>Complete a visit</h2>
        <p className="sub">Saving the visit marks the appointment as completed, reserves the medicine and issues the excuse slip.</p>
        <div className="form-grid">
          <div className="field">
            <label>Appointment</label>
            <select value={form.appointment_id} onChange={(e) => setForm({ ...form, appointment_id: e.target.value })} required>
              <option value="">Select a scheduled appointment</option>
              {(appts.data ?? []).map((a) => <option key={a.id} value={a.id}>{studentName(a.student_id)} - {fmtDateTime(a.scheduled_at)}</option>)}
            </select>
          </div>
          <div className="field">
            <label>Medical excuse needed</label>
            <select value={form.needs_excuse ? "yes" : "no"} onChange={(e) => setForm({ ...form, needs_excuse: e.target.value === "yes" })}>
              <option value="no">No</option><option value="yes">Yes</option>
            </select>
          </div>
          {form.needs_excuse && (
            <div className="field">
              <label>Days of rest</label>
              <input type="number" min={1} max={30} value={form.rest_days} onChange={(e) => setForm({ ...form, rest_days: e.target.value })} />
            </div>
          )}
        </div>
        <div className="field" style={{ marginTop: 16 }}>
          <label>Notes</label>
          <textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
        </div>
        <h3 className="section-title">Medicine given</h3>
        {rx.map((r, i) => (
          <div className="rx" key={i}>
            <select value={r.medicine_id} onChange={(e) => updateRx(i, { medicine_id: e.target.value })}>
              <option value="">Select medicine</option>
              {(meds.data ?? []).map((m) => <option key={m.id} value={m.id}>{m.name} (stock {m.stock})</option>)}
            </select>
            <input type="number" min={1} placeholder="Qty" value={r.quantity} onChange={(e) => updateRx(i, { quantity: e.target.value })} />
            <input placeholder="Instructions" value={r.instructions} onChange={(e) => updateRx(i, { instructions: e.target.value })} />
            <button type="button" className="secondary small" onClick={() => setRx(rx.filter((_, idx) => idx !== i))}>Remove</button>
          </div>
        ))}
        <button type="button" className="secondary" onClick={() => setRx([...rx, { medicine_id: "", quantity: "1", instructions: "" }])}>Add medicine</button>
        <div className="actions">
          <button type="submit" disabled={save.busy}>{save.busy ? "Saving..." : "Save consultation"}</button>
        </div>
        <ErrorBox message={save.error} />
        <OkBox message={save.notice} />
        {result && (
          <div className="alert info">
            Follow-up status: <Badge value={result.integration_status} />
            <FollowUps c={result} />
          </div>
        )}
      </form>
      <ErrorBox message={retry.error} />
      <OkBox message={retry.notice} />
      <div className="card">
        <h2>Recent consultations</h2>
        <p className="sub">If a step did not finish, for example while a service was unavailable, use Retry.</p>
        <Loading show={history.loading} />
        <ErrorBox message={history.error} />
        <div className="table-wrap">
          <table>
            <thead><tr><th>Date</th><th>Student</th><th>Attended by</th><th>Medicine</th><th>Excuse</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {(history.data ?? []).map((c) => (
                <tr key={c.id}>
                  <td>{fmtDateTime(c.completed_at)}</td>
                  <td>{studentName(c.student_id)}</td>
                  <td>{c.attended_by_name ?? ""}</td>
                  <td>{c.prescriptions.map((p) => `${medName(p.medicine_id)} x${p.quantity}`).join(", ") || "None"}</td>
                  <td>{c.needs_excuse ? `${c.rest_days} day(s)` : "None"}</td>
                  <td><FollowUps c={c} /></td>
                  <td>{c.integration_status !== "complete" && <button className="small" onClick={() => retryFollowUps(c)}>Retry</button>}</td>
                </tr>
              ))}
              <EmptyRow show={!history.loading && (history.data ?? []).length === 0} cols={7} text="No consultations have been recorded yet." />
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
