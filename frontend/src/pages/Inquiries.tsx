import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Inquiry, Medicine, patch, post, Student } from "../api";
import InstructorPicker from "../InstructorPicker";
import { Badge, EmptyRow, ErrorBox, fmtDate, fmtDateTime, Loading, OkBox, PageHeader, todayManila, useAction, useLoad } from "../ui";

const EMPTY = { medicine_id: "", quantity: "1", pickup_date: "", note: "" };

export default function Inquiries() {
  const [status, setStatus] = useState("pending");
  const [selectedId, setSelectedId] = useState("");
  const [form, setForm] = useState(EMPTY);
  const [outcome, setOutcome] = useState<"fit" | "not_fit">("fit");
  const [restDays, setRestDays] = useState("1");
  const list = useLoad(() => api<Inquiry[]>(`/api/inquiries?limit=100${status ? `&status=${status}` : ""}`), [status]);
  const detail = useLoad<Inquiry | null>(() => (selectedId ? api<Inquiry>(`/api/inquiries/${selectedId}`) : Promise.resolve(null)), [selectedId]);
  const students = useLoad(() => api<Student[]>("/api/students?limit=200"), []);
  const meds = useLoad(() => api<Medicine[]>("/api/medicines?limit=500"), []);
  const act = useAction();

  const selected = detail.data && detail.data.id === selectedId ? detail.data : null;
  const studentName = (id: string) => students.data?.find((s) => s.id === id)?.full_name ?? "Unknown student";
  const suggestedIds = new Set((selected?.suggestions ?? []).map((s) => s.medicine_id));
  const inStock = (meds.data ?? []).filter((m) => m.stock > 0 && !m.expired);

  // While the excuse slip is being created in the background, check again every few seconds.
  const waitingForSlip = !!selected && selected.status === "collected" && selected.fit_for_class === false
    && !selected.excuse_slip_id && !selected.excuse_error;
  useEffect(() => {
    if (!waitingForSlip) return;
    const timer = setTimeout(() => detail.reload(), 4000);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [waitingForSlip, detail.data]);

  function open(i: Inquiry) {
    setSelectedId(i.id);
    setForm({ ...EMPTY, medicine_id: i.suggestions[0]?.medicine_id ?? "" });
    setOutcome("fit");
    setRestDays("1");
  }

  function refresh() { list.reload(); meds.reload(); detail.reload(); }

  async function respond(isAvailable: boolean) {
    if (!selected) return;
    const ok = await act.run(async () => {
      if (isAvailable && !form.medicine_id) throw new Error("Please select the medicine.");
      if (isAvailable && !form.pickup_date) throw new Error("Please choose the pick-up date.");
      await post<Inquiry>(`/api/inquiries/${selected.id}/respond`, {
        available: isAvailable,
        medicine_id: isAvailable ? form.medicine_id : null,
        quantity: isAvailable ? Number(form.quantity) : null,
        pickup_date: isAvailable ? form.pickup_date : null,
        note: form.note || null,
      });
    }, isAvailable ? "The pick-up date was sent to the student and the medicine was set aside." : "The student was told that the medicine is not available.");
    if (ok) refresh();
  }

  async function collect() {
    if (!selected) return;
    const notFit = outcome === "not_fit";
    const ok = await act.run(
      () => post<Inquiry>(`/api/inquiries/${selected.id}/collect`, { fit_for_class: !notFit, rest_days: notFit ? Number(restDays) : null }),
      notFit ? "Pick-up recorded. The excuse slip is being created." : "Pick-up recorded."
    );
    if (ok) refresh();
  }

  async function retryExcuse() {
    if (!selected) return;
    if (await act.run(() => post<Inquiry>(`/api/inquiries/${selected.id}/issue-excuse`), "Trying again to create the excuse slip.")) detail.reload();
  }

  async function cancel() {
    if (!selected || !window.confirm("Cancel this inquiry? Any medicine set aside will return to stock.")) return;
    if (await act.run(() => patch<Inquiry>(`/api/inquiries/${selected.id}/cancel`), "The inquiry was cancelled.")) refresh();
  }

  return (
    <>
      <PageHeader title="Medicine inquiries" subtitle="Students ask whether a medicine is available. Check the stock, reply with a pick-up date, and record the pick-up." />
      <ErrorBox message={act.error} />
      <OkBox message={act.notice} />
      <div className="card">
        <div className="inline" style={{ marginBottom: 16 }}>
          <div className="field" style={{ minWidth: 220 }}>
            <label>Status</label>
            <select value={status} onChange={(e) => { setStatus(e.target.value); setSelectedId(""); }}>
              <option value="pending">Waiting for a reply</option><option value="ready">Ready for pick-up</option>
              <option value="collected">Collected</option><option value="unavailable">Not available</option>
              <option value="cancelled">Cancelled</option><option value="">All</option>
            </select>
          </div>
        </div>
        <Loading show={list.loading} />
        <ErrorBox message={list.error} />
        <div className="table-wrap">
          <table>
            <thead><tr><th>Received</th><th>Student</th><th>Symptoms</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {(list.data ?? []).map((i) => (
                <tr key={i.id}>
                  <td>{fmtDateTime(i.created_at)}</td><td>{studentName(i.student_id)}</td>
                  <td>{i.symptoms.join(", ")}</td><td><Badge value={i.status} /></td>
                  <td><button className="small secondary" onClick={() => open(i)}>Open</button></td>
                </tr>
              ))}
              <EmptyRow show={!list.loading && (list.data ?? []).length === 0} cols={5} text="No inquiries to show." />
            </tbody>
          </table>
        </div>
      </div>

      {selectedId && !selected && <Loading show={detail.loading} />}
      <ErrorBox message={detail.error} />
      {selected && (
        <div className="card">
          <h2>{studentName(selected.student_id)} <Badge value={selected.status} /></h2>
          <p className="sub">Received {fmtDateTime(selected.created_at)}</p>
          <p><b>Symptoms:</b> {selected.symptoms.join(", ")}</p>
          {selected.details && <p><b>Details:</b> {selected.details}</p>}

          {selected.status === "pending" && (
            <>
              <div className="suggest" style={{ margin: "14px 0 18px" }}>
                {selected.suggestions.length > 0
                  ? <>In stock for these symptoms: {selected.suggestions.map((s) => `${s.name} (${s.stock} ${s.unit ?? ""})`).join("; ")}.</>
                  : <>No medicine currently in stock is listed for these symptoms. You can still choose a medicine below or reply that it is not available.</>}
              </div>
              <div className="form-grid">
                <div className="field">
                  <label>Medicine</label>
                  <select value={form.medicine_id} onChange={(e) => setForm({ ...form, medicine_id: e.target.value })}>
                    <option value="">Select a medicine</option>
                    {inStock.filter((m) => suggestedIds.has(m.id)).length > 0 && (
                      <optgroup label="Suggested for these symptoms">
                        {inStock.filter((m) => suggestedIds.has(m.id)).map((m) => <option key={m.id} value={m.id}>{m.name} (stock {m.stock})</option>)}
                      </optgroup>
                    )}
                    <optgroup label="Other medicines in stock">
                      {inStock.filter((m) => !suggestedIds.has(m.id)).map((m) => <option key={m.id} value={m.id}>{m.name} (stock {m.stock})</option>)}
                    </optgroup>
                  </select>
                </div>
                <div className="field"><label>Quantity</label><input type="number" min={1} value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} /></div>
                <div className="field"><label>Pick-up date</label><input type="date" min={todayManila()} value={form.pickup_date} onChange={(e) => setForm({ ...form, pickup_date: e.target.value })} /></div>
              </div>
              <div className="field" style={{ marginTop: 16 }}>
                <label>Message to the student (optional)</label>
                <textarea value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} placeholder="For example: Please come during clinic hours." />
              </div>
              <div className="actions">
                <button onClick={() => respond(true)} disabled={act.busy}>Medicine is available: send pick-up date</button>
                <button className="danger" onClick={() => respond(false)} disabled={act.busy}>Not available</button>
              </div>
            </>
          )}

          {selected.status === "ready" && (
            <>
              <p><b>Set aside:</b> {selected.medicine_name} x{selected.quantity}</p>
              <p><b>Pick-up date:</b> {selected.pickup_date ? fmtDate(selected.pickup_date) : ""}</p>
              {selected.response_note && <p><b>Message sent:</b> {selected.response_note}</p>}
              <h3 className="section-title">When the student comes for the medicine</h3>
              <p className="sub">After checking the student in person, record whether they can continue their classes.</p>
              <div className="form-grid">
                <div className="field">
                  <label>Student's condition</label>
                  <select value={outcome} onChange={(e) => setOutcome(e.target.value as "fit" | "not_fit")}>
                    <option value="fit">Fit to continue classes</option>
                    <option value="not_fit">Not fit to continue classes (issue an excuse slip)</option>
                  </select>
                </div>
                {outcome === "not_fit" && (
                  <div className="field"><label>Days of rest</label><input type="number" min={1} max={30} value={restDays} onChange={(e) => setRestDays(e.target.value)} /></div>
                )}
              </div>
              <div className="actions">
                <button onClick={collect} disabled={act.busy}>Confirm pick-up</button>
                <button className="danger" onClick={cancel} disabled={act.busy}>Cancel and return to stock</button>
              </div>
            </>
          )}

          {selected.status === "collected" && (
            <>
              {selected.medicine_name && <p><b>Given:</b> {selected.medicine_name} x{selected.quantity}</p>}
              {selected.fit_for_class === true && <p><b>Condition at pick-up:</b> Fit to continue classes.</p>}
              {selected.fit_for_class === false && (
                <>
                  <p><b>Condition at pick-up:</b> Not fit to continue classes. Rest: {selected.rest_days} day(s).</p>
                  {selected.excuse_slip_id ? (
                    <>
                      <div className="alert ok">The excuse slip was issued and the student was notified. <Link to="/excuses">View it under Excuse slips</Link></div>
                      <h3 className="section-title">Send the slip to the student's instructors</h3>
                      <InstructorPicker slipId={selected.excuse_slip_id} />
                    </>
                  ) : selected.excuse_error ? (
                    <div className="alert error">
                      {selected.excuse_error}
                      <div className="actions"><button onClick={retryExcuse} disabled={act.busy}>Try again</button></div>
                    </div>
                  ) : (
                    <p className="muted">The excuse slip is being created. This page updates by itself.</p>
                  )}
                </>
              )}
            </>
          )}

          {(selected.status === "unavailable" || selected.status === "cancelled") && (
            <>
              {selected.response_note && <p><b>Message sent:</b> {selected.response_note}</p>}
              {selected.handled_by_name && <p className="muted">Handled by {selected.handled_by_name}</p>}
            </>
          )}
        </div>
      )}
    </>
  );
}
