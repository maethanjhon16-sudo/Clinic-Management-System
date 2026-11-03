import { FormEvent, useState } from "react";
import { api, del, post, Student } from "../api";
import { Badge, EmptyRow, ErrorBox, Loading, OkBox, PageHeader, useAction, useLoad } from "../ui";

const EMPTY = { student_number: "", full_name: "", email: "", program: "", year_level: "", contact_number: "" };

export default function Students() {
  const [q, setQ] = useState("");
  const [form, setForm] = useState(EMPTY);
  const list = useLoad(() => api<Student[]>(`/api/students?limit=200${q ? `&q=${encodeURIComponent(q)}` : ""}`), [q]);
  const act = useAction();

  async function add(e: FormEvent) {
    e.preventDefault();
    const ok = await act.run(
      () => post<Student>("/api/students", {
        student_number: form.student_number, full_name: form.full_name, email: form.email,
        program: form.program || null, year_level: form.year_level ? Number(form.year_level) : null,
        contact_number: form.contact_number || null,
      }),
      "The student was added."
    );
    if (ok) { setForm(EMPTY); list.reload(); }
  }

  async function deactivate(s: Student) {
    if (!window.confirm(`Deactivate ${s.full_name}? They will no longer be able to book appointments.`)) return;
    if (await act.run(() => del(`/api/students/${s.id}`), "The student was deactivated.")) list.reload();
  }

  const set = (key: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  return (
    <>
      <PageHeader title="Students" subtitle="Student records used for appointments and consultations." />
      <form className="card" onSubmit={add}>
        <h2>Add a student</h2>
        <p className="sub">The student's email address is used for appointment and excuse slip notifications.</p>
        <div className="form-grid">
          <div className="field"><label>Student number</label><input value={form.student_number} onChange={set("student_number")} required /></div>
          <div className="field"><label>Full name</label><input value={form.full_name} onChange={set("full_name")} required /></div>
          <div className="field"><label>Email address</label><input type="email" value={form.email} onChange={set("email")} required /></div>
          <div className="field"><label>Program</label><input value={form.program} onChange={set("program")} /></div>
          <div className="field"><label>Year level</label><input type="number" min={1} max={8} value={form.year_level} onChange={set("year_level")} /></div>
          <div className="field"><label>Contact number</label><input value={form.contact_number} onChange={set("contact_number")} /></div>
        </div>
        <div className="actions"><button type="submit" disabled={act.busy}>Add student</button></div>
        <ErrorBox message={act.error} />
        <OkBox message={act.notice} />
      </form>
      <div className="card">
        <div className="inline" style={{ marginBottom: 16 }}>
          <div className="field" style={{ minWidth: 280 }}>
            <label>Search</label>
            <input placeholder="Name, student number or email" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
        </div>
        <Loading show={list.loading} />
        <ErrorBox message={list.error} />
        <div className="table-wrap">
          <table>
            <thead><tr><th>Student number</th><th>Name</th><th>Email</th><th>Program</th><th>Year</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {(list.data ?? []).map((s) => (
                <tr key={s.id}>
                  <td>{s.student_number}</td><td>{s.full_name}</td><td>{s.email}</td>
                  <td>{s.program ?? ""}</td><td>{s.year_level ?? ""}</td>
                  <td><Badge value={s.is_active ? "active" : "inactive"} /></td>
                  <td><button className="small danger" onClick={() => deactivate(s)}>Deactivate</button></td>
                </tr>
              ))}
              <EmptyRow show={!list.loading && (list.data ?? []).length === 0} cols={7} text="No students found." />
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
