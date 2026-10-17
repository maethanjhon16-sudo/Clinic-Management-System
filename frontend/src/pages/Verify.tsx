import { useParams } from "react-router-dom";
import { api, VerifyResult } from "../api";
import { fmtDate, fmtDateTime, useLoad } from "../ui";

export default function Verify() {
  const { token } = useParams();
  const result = useLoad(() => api<VerifyResult>(`/api/excuses/verify/${token}`, undefined, false), [token]);

  return (
    <div className="center">
      {result.loading && <p className="muted">Checking this excuse slip... the first check can take up to a minute.</p>}
      {!result.loading && result.error && (
        <div className="card verify bad">
          <div className="big">&#10060;</div>
          <h2>Not verified</h2>
          <p>{result.error}</p>
        </div>
      )}
      {result.data && (
        <div className={`card verify ${result.data.is_valid ? "good" : "bad"}`}>
          <div className="big">{result.data.is_valid ? "\u2705" : "\u26A0\uFE0F"}</div>
          <h2>{result.data.is_valid ? "Valid medical excuse" : result.data.status === "expired" ? "Expired medical excuse" : "Revoked medical excuse"}</h2>
          <p>{result.data.message}</p>
          {result.data.student_name && <p><b>{result.data.student_name}</b><br />{result.data.student_number}</p>}
          <p>Valid {fmtDate(result.data.valid_from)} to {fmtDate(result.data.valid_until)}</p>
          <p className="muted">Issued {fmtDateTime(result.data.issued_at)} by the school clinic.<br />No medical details are shown.</p>
        </div>
      )}
    </div>
  );
}
