import { FormEvent, useState } from "react";
import { api, Instructor, post, put } from "../api";
import { Badge, EmptyRow, ErrorBox, Loading, OkBox, PageHeader, useAction, useLoad } from "../ui";

const EMPTY = { full_name: "", email: "", department: "" };

// One instructor per line: Full name, email, department (the department is optional)
function parseLines(text: string) {
  const items: { full_name: string; email: string; department: string | null }[] = [];
  const invalid: string[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const parts = line.split(/[,\t;]/).map((p) => p.trim()).filter(Boolean);
    const email = parts.find((p) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(p));
    if (!email || parts.length < 2) { invalid.push(line); continue; }
    const name = parts[0] === email ? parts[1] : parts[0];
    const rest = parts.filter((p) => p !== email && p !== name);
    items.push({ full_name: name, email, department: rest[0] ?? null });
  }
  return { items, invalid };
}

export default function Instructors() {
  const [form, setForm] = useState(EMPTY);
  const [bulk, setBulk] = useState("");
  const [bulkResult, setBulkResult] = useState("");
  const [q, setQ] = useState("");
  const list = useLoad(() => api<Instructor[]>(`/api/instructors?active_only=false&limit=500${q ? `&q=${encodeURIComponent(q)}` : ""}`), [q]);
  const one = useAction();
  const many = useAction();

  async function add(e: FormEvent) {
    e.preventDefault();
    const ok = await one.run(
      () => post<Instructor>("/api/instructors", { full_name: form.full_name, email: form.email, department: form.department || null }),
      "The instructor was added."
    );
    if (ok) { setForm(EMPTY); list.reload(); }
  }

  async function addMany(e: FormEvent) {
    e.preventDefault();
    setBulkResult("");
    const { items, invalid } = parseLines(bulk);
    const ok = await many.run(async () => {
      if (items.length === 0) throw new Error("Enter one instructor per line: full name, email address, department (optional).");
      const res = await post<{ created: number; skipped: string[] }>("/api/instructors/bulk", { items });
      setBulkResult(
        `${res.created} instructor(s) added.` +
        (res.skipped.length ? ` Skipped (already listed or not a school email): ${res.skipped.join(", ")}.` : "") +
        (invalid.length ? ` ${invalid.length} line(s) were not understood and are left in the box.` : "")
      );
    });
    if (ok) { setBulk(invalid.join("\n")); list.reload(); }
  }

  async function toggle(i: Instructor) {
    if (await one.run(() => put<Instructor>(`/api/instructors/${i.id}`, { is_active: !i.is_active }), i.is_active ? "The instructor was removed from the list." : "The instructor was added back to the list.")) list.reload();
  }

  return (
    <>
      <PageHeader title="Instructors" subtitle="Add instructors once, using their school email addresses, then pick them when sending an excuse slip." />
      <form className="card" onSubmit={add}>
        <h2>Add an instructor</h2>
        <div className="form-grid" style={{ marginTop: 12 }}>
          <div className="field"><label>Full name</label><input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required /></div>
          <div className="field"><label>School email address</label><input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required /></div>
          <div className="field"><label>Department or subject (optional)</label><input value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })} /></div>
        </div>
        <div className="actions"><button type="submit" disabled={one.busy}>Add instructor</button></div>
        <ErrorBox message={one.error} />
        <OkBox message={one.notice} />
      </form>
      <form className="card" onSubmit={addMany}>
        <h2>Add several at once</h2>
        <p className="sub">Type or paste one instructor per line: full name, school email, department (optional).</p>
        <textarea value={bulk} onChange={(e) => setBulk(e.target.value)} placeholder={"Maria Santos, maria.santos@school.edu.ph, Mathematics\nJuan Reyes, juan.reyes@school.edu.ph"} />
        <div className="actions"><button type="submit" className="secondary" disabled={many.busy}>Add all</button></div>
        <ErrorBox message={many.error} />
        <OkBox message={bulkResult} />
      </form>
      <div className="card">
        <div className="inline" style={{ marginBottom: 16 }}>
          <div className="field" style={{ minWidth: 280 }}>
            <label>Search</label>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, email or department" />
          </div>
        </div>
        <Loading show={list.loading} />
        <ErrorBox message={list.error} />
        <div className="table-wrap">
          <table>
            <thead><tr><th>Name</th><th>School email</th><th>Department</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {(list.data ?? []).map((i) => (
                <tr key={i.id}>
                  <td>{i.full_name}</td><td>{i.email}</td><td>{i.department ?? ""}</td>
                  <td><Badge value={i.is_active ? "active" : "inactive"} /></td>
                  <td><button className="small secondary" onClick={() => toggle(i)} disabled={one.busy}>{i.is_active ? "Remove from list" : "Add back"}</button></td>
                </tr>
              ))}
              <EmptyRow show={!list.loading && (list.data ?? []).length === 0} cols={5} text="No instructors have been added yet." />
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
