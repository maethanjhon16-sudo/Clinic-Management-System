import { FormEvent, useState } from "react";
import { api, Appointment, patch, post, Student } from "../api";
import SlotPicker from "../SlotPicker";
import { Badge, EmptyRow, ErrorBox, fmtDateTime, Loading, OkBox, PageHeader, useAction, useLoad } from "../ui";

export default function Appointments() {
  const [status, setStatus] = useState("");
  const [studentId, setStudentId] = useState("");
  const [when, setWhen] = useState("");
  const [reason, setReason] = useState("");
  const [pickerKey, setPickerKey] = useState(0);
  const students = useLoad(() => api<Student[]>("/api/students?limit=200"), []);
  const list = useLoad(() => api<Appointment[]>(`/api/appointments?limit=200${status ? `&status=${status}` : ""}`), [status]);
  const book = useAction();
  const other = useAction();

  const studentName = (id: string) => students.data?.find((s) => s.id === id)?.full_name ?? "Unknown student";

  async function submit(e: FormEvent) {
    e.preventDefault();
    const ok = await book.run(async () => {
      if (!studentId) throw new Error("Please select a student.");
      if (!when) throw new Error("Please choose a date and an available time.");
      await post<Appointment>("/api/appointments", { student_id: studentId, scheduled_at: when, reason: reason || null });
    }, "The appointment was booked and the student will be notified.");
    if (ok) { setWhen(""); setReason(""); setPickerKey(pickerKey + 1); list.reload(); }
  }

  async function cancel(a: Appointment) {
    if (!window.confirm("Cancel this appointment? The student will be notified.")) return;
    if (await other.run(() => patch(`/api/appointments/${a.id}/cancel`), "The appointment was cancelled.")) list.reload();
  }

  return (
    <>
      <PageHeader title="Appointments" subtitle="Schedule visits for students and manage the clinic calendar." />
      <form className="card" onSubmit={submit}>
        <h2>Schedule an appointment</h2>
        <p className="sub">Choose the student, then a date and an available time.</p>
        <div className="form-grid" style={{ marginBottom: 18 }}>
          <div className="field">
            <label>Student</label>
            <select value={studentId} onChange={(e) => setStudentId(e.target.value)}>
              <option value="">Select a student</option>
              {(students.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.full_name} ({s.student_number})</option>)}
            </select>
          </div>
          <div className="field"><label>Reason for visit</label><input value={reason} onChange={(e) => setReason(e.target.value)} /></div>
        </div>
        <SlotPicker key={pickerKey} value={when} onChange={setWhen} />
        <div className="actions"><button type="submit" disabled={book.busy}>{book.busy ? "Booking..." : "Book appointment"}</button></div>
        <ErrorBox message={book.error} />
        <OkBox message={book.notice} />
      </form>
      <div className="card">
        <div className="inline" style={{ marginBottom: 16 }}>
          <div className="field" style={{ minWidth: 200 }}>
            <label>Status</label>
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All appointments</option><option value="scheduled">Scheduled</option>
              <option value="completed">Completed</option><option value="cancelled">Cancelled</option>
            </select>
          </div>
        </div>
        <ErrorBox message={other.error} />
        <OkBox message={other.notice} />
        <Loading show={list.loading} />
        <ErrorBox message={list.error} />
        <div className="table-wrap">
          <table>
            <thead><tr><th>Date and time</th><th>Student</th><th>Reason</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {(list.data ?? []).map((a) => (
                <tr key={a.id}>
                  <td>{fmtDateTime(a.scheduled_at)}</td><td>{studentName(a.student_id)}</td>
                  <td>{a.reason ?? ""}</td><td><Badge value={a.status} /></td>
                  <td>{a.status === "scheduled" && <button className="small danger" onClick={() => cancel(a)}>Cancel</button>}</td>
                </tr>
              ))}
              <EmptyRow show={!list.loading && (list.data ?? []).length === 0} cols={5} text="No appointments found." />
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
