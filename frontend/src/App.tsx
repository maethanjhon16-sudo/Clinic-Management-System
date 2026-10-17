import { Navigate, NavLink, Outlet, Route, Routes } from "react-router-dom";
import { Role } from "./api";
import { useAuth } from "./auth";
import Appointments from "./pages/Appointments";
import Consultations from "./pages/Consultations";
import Dashboard from "./pages/Dashboard";
import Excuses from "./pages/Excuses";
import Login from "./pages/Login";
import MyRecords from "./pages/MyRecords";
import Notifications from "./pages/Notifications";
import Pharmacy from "./pages/Pharmacy";
import Students from "./pages/Students";
import Users from "./pages/Users";
import Verify from "./pages/Verify";

const STAFF: Role[] = ["admin", "doctor", "nurse"];
const NAV: { to: string; label: string; roles: Role[]; end?: boolean }[] = [
  { to: "/", label: "Dashboard", roles: STAFF, end: true },
  { to: "/students", label: "Students", roles: STAFF },
  { to: "/appointments", label: "Appointments", roles: STAFF },
  { to: "/consultations", label: "Consultations", roles: STAFF },
  { to: "/pharmacy", label: "Pharmacy", roles: STAFF },
  { to: "/excuses", label: "Excuse slips", roles: STAFF },
  { to: "/notifications", label: "Notifications", roles: STAFF },
  { to: "/users", label: "Users", roles: ["admin"] },
  { to: "/my-records", label: "My records", roles: ["student"] },
];

function Layout() {
  const { user, logout } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  return (
    <div className="shell">
      <nav className="side">
        <h1>School Clinic</h1>
        {NAV.filter((n) => n.roles.includes(user.role)).map((n) => (
          <NavLink key={n.to} to={n.to} end={n.end}>{n.label}</NavLink>
        ))}
        <div className="me">
          {user.full_name} ({user.role})<br />
          <a href="#/login" onClick={(e) => { e.preventDefault(); logout(); }}>Sign out</a>
        </div>
      </nav>
      <main className="main"><Outlet /></main>
    </div>
  );
}

function Home() {
  const { user } = useAuth();
  return user?.role === "student" ? <Navigate to="/my-records" replace /> : <Dashboard />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/verify/:token" element={<Verify />} />
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="students" element={<Students />} />
        <Route path="appointments" element={<Appointments />} />
        <Route path="consultations" element={<Consultations />} />
        <Route path="pharmacy" element={<Pharmacy />} />
        <Route path="excuses" element={<Excuses />} />
        <Route path="notifications" element={<Notifications />} />
        <Route path="users" element={<Users />} />
        <Route path="my-records" element={<MyRecords />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
