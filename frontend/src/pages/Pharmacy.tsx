import { FormEvent, useState } from "react";
import { api, Dispensing, Medicine, patch, post } from "../api";
import { useAuth } from "../auth";
import { Badge, ErrorBox, Field, fmtDate, fmtDateTime, Loading, OkBox, useAction, useLoad } from "../ui";

const EMPTY = { name: "", unit: "", stock: "0", reorder_level: "10", expiry_date: "" };

export default function Pharmacy() {
  const { user } = useAuth();
  const canWrite = user?.role === "admin" || user?.role === "nurse";
  const [form, setForm] = useState(EMPTY);
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [filter, setFilter] = useState("reserved");
  const meds = useLoad(() => api<Medicine[]>("/api/medicines?limit=500"), []);
  const records = useLoad(() => api<Dispensing[]>(`/api/dispensing?limit=100${filter ? `&status=${filter}` : ""}`), [filter]);
  const act = useAction();

  const medName = (id: string) => meds.data?.find((m) => m.id === id)?.name ?? id.slice(0, 8);

  async function add(e: FormEvent) {
    e.preventDefault();
    const ok = await act.run(
      () => post<Medicine>("/api/medicines", {
        name: form.name, unit: form.unit || null, stock: Number(form.stock),
        reorder_level: Number(form.reorder_level), expiry_date: form.expiry_date || null,
      }),
      "Medicine added."
    );
    if (ok) { setForm(EMPTY); meds.reload(); }
  }

  async function restock(m: Medicine) {
    const qty = Number(amounts[m.id] ?? "");
    if (!qty || qty < 1) return;
    if (await act.run(() => post<Medicine>(`/api/medicines/${m.id}/restock`, { quantity: qty }), `${m.name} restocked.`)) {
      setAmounts({ ...amounts, [m.id]: "" });
      meds.reload();
    }
  }

  async function change(r: Dispensing, action: "confirm" | "cancel") {
    const ok = await act.run(() => patch(`/api/dispensing/${r.id}/${action}`), action === "confirm" ? "Marked as dispensed." : "Reservation cancelled, stock restored.");
    if (ok) { records.reload(); meds.reload(); }
  }

  return (
    <>
      <h2>Pharmacy</h2>
      <ErrorBox message={act.error} />
      <OkBox message={act.notice} />
      {canWrite && (
        <form className="card" onSubmit={add}>
          <h3>Add a medicine</h3>
          <div className="row">
            <Field label="Name"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></Field>
            <Field label="Unit"><input value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} placeholder="tablet" style={{ minWidth: 90, width: 100 }} /></Field>
            <Field label="Stock"><input type="number" min={0} value={form.stock} onChange={(e) => setForm({ ...form, stock: e.target.value })} style={{ minWidth: 80, width: 90 }} /></Field>
            <Field label="Reorder level"><input type="number" min={0} value={form.reorder_level} onChange={(e) => setForm({ ...form, reorder_level: e.target.value })} style={{ minWidth: 80, width: 100 }} /></Field>
            <Field label="Expiry date"><input type="date" value={form.expiry_date} onChange={(e) => setForm({ ...form, expiry_date: e.target.value })} /></Field>
            <button type="submit" disabled={act.busy}>Add</button>
          </div>
        </form>
      )}
      <div className="card">
        <h3>Medicines</h3>
        <Loading show={meds.loading} />
        <ErrorBox message={meds.error} />
        <div className="scroll">
          <table>
            <thead><tr><th>Name</th><th>Stock</th><th>Reorder at</th><th>Expiry</th><th>Flags</th>{canWrite && <th>Restock</th>}</tr></thead>
            <tbody>
              {(meds.data ?? []).map((m) => (
                <tr key={m.id}>
                  <td>{m.name}</td><td>{m.stock} {m.unit ?? ""}</td><td>{m.reorder_level}</td>
                  <td>{m.expiry_date ? fmtDate(m.expiry_date) : "-"}</td>
                  <td>{m.expired && <Badge value="expired" />} {m.low_stock && <Badge value="low" />}</td>
                  {canWrite && (
                    <td>
                      <input type="number" min={1} value={amounts[m.id] ?? ""} onChange={(e) => setAmounts({ ...amounts, [m.id]: e.target.value })} style={{ minWidth: 70, width: 80 }} />{" "}
                      <button className="small" onClick={() => restock(m)} disabled={act.busy}>Add</button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="card">
        <h3>Dispensing</h3>
        <div className="row" style={{ marginBottom: 10 }}>
          <Field label="Status">
            <select value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="reserved">Reserved (waiting for pickup)</option><option value="dispensed">Dispensed</option>
              <option value="cancelled">Cancelled</option><option value="">All</option>
            </select>
          </Field>
        </div>
        <Loading show={records.loading} />
        <ErrorBox message={records.error} />
        <div className="scroll">
          <table>
            <thead><tr><th>Created</th><th>Medicine</th><th>Qty</th><th>Status</th>{canWrite && <th></th>}</tr></thead>
            <tbody>
              {(records.data ?? []).map((r) => (
                <tr key={r.id}>
                  <td>{fmtDateTime(r.created_at)}</td><td>{medName(r.medicine_id)}</td><td>{r.quantity}</td><td><Badge value={r.status} /></td>
                  {canWrite && (
                    <td>
                      {r.status === "reserved" && (
                        <>
                          <button className="small" onClick={() => change(r, "confirm")} disabled={act.busy}>Hand over</button>{" "}
                          <button className="small danger" onClick={() => change(r, "cancel")} disabled={act.busy}>Cancel</button>
                        </>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
