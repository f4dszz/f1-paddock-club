import { useCallback, useEffect, useState } from "react";

export default function SavedTrips({ ws, onLoad, onClose }) {
  const [trips, setTrips] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!ws) {
      setError("Not connected. Start a plan first.");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    const onMsg = (e) => {
      let m;
      try {
        m = JSON.parse(e.data);
      } catch {
        return;
      }
      if (m.type === "trips_list") {
        setTrips(m.data?.trips || []);
        setLoading(false);
      } else if (m.type === "trip_loaded") {
        onLoad?.(m.data);
      } else if (m.type === "delete_trip_ack") {
        // Refresh the list after a delete completes.
        ws.send(JSON.stringify({ type: "list_trips", data: {} }));
      } else if (m.type === "error") {
        // Only surface errors that look related to trips.
        if (typeof m.data === "string" && /trip/i.test(m.data)) {
          setError(m.data);
          setLoading(false);
        }
      }
    };
    ws.addEventListener("message", onMsg);
    const requestList = () => {
      try {
        ws.send(JSON.stringify({ type: "list_trips", data: {} }));
      } catch (e) {
        setError("Connection not open yet.");
        setLoading(false);
      }
    };
    if (ws.readyState === WebSocket.OPEN) {
      requestList();
    } else if (ws.readyState === WebSocket.CONNECTING) {
      ws.addEventListener("open", requestList, { once: true });
    } else {
      setError("Connection closed.");
      setLoading(false);
    }
    return () => {
      ws.removeEventListener("message", onMsg);
      ws.removeEventListener("open", requestList);
    };
  }, [ws, onLoad]);

  const loadTrip = useCallback(
    (id) => {
      if (!ws) return;
      ws.send(JSON.stringify({ type: "load_trip", data: { id } }));
    },
    [ws]
  );

  const deleteTrip = useCallback(
    (id) => {
      if (!ws) return;
      if (!window.confirm("Delete this saved trip?")) return;
      ws.send(JSON.stringify({ type: "delete_trip", data: { id } }));
    },
    [ws]
  );

  return (
    <div
      data-testid="saved-trips-panel"
      style={{
        position: "fixed",
        top: 0,
        right: 0,
        bottom: 0,
        width: 320,
        background: "#0e1428",
        color: "#e6ecff",
        padding: 16,
        boxShadow: "-8px 0 24px rgba(0,0,0,0.5)",
        overflowY: "auto",
        zIndex: 50,
        fontSize: 11,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <strong style={{ fontSize: 13 }}>My Trips</strong>
        <button
          data-testid="saved-trips-close"
          onClick={onClose}
          style={{ background: "transparent", color: "#e6ecff", border: "1px solid #2a3358", borderRadius: 4, padding: "2px 8px", cursor: "pointer" }}
        >
          ×
        </button>
      </div>

      {loading && <div>Loading…</div>}
      {error && (
        <div data-testid="saved-trips-error" style={{ color: "salmon", marginBottom: 8 }}>
          {error}
        </div>
      )}
      {!loading && trips.length === 0 && !error && (
        <div data-testid="saved-trips-empty" style={{ opacity: 0.7 }}>
          No saved trips yet.
        </div>
      )}

      {trips.map((t) => (
        <div
          key={t.id}
          data-testid="saved-trip-item"
          style={{
            border: "1px solid #2a3358",
            borderRadius: 6,
            padding: 10,
            marginBottom: 8,
            background: "#0a1224",
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 2 }}>{t.gp_slug}</div>
          <div style={{ fontSize: 10, opacity: 0.7, marginBottom: 4 }}>
            {t.depart_date || "—"} → {t.return_date || "—"}
          </div>
          {t.budget_total != null && (
            <div style={{ fontSize: 10, opacity: 0.7, marginBottom: 6 }}>
              Budget: {t.budget_total} {t.currency || ""}
            </div>
          )}
          <div style={{ display: "flex", gap: 6 }}>
            <button
              data-testid="saved-trip-load"
              onClick={() => loadTrip(t.id)}
              style={{ flex: 1, background: "#1d4ed8", color: "white", border: "none", borderRadius: 4, padding: "4px 8px", cursor: "pointer" }}
            >
              Load
            </button>
            <button
              data-testid="saved-trip-delete"
              onClick={() => deleteTrip(t.id)}
              style={{ background: "transparent", color: "#fca5a5", border: "1px solid #7f1d1d", borderRadius: 4, padding: "4px 8px", cursor: "pointer" }}
            >
              Delete
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
