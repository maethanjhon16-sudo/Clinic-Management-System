import { FormEvent, useState } from "react";
import { api, Inquiry, patch, post, Slip } from "../api";
import { Badge, EmptyRow, ErrorBox, fmtDate, fmtDateTime, Loading, OkBox, PageHeader, useAction, useLoad } from "../ui";

const SYMPTOMS = ["headache", "cough", "runny nose", "fever", "sore throat", "stomach ache", "body pain", "allergy"];

function answer(i: Inquiry): string {
  switch (i.status) {
    case "pending": return "Waiting for the nurse to check the stock.";
    case "ready": return `Available. Pick-up date: ${i.pickup_date ? fmtDate(i.pickup_date) : ""}${i.medicine_name ? ` (${i.medicine_name} x${i.quantity})` : ""}.`;
    case "unavailable": return "The medicine is not available right now.";
    case "collected": return "You have collected the medicine.";
    default: return "Cancelled.";
  }
}

export default function MyRecords() {
  const [picked, setPicked] = useState<string[]>([]);
  const [details, setDetails] = useState("");
  const inquiries = useLoad(() => api<Inquiry[]>("/api/inquiries?limit=100"), []);
  const slips = useLoad(() => api<Slip[]>("/api/excuses?limit=100"), []);
  const send = useAction();
  const cancel = useAction();

  const toggle = (s: string) => setPicked(picked.includes(s) ? picked.filter((x) => x !== s) : [...picked, s]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const ok = await send.run(async () => {
      if (picked.length === 0) throw new Error("Please choose at least one symptom.");
      await post<Inquiry>("/api/inquiries", { symptoms: picked, details: details.trim() || null });
    }, "Your inquiry was sent. The nurse will check the stock and reply with a pick-up date by email.");
    if (ok) { setPicked([]); setDetails(""); inquiries.reload(); }
  }

  async function cancelInquiry(i: Inquiry) {
    if (!window.confirm("Cancel this inquiry?")) return;
    if (await cancel.run(() => patch(`/api/inquiries/${i.id}/cancel`), "Your inquiry was cancelled.")) inquiries.reload();
  }

  return (
    <>
      <PageHeader title="Medicine inquiry" subtitle="Ask the clinic nurse whether a medicine for how you feel is available." />
      <form className="card" onSubmit={submit}>
        <h2>Send an inquiry</h2>
        <p className="sub">Choose what you are feeling. The nurse will check the stock and tell you the date you can pick it up. You can have up to three open inquiries.</p>
        <label>What are you feeling?</label>
        <div className="checks">
          {SYMPTOMS.map((s) => (
            <label key={s}><input type="checkbox" checked={picked.includes(s)} onChange={() => toggle(s)} />{s.charAt(0).toUpperCase() + s.slice(1)}</label>
          ))}
        </div>
        <div className="field" style={{ marginTop: 18, maxWidth: 620 }}>
          <label>Anything else the nurse should know (optional)</label>
          <textarea value={details} onChange={(e) => setDetails(e.target.value)} maxLength={500} placeholder="For example: since yesterday, mild" />
        </div>
        <div className="actions"><button type="submit" disabled={send.busy}>{send.busy ? "Sending..." : "Send inquiry"}</button></div>
        <ErrorBox message={send.error} />
        <OkBox message={send.notice} />
      </form>
      <div className="card">
        <h2>My inquiries</h2>
        <ErrorBox message={cancel.error} />
        <OkBox message={cancel.notice} />
        <Loading show={inquiries.loading} />
        <ErrorBox message={inquiries.error} />
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table>
            <thead><tr><th>Sent</th><th>Symptoms</th><th>Status</th><th>Reply</th><th></th></tr></thead>
            <tbody>
              {(inquiries.data ?? []).map((i) => (
                <tr key={i.id}>
                  <td>{fmtDateTime(i.created_at)}</td><td>{i.symptoms.join(", ")}</td><td><Badge value={i.status} /></td>
                  <td>{answer(i)}{i.response_note && <div className="muted">Note from the nurse: {i.response_note}</div>}</td>
                  <td>{(i.status === "pending" || i.status === "ready") && <button className="small danger" onClick={() => cancelInquiry(i)} disabled={cancel.busy}>Cancel</button>}</td>
                </tr>
              ))}
              <EmptyRow show={!inquiries.loading && (inquiries.data ?? []).length === 0} cols={5} text="You have not sent any inquiries yet." />
            </tbody>
          </table>
        </div>
      </div>
      <div className="card">
        <h2>My excuse slips</h2>
        <Loading show={slips.loading} />
        <ErrorBox message={slips.error} />
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table>
            <thead><tr><th>Valid from</th><th>Valid until</th><th>Status</th><th>Verification page</th></tr></thead>
            <tbody>
              {(slips.data ?? []).map((s) => {
                const link = `${window.location.origin}${window.location.pathname}#/verify/${s.token}`;
                return (
                  <tr key={s.id}>
                    <td>{fmtDate(s.valid_from)}</td><td>{fmtDate(s.valid_until)}</td>
                    <td><Badge value={s.effective_status} /></td>
                    <td><a href={link} target="_blank" rel="noreferrer">Open</a></td>
                  </tr>
                );
              })}
              <EmptyRow show={!slips.loading && (slips.data ?? []).length === 0} cols={4} text="You have no excuse slips." />
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
