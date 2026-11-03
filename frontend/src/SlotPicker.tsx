import { useState } from "react";
import { api, Availability } from "./api";
import { todayManila, useLoad } from "./ui";

interface Props {
  value: string;                    // the chosen time as an ISO string, or ""
  onChange: (iso: string) => void;
}

export default function SlotPicker({ value, onChange }: Props) {
  const [day, setDay] = useState("");
  const info = useLoad<Availability | null>(
    () => (day ? api<Availability>(`/api/appointments/availability?date=${day}`) : Promise.resolve(null)),
    [day]
  );

  return (
    <div>
      <div className="field" style={{ maxWidth: 240 }}>
        <label>Date</label>
        <input type="date" min={todayManila()} value={day} onChange={(e) => { setDay(e.target.value); onChange(""); }} />
      </div>
      {day && info.loading && <p className="muted">Checking available times...</p>}
      {info.error && <div className="alert error">{info.error}</div>}
      {info.data?.closed && <div className="alert info">{info.data.message}</div>}
      {info.data && !info.data.closed && (
        <div style={{ marginTop: 14 }}>
          <label>Available times (Philippine time)</label>
          <div className="slots">
            {info.data.slots.map((s) => (
              <button
                type="button"
                key={s.start}
                disabled={!s.available}
                className={"slot" + (value === s.start ? " selected" : "")}
                onClick={() => onChange(s.start)}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
