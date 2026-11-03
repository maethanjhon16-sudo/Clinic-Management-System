import { useState } from "react";
import { Navigate, NavLink, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { Role } from "./api";
import { useAuth } from "./auth";
import Appointments from "./pages/Appointments";
import Consultations from "./pages/Consultations";
import Dashboard from "./pages/Dashboard";
import Excuses from "./pages/Excuses";
import Inquiries from "./pages/Inquiries";
import Instructors from "./pages/Instructors";
import Login from "./pages/Login";
import MyRecords from "./pages/MyRecords";
import Notifications from "./pages/Notifications";
import Pharmacy from "./pages/Pharmacy";
import Students from "./pages/Students";
import Users from "./pages/Users";
import Verify from "./pages/Verify";
import { roleLabel } from "./ui";

const STAFF: Role[] = ["admin", "nurse"];
const NAV: { to: string; label: string; roles: Role[]; end?: boolean }[] = [
  { to: "/", label: "Dashboard", roles: STAFF, end: true },
  { to: "/inquiries", label: "Medicine inquiries", roles: STAFF },
  { to: "/excuses", label: "Excuse slips", roles: STAFF },
  { to: "/instructors", label: "Instructors", roles: STAFF },
  { to: "/pharmacy", label: "Pharmacy stock", roles: STAFF },
  { to: "/students", label: "Students", roles: STAFF },
  { to: "/notifications", label: "Notifications", roles: STAFF },
  { to: "/users", label: "User accounts", roles: ["admin"] },
  { to: "/my-records", label: "Medicine inquiry", roles: ["student"] },
];
// Optional pages, kept out of the way until the nurse opens this group.
const VISITS = [
  { to: "/appointments", label: "Appointments" },
  { to: "/consultations", label: "Consultations" },
];

function Layout() {
  const { user, logout } = useAuth();
  const { pathname } = useLocation();
  const [openVisits, setOpenVisits] = useState(false);
  if (!user) return <Navigate to="/login" replace />;
  const onVisitPage = VISITS.some((v) => pathname.startsWith(v.to));
  const visitsOpen = openVisits || onVisitPage;
  return (
    <>
      <header className="topbar">
        <div className="brand">
          School Clinic Management System
          <small>Health services</small>
        </div>
        <div className="user">
          <span>{user.full_name} <small>({roleLabel(user.role)})</small></span>
          <button onClick={() => logout()}>Sign out</button>
        </div>
      </header>
      <div className="shell">
        <nav className="side">
          {NAV.filter((n) => n.roles.includes(user.role)).map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end}>{n.label}</NavLink>
          ))}
          {user.role !== "student" && (
            <>
              <button className="side-toggle" aria-expanded={visitsOpen} onClick={() => setOpenVisits(!openVisits)}>
                Scheduled visits {visitsOpen ? "\u2212" : "+"}
              </button>
              {visitsOpen && VISITS.map((v) => <NavLink key={v.to} to={v.to} className="sub">{v.label}</NavLink>)}
            </>
          )}
        </nav>
        <main className="main"><Outlet /></main>
      </div>
    </>
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
        <Route path="inquiries" element={<Inquiries />} />
        <Route path="excuses" element={<Excuses />} />
        <Route path="instructors" element={<Instructors />} />
        <Route path="pharmacy" element={<Pharmacy />} />
        <Route path="students" element={<Students />} />
        <Route path="notifications" element={<Notifications />} />
        <Route path="users" element={<Users />} />
        <Route path="appointments" element={<Appointments />} />
        <Route path="consultations" element={<Consultations />} />
        <Route path="my-records" element={<MyRecords />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
