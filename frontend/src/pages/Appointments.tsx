import { FormEvent, useState } from "react";
import { api, Appointment, Doctor, patch, post, Student } from "../api";
import { useAuth } from "../auth";
import { Badge, ErrorBox, Field, fmtDateTime, Loading, OkBox, toManilaIso, useAction, useLoad } from "../ui";

export default function Appointments() {
  const { user } = useAuth();
  const canWrite = user?.role !== undefined && user.role !== "student";
  const isAdmin = user?.role === "admin";
  const [status, setStatus] = useState("");
  const [form, setForm] = useState({ student_id: "", doctor_id: "", when: "", reason: "" });
  const [doc, setDoc] = useState({ full_name: "", specialization: "", email: "" });
  const students = useLoad(() => api<Student[]>("/api/students?limit=200"), []);
  const doctors = useLoad(() => api<Doctor[]>("/api/doctors"), []);
  const list = useLoad(() => api<Appointment[]>(`/api/appointments?limit=200${status ? `&status=${status}` : ""}`), [status]);
  const book = useAction();
  const other = useAction();

  const studentName = (id: string) => students.data?.find((s) => s.id === id)?.full_name ?? id.slice(0, 8);
  const doctorName = (id: string) => doctors.data?.find((d) => d.id === id)?.full_name ?? id.slice(0, 8);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const ok = await book.run(
      () => post<Appointment>("/api/appointments", {
        student_id: form.student_id, doctor_id: form.doctor_id,
        scheduled_at: toManilaIso(form.when), reason: form.reason || null,
      }),
      "Appointment booked. The student will be notified."
    );
    if (ok) { setForm({ ...form, when: "", reason: "" }); list.reload(); }
  }

  async function cancel(a: Appointment) {
    if (!window.confirm("Cancel this appointment?")) return;
    if (await other.run(() => patch(`/api/appointments/${a.id}/cancel`), "Appointment cancelled.")) list.reload();
  }

  async function addDoctor(e: FormEvent) {
    e.preventDefault();
    const ok = await other.run(
      () => post<Doctor>("/api/doctors", {
        full_name: doc.full_name, specialization: doc.specialization || null, email: doc.email || null,
      }),
      "Doctor added."
    );
    if (ok) { setDoc({ full_name: "", specialization: "", email: "" }); doctors.reload(); }
  }

  return (
    <>
      <h2>Appointments</h2>
      {canWrite && (
        <form className="card" onSubmit={submit}>
          <h3>Book an appointment</h3>
          <div className="row">
            <Field label="Student">
              <select value={form.student_id} onChange={(e) => setForm({ ...form, student_id: e.target.value })} required>
                <option value="">Select...</option>
                {(students.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.full_name} ({s.student_number})</option>)}
              </select>
            </Field>
            <Field label="Doctor">
              <select value={form.doctor_id} onChange={(e) => setForm({ ...form, doctor_id: e.target.value })} required>
                <option value="">Select...</option>
                {(doctors.data ?? []).map((d) => <option key={d.id} value={d.id}>{d.full_name}</option>)}
              </select>
            </Field>
            <Field label="Date and time (Philippine time)">
              <input type="datetime-local" value={form.when} onChange={(e) => setForm({ ...form, when: e.target.value })} required />
            </Field>
            <Field label="Reason"><input value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></Field>
            <button type="submit" disabled={book.busy}>{book.busy ? "Booking..." : "Book"}</button>
          </div>
          <ErrorBox message={book.error} />
          <OkBox message={book.notice} />
        </form>
      )}
      {isAdmin && (
        <form className="card" onSubmit={addDoctor}>
          <h3>Add a doctor</h3>
          <div className="row">
            <Field label="Full name"><input value={doc.full_name} onChange={(e) => setDoc({ ...doc, full_name: e.target.value })} required /></Field>
            <Field label="Specialization"><input value={doc.specialization} onChange={(e) => setDoc({ ...doc, specialization: e.target.value })} /></Field>
            <Field label="Email"><input type="email" value={doc.email} onChange={(e) => setDoc({ ...doc, email: e.target.value })} /></Field>
            <button type="submit" disabled={other.busy}>Add doctor</button>
          </div>
        </form>
      )}
      <ErrorBox message={other.error} />
      <OkBox message={other.notice} />
      <div className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          <Field label="Status">
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All</option><option value="scheduled">Scheduled</option>
              <option value="completed">Completed</option><option value="cancelled">Cancelled</option>
            </select>
          </Field>
        </div>
        <Loading show={list.loading} />
        <ErrorBox message={list.error} />
        <div className="scroll">
          <table>
            <thead><tr><th>When</th><th>Student</th><th>Doctor</th><th>Reason</th><th>Status</th>{canWrite && <th></th>}</tr></thead>
            <tbody>
              {(list.data ?? []).map((a) => (
                <tr key={a.id}>
                  <td>{fmtDateTime(a.scheduled_at)}</td><td>{studentName(a.student_id)}</td><td>{doctorName(a.doctor_id)}</td>
                  <td>{a.reason ?? ""}</td><td><Badge value={a.status} /></td>
                  {canWrite && <td>{a.status === "scheduled" && <button className="small danger" onClick={() => cancel(a)}>Cancel</button>}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
