import { api, Appointment, Slip } from "../api";
import { Badge, ErrorBox, fmtDate, fmtDateTime, Loading, useLoad } from "../ui";

export default function MyRecords() {
  const appts = useLoad(() => api<Appointment[]>("/api/appointments?limit=100"), []);
  const slips = useLoad(() => api<Slip[]>("/api/excuses?limit=100"), []);

  return (
    <>
      <h2>My records</h2>
      <div className="card">
        <h3>My appointments</h3>
        <Loading show={appts.loading} />
        <ErrorBox message={appts.error} />
        <div className="scroll">
          <table>
            <thead><tr><th>When</th><th>Reason</th><th>Status</th></tr></thead>
            <tbody>
              {(appts.data ?? []).map((a) => (
                <tr key={a.id}><td>{fmtDateTime(a.scheduled_at)}</td><td>{a.reason ?? ""}</td><td><Badge value={a.status} /></td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="card">
        <h3>My excuse slips</h3>
        <Loading show={slips.loading} />
        <ErrorBox message={slips.error} />
        <div className="scroll">
          <table>
            <thead><tr><th>Valid</th><th>Status</th><th>Verification link</th></tr></thead>
            <tbody>
              {(slips.data ?? []).map((s) => {
                const link = `${window.location.origin}${window.location.pathname}#/verify/${s.token}`;
                return (
                  <tr key={s.id}>
                    <td>{fmtDate(s.valid_from)} to {fmtDate(s.valid_until)}</td>
                    <td><Badge value={s.effective_status} /></td>
                    <td><a href={link} target="_blank" rel="noreferrer">Open</a></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
