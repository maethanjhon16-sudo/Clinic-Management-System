import { FormEvent, useState } from "react";
import { api, patch, post, Role, Student, User } from "../api";
import { useAuth } from "../auth";
import { Badge, EmptyRow, ErrorBox, OkBox, PageHeader, roleLabel, useAction, useLoad } from "../ui";

const EMPTY = { email: "", password: "", full_name: "", role: "nurse" as Role, student_id: "" };

export default function Users() {
  const { user: me } = useAuth();
  const [form, setForm] = useState(EMPTY);
  const users = useLoad(() => api<User[]>("/auth/users"), []);
  const students = useLoad(() => api<Student[]>("/api/students?limit=200"), []);
  const act = useAction();

  async function create(e: FormEvent) {
    e.preventDefault();
    const ok = await act.run(
      () => post<User>("/auth/users", {
        email: form.email, password: form.password, full_name: form.full_name, role: form.role,
        student_id: form.role === "student" ? form.student_id : null,
      }),
      "The account was created."
    );
    if (ok) { setForm(EMPTY); users.reload(); }
  }

  async function toggle(u: User) {
    if (await act.run(() => patch<User>(`/auth/users/${u.id}`, { is_active: !u.is_active }), u.is_active ? "The account was deactivated." : "The account was reactivated.")) users.reload();
  }

  return (
    <>
      <PageHeader title="User accounts" subtitle="Create sign-in accounts for nurses, administrators and students." />
      <form className="card" onSubmit={create}>
        <h2>Create an account</h2>
        <p className="sub">A student account must be linked to an existing student record so the student can send medicine inquiries and view their own excuse slips.</p>
        <div className="form-grid">
          <div className="field"><label>Full name</label><input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required /></div>
          <div className="field"><label>Email address</label><input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required /></div>
          <div className="field"><label>Password (at least 8 characters)</label><input type="password" minLength={8} maxLength={72} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required /></div>
          <div className="field">
            <label>Role</label>
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
              <option value="nurse">Clinic nurse</option><option value="admin">Administrator</option><option value="student">Student</option>
            </select>
          </div>
          {form.role === "student" && (
            <div className="field">
              <label>Student record</label>
              <select value={form.student_id} onChange={(e) => setForm({ ...form, student_id: e.target.value })} required>
                <option value="">Select a student</option>
                {(students.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.full_name} ({s.student_number})</option>)}
              </select>
            </div>
          )}
        </div>
        <div className="actions"><button type="submit" disabled={act.busy}>Create account</button></div>
        <ErrorBox message={act.error} />
        <OkBox message={act.notice} />
      </form>
      <div className="card">
        <ErrorBox message={users.error} />
        <div className="table-wrap">
          <table>
            <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {(users.data ?? []).map((u) => (
                <tr key={u.id}>
                  <td>{u.full_name}</td><td>{u.email}</td><td>{roleLabel(u.role)}</td>
                  <td><Badge value={u.is_active ? "active" : "inactive"} /></td>
                  <td>{u.id !== me?.id && <button className="small secondary" onClick={() => toggle(u)} disabled={act.busy}>{u.is_active ? "Deactivate" : "Reactivate"}</button>}</td>
                </tr>
              ))}
              <EmptyRow show={!users.loading && (users.data ?? []).length === 0} cols={5} text="No accounts yet." />
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
