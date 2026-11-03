import { useState } from "react";
import { Link } from "react-router-dom";
import { api, Instructor, post, Slip } from "./api";
import { ErrorBox, Loading, OkBox, useAction, useLoad } from "./ui";

// Pick the student's instructors from the school's list and send them the excuse slip.
export default function InstructorPicker({ slipId }: { slipId: string }) {
  const slip = useLoad(() => api<Slip>(`/api/excuses/${slipId}`), [slipId]);
  const list = useLoad(() => api<Instructor[]>("/api/instructors?limit=500"), []);
  const [q, setQ] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const act = useAction();

  const informed = new Set((slip.data?.recipients ?? []).map((r) => r.instructor_email.toLowerCase()));
  const shown = (list.data ?? []).filter((i) =>
    `${i.full_name} ${i.email} ${i.department ?? ""}`.toLowerCase().includes(q.toLowerCase())
  );
  const toggle = (id: string) => setChosen(chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id]);
  const revoked = slip.data?.status === "revoked";

  async function send() {
    const ok = await act.run(async () => {
      if (chosen.length === 0) throw new Error("Please select at least one instructor.");
      await post<Slip>(`/api/excuses/${slipId}/notify-instructors`, { instructor_ids: chosen });
    }, "The excuse slip was sent to the selected instructors.");
    if (ok) { setChosen([]); slip.reload(); }
  }

  if (list.data && list.data.length === 0) {
    return <p className="muted">No instructors have been added yet. Add them once on the <Link to="/instructors">Instructors</Link> page.</p>;
  }
  return (
    <div>
      <Loading show={list.loading} />
      <ErrorBox message={list.error || slip.error} />
      <div className="field" style={{ maxWidth: 360 }}>
        <label>Search instructors</label>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, email or department" />
      </div>
      <div className="picker">
        {shown.map((i) => (
          <label key={i.id}>
            <input type="checkbox" checked={chosen.includes(i.id)} onChange={() => toggle(i.id)} disabled={informed.has(i.email.toLowerCase())} />
            <span>{i.full_name} <small>{i.email}{i.department ? ` \u00b7 ${i.department}` : ""}</small></span>
            {informed.has(i.email.toLowerCase()) && <span className="badge b-sent done">Sent</span>}
          </label>
        ))}
        {list.data && shown.length === 0 && <p className="muted" style={{ margin: "8px 0" }}>No instructors match your search.</p>}
      </div>
      <div className="actions" style={{ marginTop: 0 }}>
        <button onClick={send} disabled={act.busy || revoked || chosen.length === 0}>Send slip to selected instructors</button>
      </div>
      {revoked && <p className="muted">This slip was revoked and can no longer be sent.</p>}
      <ErrorBox message={act.error} />
      <OkBox message={act.notice} />
    </div>
  );
}
