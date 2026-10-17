import { api, Appointment, Medicine, Student } from "../api";
import { ErrorBox, Loading, useLoad } from "../ui";

interface Summary { sent: number; failed: number; pending: number }

export default function Dashboard() {
  const students = useLoad(() => api<Student[]>("/api/students?limit=200"), []);
  const scheduled = useLoad(() => api<Appointment[]>("/api/appointments?status=scheduled&limit=200"), []);
  const medicines = useLoad(() => api<Medicine[]>("/api/medicines?limit=500"), []);
  const notices = useLoad(() => api<Summary>("/api/notifications/summary"), []);
  const error = students.error || scheduled.error || medicines.error || notices.error;
  const loading = students.loading || scheduled.loading || medicines.loading || notices.loading;
  const lowStock = (medicines.data ?? []).filter((m) => m.low_stock || m.expired).length;

  return (
    <>
      <h2>Dashboard</h2>
      <Loading show={loading} />
      <ErrorBox message={error} />
      <div className="grid">
        <div className="stat"><b>{students.data?.length ?? "-"}</b><span>Active students</span></div>
        <div className="stat"><b>{scheduled.data?.length ?? "-"}</b><span>Upcoming appointments</span></div>
        <div className="stat"><b>{medicines.data ? lowStock : "-"}</b><span>Medicines low or expired</span></div>
        <div className="stat"><b>{notices.data?.failed ?? "-"}</b><span>Failed notifications</span></div>
      </div>
    </>
  );
}
