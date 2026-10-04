import { useEffect, useState } from "react";

type Student = { id: string; student_number: string; full_name: string; email: string };

const API = import.meta.env.VITE_API_URL;

export default function App() {
  const [students, setStudents] = useState<Student[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API}/api/students`)
      .then((r) => (r.ok ? r.json() : Promise.reject(`Error ${r.status}`)))
      .then(setStudents)
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <div style={{ padding: 24, fontFamily: "sans-serif" }}>
      <h1>School Clinic System</h1>
      {error && <p style={{ color: "crimson" }}>Could not load students: {error}</p>}
      <ul>
        {students.map((s) => (
          <li key={s.id}>{s.student_number} - {s.full_name} ({s.email})</li>
        ))}
      </ul>
    </div>
  );
}