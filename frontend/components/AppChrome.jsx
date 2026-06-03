import { FLAGS, PIPELINE, SHORT_NAMES, TRACK_MAP, ZONES } from "../domain/planningConstants.js";
import { ConFloat, TrackSVG, Zone } from "./PaddockVisuals.jsx";

export function AppHeader({ gp, phase, pipeIdx, onBack, onReset, rightSlot, extraActions }) {
  return (
    <div style={{padding:"8px 16px",borderBottom:"1px solid #1a1a1a",flexShrink:0,display:"flex",alignItems:"center",gap:8}}>
      <div
        onClick={onBack}
        role="button"
        tabIndex={0}
        aria-label="Back to Grand Prix selection"
        onKeyDown={(e)=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();onBack();}}}
        style={{cursor:"pointer",color:"#555",fontSize:14}}>←</div>
      {gp && <TrackSVG d={gp.track||TRACK_MAP["Italian GP"]} color={gp.hero||"#059669"} size={28}/>}
      <div style={{flex:1}}>
        <div style={{fontSize:13,fontWeight:700}}>{gp ? `${FLAGS[gp.country]||""} ${SHORT_NAMES[gp.gp_name]||gp.city}` : "Paddock Club"}</div>
        {gp && <div style={{fontSize:9,color:"#555"}}>{gp.gp_name} · {gp.race_date ? new Date(gp.race_date+"T00:00:00").toLocaleDateString("en",{month:"short",day:"numeric"}) : "TBD"}</div>}
      </div>
      {phase==="running" && (
        <div style={{display:"flex",gap:3,alignItems:"center"}}>
          {PIPELINE.map((_,i) => <div key={i} style={{width:16,height:3,borderRadius:2,background:i<=pipeIdx?"#E10600":"#222",transition:"all .3s"}}/>)}
        </div>
      )}
      {extraActions}
      {phase!=="welcome" && (
        <button type="button" onClick={onReset} style={{padding:"3px 8px",borderRadius:5,border:"1px solid #222",background:"transparent",color:"#555",fontSize:8,cursor:"pointer"}}>
          RESET
        </button>
      )}
      {rightSlot}
    </div>
  );
}

export function PaddockMap({ zSt, conPos, speaking }) {
  return (
    <div style={{position:"relative",width:"100%",paddingTop:"50%",background:"#0c0c0c",borderBottom:"1px solid #1a1a1a",flexShrink:0,overflow:"hidden"}}>
      <div style={{position:"absolute",inset:0,padding:"3%"}}>
        {ZONES.map(z => <Zone key={z.key} zone={z} status={zSt[z.key]||"idle"}/>)}
        <ConFloat x={conPos.x} y={conPos.y} speaking={speaking}/>
      </div>
    </div>
  );
}

export function DebugTrace({ debugLog, copyStatus, setCopyStatus }) {
  return (
    <div data-testid="debug-trace" style={{padding:"6px 14px 10px",borderTop:"1px solid #141414",background:"#0b0b0b",flexShrink:0}}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:4}}>
        <div style={{fontSize:8,color:"#555"}}>Debug trace</div>
        <button
          type="button"
          onClick={async () => {
            try{
              await navigator.clipboard.writeText(debugLog.join("\n"));
              setCopyStatus("copied");
            }catch(e){
              setCopyStatus("failed");
            }
            setTimeout(() => setCopyStatus("copy"), 1500);
          }}
          style={{fontSize:7,color:copyStatus==="failed"?"#EF4444":"#555",background:"#1a1a1a",border:"1px solid #333",borderRadius:3,padding:"1px 6px",cursor:"pointer"}}
        >
          {copyStatus}
        </button>
      </div>
      <div style={{maxHeight:88,overflowY:"auto",fontSize:8,color:"#777",fontFamily:"ui-monospace, SFMono-Regular, Consolas, monospace",lineHeight:1.5}}>
        {debugLog.length
          ? debugLog.map((line,i) => <div key={i}>{line}</div>)
          : <div>No events yet.</div>}
      </div>
    </div>
  );
}
