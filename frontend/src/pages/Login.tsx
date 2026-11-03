import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { API } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, useAction } from "../ui";

export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState("");
  const act = useAction();

  useEffect(() => {
    if (user) navigate("/", { replace: true });
  }, [user, navigate]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    await act.run(() => login(email, password));
  }

  async function checkStatus() {
    setStatus("Checking the system. This can take up to a minute.");
    try {
      const res = await fetch(`${API}/warmup`);
      const data = (await res.json()) as Record<string, string>;
      const waiting = Object.values(data).filter((v) => v !== "ok").length;
      setStatus(waiting === 0 ? "The system is ready." : "Some services are still starting. Please check again in a moment.");
    } catch {
      setStatus("The system is not responding yet. Please try again shortly.");
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={submit}>
        <header>
          <h1>School Clinic Management System</h1>
          <p>Sign in with your school clinic account</p>
        </header>
        <div className="body">
          <div className="field">
            <label htmlFor="email">Email address</label>
            <input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          <button type="submit" disabled={act.busy}>{act.busy ? "Signing in..." : "Sign in"}</button>
          <ErrorBox message={act.error} />
          {act.busy && <p className="status-line">The first sign-in can take up to a minute while the system starts.</p>}
          <p className="status-line">
            {status || "System status: "}
            {!status && <button type="button" onClick={checkStatus}>Check</button>}
          </p>
        </div>
      </form>
    </div>
  );
}
