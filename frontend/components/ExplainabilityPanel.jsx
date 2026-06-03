import { ZONES } from "../domain/planningConstants.js";
import { describeConstraintMatch, sourceColor, sourceLabel } from "../domain/display.js";
import { PxChar } from "./PaddockVisuals.jsx";
import { useFocusTrap } from "../hooks/useFocusTrap.js";

export function ExplainabilityPanel({rationale,zoneKey,itemMain,onClose}){
  // a11y (frontend-completeness-6): move focus into the panel, trap Tab, Esc
  // to close, and restore focus to the trigger on close.
  const panelRef=useFocusTrap(!!rationale,onClose);

  if(!rationale)return null;
  const z=ZONES.find(z=>z.key===zoneKey)||{color:"#888",label:zoneKey};
  const reasons=Array.isArray(rationale.reasons)?rationale.reasons:[];
  const matches=rationale.constraint_matches||{};
  const matchEntries=Object.entries(matches).filter(([,v])=>v!==undefined&&v!==null&&v!==false);
  const sourcePath=Array.isArray(rationale.fallback_chain)&&rationale.fallback_chain.length
    ?rationale.fallback_chain:[rationale.source||"unknown"];
  const tradeOffs=Array.isArray(rationale.trade_offs)?rationale.trade_offs:[];

  return(
    <div style={{position:"fixed",inset:0,zIndex:100,pointerEvents:"auto"}}>
      <div onClick={onClose} style={{position:"absolute",inset:0,background:"rgba(0,0,0,0.55)",animation:"explainFadeIn .18s ease-out"}}/>
      <div ref={panelRef} role="dialog" aria-modal="true" aria-label="Why this card?" data-testid="explain-panel" style={{
        position:"absolute",top:0,right:0,bottom:0,width:"min(360px, 92vw)",
        background:"#0c0c0c",borderLeft:`1px solid ${z.color}55`,
        boxShadow:"-8px 0 24px rgba(0,0,0,0.5)",display:"flex",
        flexDirection:"column",animation:"explainSlideIn .25s cubic-bezier(0.16,1,0.3,1)",zIndex:101,
      }}>
        <div style={{padding:"12px 14px",borderBottom:`1px solid ${z.color}22`,display:"flex",alignItems:"center",gap:8,flexShrink:0}}>
          <PxChar type={zoneKey} size={20}/>
          <div style={{flex:1,minWidth:0}}>
            <div style={{fontSize:9,color:"#555",letterSpacing:"0.06em"}}>WHY THIS {z.label.toUpperCase()}?</div>
            <div style={{fontSize:11.5,fontWeight:600,color:"#ddd",overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{itemMain||"Selection"}</div>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" style={{background:"transparent",border:"1px solid #222",color:"#888",borderRadius:5,fontSize:12,padding:"3px 8px",cursor:"pointer",lineHeight:1}}>x</button>
        </div>

        <div style={{flex:1,overflowY:"auto",padding:"12px 14px"}} data-testid="explain-panel-body">
          {reasons.length>0&&(
            <section data-testid="explain-reasons" style={{marginBottom:14}}>
              <div style={{fontSize:8,color:"#555",letterSpacing:"0.08em",marginBottom:6}}>WHY IT WAS PICKED</div>
              {reasons.map((r,i)=>(
                <div key={i} style={{display:"flex",gap:7,marginBottom:5,alignItems:"flex-start"}}>
                  <span style={{fontSize:10,color:z.color,marginTop:1,flexShrink:0}}>✓</span>
                  <span style={{fontSize:11,color:"#ccc",lineHeight:1.45}}>{r}</span>
                </div>
              ))}
            </section>
          )}

          {matchEntries.length>0&&(
            <section style={{marginBottom:14}}>
              <div style={{fontSize:8,color:"#555",letterSpacing:"0.08em",marginBottom:6}}>MATCHES YOUR CONSTRAINTS</div>
              <div style={{display:"flex",flexWrap:"wrap",gap:4}}>
                {matchEntries.map(([k,v])=>(
                  <span key={k} style={{fontSize:9,color:"#86EFAC",border:"1px solid #22C55E55",background:"#22C55E14",borderRadius:999,padding:"2px 8px"}}>
                    {describeConstraintMatch(k,v)}
                  </span>
                ))}
              </div>
            </section>
          )}

          <section data-testid="explain-source-path" style={{marginBottom:14}}>
            <div style={{fontSize:8,color:"#555",letterSpacing:"0.08em",marginBottom:6}}>DATA SOURCE PATH</div>
            <div style={{display:"flex",alignItems:"center",gap:5,flexWrap:"wrap"}}>
              {sourcePath.map((src,i)=>(
                <span key={i} style={{display:"flex",alignItems:"center",gap:5}}>
                  <span style={{fontSize:8,fontWeight:600,color:sourceColor(src),background:sourceColor(src)+"15",border:`1px solid ${sourceColor(src)}33`,padding:"2px 7px",borderRadius:8,letterSpacing:"0.02em"}}>{sourceLabel(src)}</span>
                  {i<sourcePath.length-1&&<span style={{fontSize:10,color:"#444"}}>-&gt;</span>}
                </span>
              ))}
            </div>
            <div style={{fontSize:8,color:"#555",marginTop:5,lineHeight:1.5,fontStyle:"italic"}}>
              {rationale.source_path_note||"This is the configured source path inferred from the final card source, not a full runtime attempt log."}
            </div>
          </section>

          {tradeOffs.length>0&&(
            <section style={{marginBottom:8}}>
              <div style={{fontSize:8,color:"#555",letterSpacing:"0.08em",marginBottom:6}}>TRADE-OFFS VS ALTERNATIVES</div>
              {tradeOffs.map((t,i)=>(
                <div key={i} style={{background:"#111",border:"1px solid #1f1f1f",borderRadius:6,padding:"8px 10px",marginBottom:6}}>
                  <div style={{fontSize:10,fontWeight:600,color:"#ccc",marginBottom:4}}>vs {t.against||"alternative"}</div>
                  {t.advantage&&<div style={{display:"flex",gap:6,marginBottom:2}}><span style={{fontSize:9,color:"#22C55E",flexShrink:0,minWidth:38}}>pro</span><span style={{fontSize:10,color:"#bbb",lineHeight:1.4}}>{t.advantage}</span></div>}
                  {t.cost&&<div style={{display:"flex",gap:6}}><span style={{fontSize:9,color:"#EF4444",flexShrink:0,minWidth:38}}>con</span><span style={{fontSize:10,color:"#bbb",lineHeight:1.4}}>{t.cost}</span></div>}
                </div>
              ))}
            </section>
          )}

          {reasons.length===0&&matchEntries.length===0&&tradeOffs.length===0&&(
            <div style={{fontSize:10,color:"#555",fontStyle:"italic",padding:"8px 0"}}>No detailed rationale recorded for this card.</div>
          )}
        </div>
      </div>
    </div>
  );
}
