import { FormEvent, useState } from "react";
import { api, del, post, Student } from "../api";
import { useAuth } from "../auth";
import { Badge, ErrorBox, Field, Loading, OkBox, useAction, useLoad } from "../ui";

const EMPTY = { student_number: "", full_name: "", email: "", program: "", year_level: "", contact_number: "" };

export default function Students() {
  const { user } = useAuth();
  const canWrite = user?.role === "admin" || user?.role === "nurse";
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
      "Student added."
    );
    if (ok) { setForm(EMPTY); list.reload(); }
  }

  async function deactivate(s: Student) {
    if (!window.confirm(`Deactivate ${s.full_name}?`)) return;
    if (await act.run(() => del(`/api/students/${s.id}`), "Student deactivated.")) list.reload();
  }

  const set = (key: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  return (
    <>
      <h2>Students</h2>
      {canWrite && (
        <form className="card" onSubmit={add}>
          <h3>Add a student</h3>
          <div className="row">
            <Field label="Student number"><input value={form.student_number} onChange={set("student_number")} required /></Field>
            <Field label="Full name"><input value={form.full_name} onChange={set("full_name")} required /></Field>
            <Field label="Email"><input type="email" value={form.email} onChange={set("email")} required /></Field>
            <Field label="Program"><input value={form.program} onChange={set("program")} /></Field>
            <Field label="Year"><input type="number" min={1} max={8} value={form.year_level} onChange={set("year_level")} style={{ minWidth: 70, width: 80 }} /></Field>
            <button type="submit" disabled={act.busy}>Add</button>
          </div>
        </form>
      )}
      <ErrorBox message={act.error} />
      <OkBox message={act.notice} />
      <div className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          <Field label="Search"><input placeholder="Name, number or email" value={q} onChange={(e) => setQ(e.target.value)} /></Field>
        </div>
        <Loading show={list.loading} />
        <ErrorBox message={list.error} />
        <div className="scroll">
          <table>
            <thead><tr><th>Number</th><th>Name</th><th>Email</th><th>Program</th><th>Year</th><th>Status</th>{canWrite && <th></th>}</tr></thead>
            <tbody>
              {(list.data ?? []).map((s) => (
                <tr key={s.id}>
                  <td>{s.student_number}</td><td>{s.full_name}</td><td>{s.email}</td>
                  <td>{s.program ?? ""}</td><td>{s.year_level ?? ""}</td>
                  <td><Badge value={s.is_active ? "active" : "inactive"} /></td>
                  {canWrite && <td><button className="small danger" onClick={() => deactivate(s)}>Deactivate</button></td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
