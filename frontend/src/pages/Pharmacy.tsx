import { FormEvent, useState } from "react";
import { api, Dispensing, Medicine, patch, post } from "../api";
import { Badge, EmptyRow, ErrorBox, fmtDate, fmtDateTime, Loading, OkBox, PageHeader, useAction, useLoad } from "../ui";

const EMPTY = { name: "", unit: "", stock: "0", reorder_level: "10", expiry_date: "", treats: "" };

export default function Pharmacy() {
  const [form, setForm] = useState(EMPTY);
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [filter, setFilter] = useState("reserved");
  const meds = useLoad(() => api<Medicine[]>("/api/medicines?limit=500"), []);
  const records = useLoad(() => api<Dispensing[]>(`/api/dispensing?limit=100${filter ? `&status=${filter}` : ""}`), [filter]);
  const act = useAction();

  const medName = (id: string) => meds.data?.find((m) => m.id === id)?.name ?? "Unknown medicine";

  async function add(e: FormEvent) {
    e.preventDefault();
    const ok = await act.run(
      () => post<Medicine>("/api/medicines", {
        name: form.name, unit: form.unit || null, stock: Number(form.stock),
        reorder_level: Number(form.reorder_level), expiry_date: form.expiry_date || null,
        treats: form.treats || null,
      }),
      "The medicine was added."
    );
    if (ok) { setForm(EMPTY); meds.reload(); }
  }

  async function restock(m: Medicine) {
    const qty = Number(amounts[m.id] ?? "");
    if (!qty || qty < 1) return;
    if (await act.run(() => post<Medicine>(`/api/medicines/${m.id}/restock`, { quantity: qty }), `${m.name} was restocked.`)) {
      setAmounts({ ...amounts, [m.id]: "" });
      meds.reload();
    }
  }

  async function change(r: Dispensing, action: "confirm" | "cancel") {
    const ok = await act.run(() => patch(`/api/dispensing/${r.id}/${action}`),
      action === "confirm" ? "The medicine was marked as given to the student." : "The reservation was cancelled and the stock returned.");
    if (ok) { records.reload(); meds.reload(); }
  }

  return (
    <>
      <PageHeader title="Pharmacy" subtitle="Medicine stock and the medicine reserved for students." />
      <ErrorBox message={act.error} />
      <OkBox message={act.notice} />
      <div className="card">
        <h2>Medicine reserved for students</h2>
        <p className="sub">Stock is reserved when a consultation is saved. Select Hand over when the student receives the medicine.</p>
        <div className="inline" style={{ marginBottom: 16 }}>
          <div className="field" style={{ minWidth: 240 }}>
            <label>Status</label>
            <select value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="reserved">Waiting for pickup</option><option value="dispensed">Given</option>
              <option value="cancelled">Cancelled</option><option value="">All</option>
            </select>
          </div>
        </div>
        <Loading show={records.loading} />
        <ErrorBox message={records.error} />
        <div className="table-wrap">
          <table>
            <thead><tr><th>Reserved on</th><th>Medicine</th><th>Quantity</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {(records.data ?? []).map((r) => (
                <tr key={r.id}>
                  <td>{fmtDateTime(r.created_at)}</td><td>{medName(r.medicine_id)}</td><td>{r.quantity}</td><td><Badge value={r.status} /></td>
                  <td>
                    {r.status === "reserved" && (
                      <div className="inline">
                        <button className="small" onClick={() => change(r, "confirm")} disabled={act.busy}>Hand over</button>
                        <button className="small danger" onClick={() => change(r, "cancel")} disabled={act.busy}>Cancel</button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
              <EmptyRow show={!records.loading && (records.data ?? []).length === 0} cols={5} text="Nothing to show." />
            </tbody>
          </table>
        </div>
      </div>
      <div className="card">
        <h2>Medicine stock</h2>
        <Loading show={meds.loading} />
        <ErrorBox message={meds.error} />
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table>
            <thead><tr><th>Medicine</th><th>Used for</th><th>In stock</th><th>Reorder at</th><th>Expiry date</th><th>Notes</th><th>Add stock</th></tr></thead>
            <tbody>
              {(meds.data ?? []).map((m) => (
                <tr key={m.id}>
                  <td>{m.name}</td><td>{m.treats ?? ""}</td><td>{m.stock} {m.unit ?? ""}</td><td>{m.reorder_level}</td>
                  <td>{m.expiry_date ? fmtDate(m.expiry_date) : "Not set"}</td>
                  <td>{m.expired && <Badge value="expired" />} {m.low_stock && <Badge value="low" />}</td>
                  <td>
                    <div className="inline">
                      <input type="number" min={1} aria-label={`Quantity to add for ${m.name}`} value={amounts[m.id] ?? ""} onChange={(e) => setAmounts({ ...amounts, [m.id]: e.target.value })} style={{ width: 90 }} />
                      <button className="small secondary" onClick={() => restock(m)} disabled={act.busy}>Add</button>
                    </div>
                  </td>
                </tr>
              ))}
              <EmptyRow show={!meds.loading && (meds.data ?? []).length === 0} cols={7} text="No medicines have been added yet." />
            </tbody>
          </table>
        </div>
      </div>
      <form className="card" onSubmit={add}>
        <h2>Add a medicine</h2>
        <div className="form-grid" style={{ marginTop: 12 }}>
          <div className="field"><label>Name</label><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></div>
          <div className="field"><label>Unit</label><input value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} placeholder="tablet" /></div>
          <div className="field"><label>Starting stock</label><input type="number" min={0} value={form.stock} onChange={(e) => setForm({ ...form, stock: e.target.value })} /></div>
          <div className="field"><label>Reorder level</label><input type="number" min={0} value={form.reorder_level} onChange={(e) => setForm({ ...form, reorder_level: e.target.value })} /></div>
          <div className="field"><label>Expiry date</label><input type="date" value={form.expiry_date} onChange={(e) => setForm({ ...form, expiry_date: e.target.value })} /></div>
          <div className="field"><label>Used for (symptoms, separated by commas)</label><input value={form.treats} onChange={(e) => setForm({ ...form, treats: e.target.value })} placeholder="headache, fever" /></div>
        </div>
        <div className="actions"><button type="submit" disabled={act.busy}>Add medicine</button></div>
      </form>
    </>
  );
}
