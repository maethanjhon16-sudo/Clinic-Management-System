import { useParams } from "react-router-dom";
import { api, VerifyResult } from "../api";
import { fmtDate, fmtDateTime, useLoad } from "../ui";

export default function Verify() {
  const { token } = useParams();
  const result = useLoad(() => api<VerifyResult>(`/api/excuses/verify/${token}`, undefined, false), [token]);
  const data = result.data;

  return (
    <div className="auth-page">
      <div className="auth-card">
        <header>
          <h1>Medical excuse verification</h1>
          <p>School Clinic Management System</p>
        </header>
        {result.loading && <div className="body"><p className="muted">Checking this excuse slip. This can take up to a minute.</p></div>}
        {!result.loading && result.error && (
          <div className="verify bad">
            <div className="mark">&#10005;</div>
            <h1>Not verified</h1>
            <p className="muted">{result.error}</p>
          </div>
        )}
        {data && (
          <div className={`verify ${data.is_valid ? "good" : "bad"}`}>
            <div className="mark">{data.is_valid ? "\u2713" : "!"}</div>
            <h1>{data.is_valid ? "Valid medical excuse" : data.status === "expired" ? "Expired medical excuse" : "Revoked medical excuse"}</h1>
            <p className="muted">{data.message}</p>
            <dl>
              {data.student_name && (<><dt>Student</dt><dd>{data.student_name}</dd></>)}
              {data.student_number && (<><dt>Student number</dt><dd>{data.student_number}</dd></>)}
              <dt>Valid from</dt><dd>{fmtDate(data.valid_from)}</dd>
              <dt>Valid until</dt><dd>{fmtDate(data.valid_until)}</dd>
              <dt>Issued</dt><dd>{fmtDateTime(data.issued_at)}</dd>
            </dl>
            <p className="muted" style={{ marginTop: 18 }}>Issued by the school clinic. No medical details are shown.</p>
          </div>
        )}
      </div>
    </div>
  );
}
