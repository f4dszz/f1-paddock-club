import { FLAGS, HERO_COLORS, SHORT_NAMES, TRACK_MAP } from "../domain/planningConstants.js";
import { PxChar, TrackSVG } from "./PaddockVisuals.jsx";

export function GpSelect({ gpList, onSelectGp, pushDebug, calStatus = "loading", onRetry }) {
  // frontend-completeness-4 — render distinct states for the calendar fetch:
  // a real error+retry on failure, a loading hint while in flight, an empty
  // notice when the backend returns an empty list, instead of one perpetual
  // "is backend running?" string for every outcome.
  const renderStatus = () => {
    if (calStatus === "error") {
      return (
        <div data-testid="calendar-error" role="alert" style={{ gridColumn: "1/-1", textAlign: "center", color: "#ccc", fontSize: 11, padding: 20 }}>
          <div style={{ color: "#EF4444", marginBottom: 8 }}>Couldn&apos;t load the race calendar.</div>
          <div style={{ color: "#666", marginBottom: 12, fontSize: 10 }}>The backend may be unreachable.</div>
          {onRetry && (
            <button
              type="button"
              data-testid="calendar-retry"
              onClick={onRetry}
              style={{ padding: "6px 16px", borderRadius: 6, border: "1px solid #E10600", background: "transparent", color: "#E10600", fontSize: 11, fontWeight: 600, cursor: "pointer" }}
            >
              Retry
            </button>
          )}
        </div>
      );
    }
    if (calStatus === "ready") {
      // ready but empty list
      return (
        <div data-testid="calendar-empty" style={{ gridColumn: "1/-1", textAlign: "center", color: "#555", fontSize: 11, padding: 20 }}>
          No upcoming races available right now.
        </div>
      );
    }
    return (
      <div data-testid="calendar-loading" style={{ gridColumn: "1/-1", textAlign: "center", color: "#555", fontSize: 11, padding: 20 }}>
        Loading calendar…
      </div>
    );
  };

  return (
    <div data-app-root style={{background:"#0a0a0a",minHeight:"100vh",fontFamily:"'DM Sans',sans-serif",color:"#fff",padding:"20px 16px",maxWidth:680,width:"100%",margin:"0 auto"}}>
      <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet"/>
      <div style={{textAlign:"center",marginBottom:20}}>
        <PxChar type="concierge" size={56}/>
        <div style={{fontSize:10,letterSpacing:"0.2em",color:"#555",marginTop:8}}>FORMULA 1</div>
        <div style={{fontSize:22,fontWeight:700}}>PADDOCK CLUB</div>
        <div style={{fontSize:11,color:"#666",marginTop:2}}>Choose your Grand Prix</div>
        <div style={{width:40,height:2,background:"#E10600",margin:"10px auto 0",borderRadius:1}}/>
      </div>
      <div data-gp-grid style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:8}}>
        {(gpList.length ? gpList : []).map((g, i) => {
          const flag = FLAGS[g.country] || "\u{1F3C1}";
          const hero = HERO_COLORS[i % HERO_COLORS.length];
          const track = TRACK_MAP[g.gp_name] || TRACK_MAP["Italian GP"];
          const shortName = SHORT_NAMES[g.gp_name] || g.city;
          const dateStr = g.race_date ? new Date(g.race_date + "T00:00:00").toLocaleDateString("en", {month:"short",day:"numeric"}) : "TBD";
          const selectGp = () => {
            pushDebug("card.click", { gp:g.gp_name, is_past:g.is_past });
            if (!g.is_past) onSelectGp({ ...g, hero, track });
          };
          return (
            <div
              key={g.gp_name}
              data-testid={`gp-card-${g.gp_name.replace(/\s+/g,"-").toLowerCase()}`}
              // a11y (frontend-completeness-6): make the clickable card a
              // keyboard-operable button so non-mouse users can pick a GP.
              role="button"
              tabIndex={g.is_past ? -1 : 0}
              aria-disabled={g.is_past ? true : undefined}
              aria-label={`${shortName} — ${g.is_past ? "concluded" : dateStr}`}
              onClick={selectGp}
              onKeyDown={(e) => {
                if (g.is_past) return;
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectGp(); }
              }}
              style={{
                padding:"12px 8px",borderRadius:10,cursor:g.is_past?"not-allowed":"pointer",background:g.is_past?"#0a0a0a":"#111",border:`1px solid ${g.is_past?"#1a1a1a":"#222"}`,
                display:"flex",flexDirection:"column",alignItems:"center",gap:4,transition:"all .2s",
                opacity:g.is_past?0.4:1,
              }}
              onMouseEnter={e => { if(!g.is_past){ e.currentTarget.style.borderColor=hero; e.currentTarget.style.transform="translateY(-2px)"; } }}
              onMouseLeave={e => { e.currentTarget.style.borderColor=g.is_past?"#1a1a1a":"#222"; e.currentTarget.style.transform="translateY(0)"; }}
            >
              <TrackSVG d={track} color={g.is_past?"#333":hero} size={44}/>
              <span style={{fontSize:16}}>{flag}</span>
              <div style={{fontSize:10,fontWeight:600,color:g.is_past?"#444":"#ccc",textAlign:"center"}}>{shortName}</div>
              <div style={{fontSize:8,color:g.is_past?"#333":"#555"}}>{g.is_past?"Concluded":dateStr}</div>
            </div>
          );
        })}
        {!gpList.length && renderStatus()}
      </div>
      <style>{`@keyframes drawTrack{to{stroke-dashoffset:0}}`}</style>
    </div>
  );
}
