import { FormEvent, useState } from "react";
import { api, Appointment, Consultation, Medicine, post, Student } from "../api";
import { useAuth } from "../auth";
import { Badge, ErrorBox, Field, fmtDateTime, Loading, OkBox, useAction, useLoad } from "../ui";

interface Rx { medicine_id: string; quantity: string; instructions: string }

function FollowUps({ c }: { c: Consultation }) {
  return (
    <div>
      {c.events.map((e) => (
        <div key={e.target} style={{ marginBottom: 4 }}>
          <Badge value={e.status} /> {e.target}
          {e.last_error && <span className="muted"> - {e.last_error}</span>}
        </div>
      ))}
    </div>
  );
}

export default function Consultations() {
  const { user } = useAuth();
  const canWrite = user?.role === "doctor" || user?.role === "admin";
  const [form, setForm] = useState({ appointment_id: "", notes: "", needs_excuse: false, rest_days: "1" });
  const [rx, setRx] = useState<Rx[]>([]);
  const [result, setResult] = useState<Consultation | null>(null);
  const appts = useLoad(() => api<Appointment[]>("/api/appointments?status=scheduled&limit=200"), []);
  const students = useLoad(() => api<Student[]>("/api/students?limit=200"), []);
  const meds = useLoad(() => api<Medicine[]>("/api/medicines?limit=500"), []);
  const history = useLoad(() => api<Consultation[]>("/api/consultations?limit=50"), []);
  const save = useAction();
  const retry = useAction();

  const studentName = (id: string) => students.data?.find((s) => s.id === id)?.full_name ?? id.slice(0, 8);
  const medName = (id: string) => meds.data?.find((m) => m.id === id)?.name ?? id.slice(0, 8);

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
    const ok = await save.run(async () => { setResult(await post<Consultation>("/api/consultations", body)); }, "Consultation saved.");
    if (ok) {
      setForm({ appointment_id: "", notes: "", needs_excuse: false, rest_days: "1" });
      setRx([]);
      appts.reload(); history.reload(); meds.reload();
    }
  }

  async function retryFollowUps(c: Consultation) {
    if (await retry.run(() => post<Consultation>(`/api/consultations/${c.id}/retry`), "Follow-ups retried.")) history.reload();
  }

  const updateRx = (i: number, patchValue: Partial<Rx>) => setRx(rx.map((r, idx) => (idx === i ? { ...r, ...patchValue } : r)));

  return (
    <>
      <h2>Consultations</h2>
      {canWrite && (
        <form className="card" onSubmit={submit}>
          <h3>Complete a visit</h3>
          <div className="row">
            <Field label="Appointment">
              <select value={form.appointment_id} onChange={(e) => setForm({ ...form, appointment_id: e.target.value })} required>
                <option value="">Select a scheduled appointment...</option>
                {(appts.data ?? []).map((a) => <option key={a.id} value={a.id}>{studentName(a.student_id)} - {fmtDateTime(a.scheduled_at)}</option>)}
              </select>
            </Field>
            <Field label="Needs a medical excuse?">
              <select value={form.needs_excuse ? "yes" : "no"} onChange={(e) => setForm({ ...form, needs_excuse: e.target.value === "yes" })}>
                <option value="no">No</option><option value="yes">Yes</option>
              </select>
            </Field>
            {form.needs_excuse && (
              <Field label="Rest days">
                <input type="number" min={1} max={30} value={form.rest_days} onChange={(e) => setForm({ ...form, rest_days: e.target.value })} style={{ minWidth: 80, width: 90 }} />
              </Field>
            )}
          </div>
          <div style={{ margin: "12px 0" }}>
            <label>Notes</label>
            <textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </div>
          <h3>Prescription</h3>
          {rx.map((r, i) => (
            <div className="rx" key={i}>
              <select value={r.medicine_id} onChange={(e) => updateRx(i, { medicine_id: e.target.value })}>
                <option value="">Medicine...</option>
                {(meds.data ?? []).map((m) => <option key={m.id} value={m.id}>{m.name} (stock {m.stock})</option>)}
              </select>
              <input type="number" min={1} placeholder="Qty" value={r.quantity} onChange={(e) => updateRx(i, { quantity: e.target.value })} style={{ minWidth: 70, width: 80 }} />
              <input placeholder="Instructions" value={r.instructions} onChange={(e) => updateRx(i, { instructions: e.target.value })} />
              <button type="button" className="secondary small" onClick={() => setRx(rx.filter((_, idx) => idx !== i))}>Remove</button>
            </div>
          ))}
          <div className="row">
            <button type="button" className="secondary" onClick={() => setRx([...rx, { medicine_id: "", quantity: "1", instructions: "" }])}>Add medicine</button>
            <button type="submit" disabled={save.busy}>{save.busy ? "Saving... (this can take a minute)" : "Complete visit"}</button>
          </div>
          <ErrorBox message={save.error} />
          <OkBox message={save.notice} />
          {result && (
            <div className="alert ok">
              Follow-up actions: <Badge value={result.integration_status} />
              <FollowUps c={result} />
            </div>
          )}
        </form>
      )}
      <ErrorBox message={retry.error} />
      <OkBox message={retry.notice} />
      <div className="card">
        <h3>Recent consultations</h3>
        <Loading show={history.loading} />
        <ErrorBox message={history.error} />
        <div className="scroll">
          <table>
            <thead><tr><th>When</th><th>Student</th><th>Medicines</th><th>Excuse</th><th>Follow-ups</th><th></th></tr></thead>
            <tbody>
              {(history.data ?? []).map((c) => (
                <tr key={c.id}>
                  <td>{fmtDateTime(c.completed_at)}</td>
                  <td>{studentName(c.student_id)}</td>
                  <td>{c.prescriptions.map((p) => `${medName(p.medicine_id)} x${p.quantity}`).join(", ") || "-"}</td>
                  <td>{c.needs_excuse ? `${c.rest_days} day(s)` : "-"}</td>
                  <td><FollowUps c={c} /></td>
                  <td>{canWrite && c.integration_status !== "complete" && <button className="small" onClick={() => retryFollowUps(c)}>Retry</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
