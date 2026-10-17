import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { ErrorBox, useAction } from "../ui";

export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const act = useAction();

  useEffect(() => {
    if (user) navigate("/", { replace: true });
  }, [user, navigate]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    await act.run(() => login(email, password));
  }

  return (
    <div className="center">
      <form className="login" onSubmit={submit}>
        <div className="card">
          <h2>School Clinic System</h2>
          <label>Email</label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
          <label>Password</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          <ErrorBox message={act.error} />
          <button type="submit" disabled={act.busy} style={{ width: "100%" }}>
            {act.busy ? "Signing in..." : "Sign in"}
          </button>
          {act.busy && <p className="muted">The first sign-in can take up to a minute while the server wakes up.</p>}
        </div>
      </form>
    </div>
  );
}
