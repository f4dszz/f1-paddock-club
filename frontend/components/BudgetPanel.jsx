import { CUR_SYMBOL } from "../domain/display.js";

export function BudgetPanel({budgetSummary, formBudget, formCurrency, liveResults}){
  if(!budgetSummary)return null;
  const bs=budgetSummary;
  const total=bs.total||0;
  const budget=bs.budget||+(formBudget||2500);
  const within=bs.within_budget;
  const quoteComplete=bs.quote_complete!==false;
  const isSelected=bs.basis==="selected";
  const tone=quoteComplete?(within?"#22C55E":"#EF4444"):"#F59E0B";
  const toneSoft=quoteComplete?(within?"#22C55E33":"#EF444433"):"#F59E0B44";
  const toneGradient=quoteComplete
    ?(within?"linear-gradient(90deg,#22C55E,#4ADE80)":"linear-gradient(90deg,#EF4444,#F87171)")
    :"linear-gradient(90deg,#F59E0B,#FBBF24)";
  const items=bs.items||[];
  const cur=bs.currency||formCurrency||"EUR";
  const sym=CUR_SYMBOL[cur]||(cur+" ");
  const unpricedCount=Object.values(liveResults||{}).reduce((n,zone)=>
    n + (zone.items||[]).filter(it=>it.priced===false && (zone.mode==="single"||zone.mode==="multi")).length, 0);

  return(
    <div data-testid="budget-panel" style={{background:"#111",border:`1px solid ${toneSoft}`,borderRadius:8,padding:"10px 14px",marginBottom:6,animation:"cardSlide .4s ease-out"}}>
      <div style={{fontSize:9,color:"#666",marginBottom:6}}>{isSelected?"Your selected total":"Baseline estimate"} ({cur})</div>
      {items.map((it,i)=>(
        <div key={i} style={{display:"flex",justifyContent:"space-between",fontSize:10,color:"#aaa",padding:"2px 0"}}>
          <span>{it.name}</span><span style={{color:"#ddd"}}>{sym}{Math.round(it.amount)}</span>
        </div>
      ))}
      <div style={{borderTop:"1px solid #222",marginTop:4,paddingTop:4}}>
        <div style={{display:"flex",justifyContent:"space-between",marginBottom:5}}>
          <span style={{fontSize:9,color:"#888"}}>Estimated total</span>
          <span style={{fontSize:13,fontWeight:700,color:tone}}>{quoteComplete?"": "Pending · "}{sym}{Math.round(total).toLocaleString()} <span style={{fontSize:9,fontWeight:400,color:"#555"}}>/ {sym}{Math.round(budget).toLocaleString()}</span></span>
        </div>
        <div style={{height:4,borderRadius:2,background:"#1a1a1a",overflow:"hidden"}}>
          <div style={{height:"100%",borderRadius:2,background:toneGradient,width:`${Math.min(total/budget*100,100)}%`,transition:"width .5s"}}/>
        </div>
        {bs.savings_tip&&<div style={{fontSize:8,color:quoteComplete?"#EF4444":"#F59E0B",marginTop:4}}>{bs.savings_tip}</div>}
        {!quoteComplete&&<div style={{fontSize:8,color:"#F59E0B",marginTop:4}}>Incomplete quote: pending {bs.missing_price_categories?.join(", ")||"price"}.</div>}
        {quoteComplete&&isSelected&&<div style={{fontSize:8,color:"#444",marginTop:4,fontStyle:"italic"}}>Budget based on your selected cards.</div>}
        {quoteComplete&&!isSelected&&unpricedCount>0&&<div style={{fontSize:8,color:"#666",marginTop:4,fontStyle:"italic"}}>{unpricedCount} option{unpricedCount>1?"s":""} without prices available. Baseline uses cheapest priced options.</div>}
        {quoteComplete&&!isSelected&&unpricedCount===0&&<div style={{fontSize:8,color:"#444",marginTop:4,fontStyle:"italic"}}>Budget based on cheapest available options.</div>}
      </div>
    </div>
  );
}
