import { FormEvent, useState } from "react";
import { api, patch, post, Role, Student, User } from "../api";
import { useAuth } from "../auth";
import { Badge, ErrorBox, Field, OkBox, useAction, useLoad } from "../ui";

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
      "User created."
    );
    if (ok) { setForm(EMPTY); users.reload(); }
  }

  async function toggle(u: User) {
    if (await act.run(() => patch<User>(`/auth/users/${u.id}`, { is_active: !u.is_active }), u.is_active ? "User deactivated." : "User reactivated.")) users.reload();
  }

  return (
    <>
      <h2>Users</h2>
      <form className="card" onSubmit={create}>
        <h3>Create a user</h3>
        <div className="row">
          <Field label="Full name"><input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required /></Field>
          <Field label="Email"><input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required /></Field>
          <Field label="Password (8+ characters)"><input type="password" minLength={8} maxLength={72} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required /></Field>
          <Field label="Role">
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
              <option value="admin">Admin</option><option value="doctor">Doctor</option>
              <option value="nurse">Nurse</option><option value="student">Student</option>
            </select>
          </Field>
          {form.role === "student" && (
            <Field label="Student record">
              <select value={form.student_id} onChange={(e) => setForm({ ...form, student_id: e.target.value })} required>
                <option value="">Select...</option>
                {(students.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.full_name} ({s.student_number})</option>)}
              </select>
            </Field>
          )}
          <button type="submit" disabled={act.busy}>Create</button>
        </div>
      </form>
      <ErrorBox message={act.error} />
      <OkBox message={act.notice} />
      <div className="card">
        <ErrorBox message={users.error} />
        <div className="scroll">
          <table>
            <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {(users.data ?? []).map((u) => (
                <tr key={u.id}>
                  <td>{u.full_name}</td><td>{u.email}</td><td>{u.role}</td>
                  <td><Badge value={u.is_active ? "active" : "inactive"} /></td>
                  <td>{u.id !== me?.id && <button className="small secondary" onClick={() => toggle(u)} disabled={act.busy}>{u.is_active ? "Deactivate" : "Reactivate"}</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
