import { SOURCE_LABELS } from "../domain/display.js";

export function SourceBadge({source}){
  const meta=SOURCE_LABELS[source]||SOURCE_LABELS.mock;
  return <span title={`Data source: ${source||"mock"}`} style={{fontSize:7,fontWeight:600,color:meta.color,background:meta.color+"15",border:`1px solid ${meta.color}33`,padding:"1px 5px",borderRadius:8,letterSpacing:"0.02em",whiteSpace:"nowrap",flexShrink:0}}>{meta.text}</span>;
}
