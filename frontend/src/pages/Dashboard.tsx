import { Link } from "react-router-dom";
import { api, Inquiry, Medicine, Student } from "../api";
import { EmptyRow, ErrorBox, fmtDateTime, Loading, PageHeader, useLoad } from "../ui";

interface Summary { sent: number; failed: number; pending: number }

export default function Dashboard() {
  const waiting = useLoad(() => api<Inquiry[]>("/api/inquiries?status=pending&limit=200"), []);
  const ready = useLoad(() => api<Inquiry[]>("/api/inquiries?status=ready&limit=200"), []);
  const students = useLoad(() => api<Student[]>("/api/students?limit=200"), []);
  const medicines = useLoad(() => api<Medicine[]>("/api/medicines?limit=500"), []);
  const notices = useLoad(() => api<Summary>("/api/notifications/summary"), []);
  const error = waiting.error || ready.error || students.error || medicines.error || notices.error;
  const loading = waiting.loading || ready.loading || students.loading || medicines.loading || notices.loading;
  const attention = (medicines.data ?? []).filter((m) => m.low_stock || m.expired).length;
  const studentName = (id: string) => students.data?.find((s) => s.id === id)?.full_name ?? "Unknown student";

  return (
    <>
      <PageHeader title="Dashboard" subtitle="What needs attention in the clinic today." />
      <Loading show={loading} />
      <ErrorBox message={error} />
      <div className="stats">
        <div className="stat"><b>{waiting.data?.length ?? "-"}</b><span>Inquiries waiting for a reply</span></div>
        <div className="stat"><b>{ready.data?.length ?? "-"}</b><span>Medicine ready for pick-up</span></div>
        <div className="stat"><b>{medicines.data ? attention : "-"}</b><span>Medicines low or expired</span></div>
        <div className="stat"><b>{notices.data?.failed ?? "-"}</b><span>Failed notifications</span></div>
      </div>
      <div className="card">
        <h2>Inquiries waiting for a reply</h2>
        <p className="sub">Check the stock and reply with a pick-up date. <Link to="/inquiries">Go to medicine inquiries</Link></p>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Received</th><th>Student</th><th>Symptoms</th></tr></thead>
            <tbody>
              {(waiting.data ?? []).slice(0, 8).map((i) => (
                <tr key={i.id}><td>{fmtDateTime(i.created_at)}</td><td>{studentName(i.student_id)}</td><td>{i.symptoms.join(", ")}</td></tr>
              ))}
              <EmptyRow show={!loading && (waiting.data ?? []).length === 0} cols={3} text="No inquiries are waiting." />
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
