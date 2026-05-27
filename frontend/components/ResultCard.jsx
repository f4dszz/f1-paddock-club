import { ZONES } from "../domain/planningConstants.js";
import { CUR_SYMBOL, linkActionLabel } from "../domain/display.js";
import { PxChar } from "./PaddockVisuals.jsx";
import { SourceBadge } from "./SourceBadge.jsx";

export function ResultCard({zoneKey,selections,onSelect,liveResults,onShowExplain,explainDemo}){
  const z=ZONES.find(z=>z.key===zoneKey);
  const data=(liveResults||{})[zoneKey];
  if(!data||!data.items?.length) return null;
  const{mode,items,bookLabel,bookIcon}=data;
  const sel=selections[zoneKey]||[];
  const hasSelection=sel.length>0;
  const selectionValue=(it,i)=>it.selectionIndex ?? i;
  const selectedItems=items.filter((it,i)=>sel.includes(selectionValue(it,i)));
  const selectedCurs=new Set(selectedItems.filter(it=>it.priced!==false).map(it=>it.currency||"").filter(Boolean));
  const selectedTotal=selectedItems.filter(it=>it.priced!==false).reduce((s,it)=>(it.pv||0)+s,0);
  const chipSameCur=selectedCurs.size===1?[...selectedCurs][0]:null;
  const chipText=chipSameCur
    ?`${CUR_SYMBOL[chipSameCur]||(chipSameCur+" ")}${selectedTotal}`
    :`${sel.length} selected`;
  const bookableItems=selectedItems.filter(it=>it?.link);

  const toggle=(idx)=>{
    if(mode==="none")return;
    if(mode==="single") onSelect(zoneKey,sel[0]===idx?[]:[idx]);
    else{
      const next=sel.includes(idx)?sel.filter(x=>x!==idx):[...sel,idx];
      onSelect(zoneKey,next);
    }
  };

  return(
    <div data-testid={`result-card-${zoneKey}`} style={{background:"#111",border:`1px solid ${hasSelection?z.color+"55":z.color+"33"}`,borderRadius:8,overflow:"hidden",animation:"cardSlide .4s cubic-bezier(0.16,1,0.3,1)",marginBottom:6,transition:"border-color .3s"}}>
      <div style={{padding:"6px 10px",borderBottom:`1px solid ${z.color}15`,display:"flex",alignItems:"center",gap:6}}>
        <PxChar type={zoneKey} size={16}/>
        <span style={{fontSize:10,fontWeight:600,color:"#ccc"}}>{z.label}</span>
        {mode!=="none"&&<span style={{fontSize:7,color:"#444",marginLeft:4}}>{mode==="single"?"pick one":"select any"}</span>}
        {hasSelection&&<span style={{marginLeft:"auto",fontSize:8,fontWeight:600,color:z.color}}>{chipText}</span>}
        {!hasSelection&&<div style={{marginLeft:"auto",width:4,height:4,borderRadius:"50%",background:z.color,boxShadow:`0 0 5px ${z.color}`}}/>}
      </div>
      {items.map((it,i)=>{
        const value=selectionValue(it,i);
        const isSel=sel.includes(value);
        const selectable=mode!=="none";
        const isRadio=mode==="single";
        const unpriced=it.priced===false && (mode==="single"||mode==="multi");
        return(
          <div key={i} data-testid={`result-item-${zoneKey}-${i}`} onClick={()=>selectable&&toggle(value)}
            style={{display:"flex",alignItems:"center",gap:6,padding:"5px 10px",borderBottom:i<items.length-1?"1px solid #1a1a1a":"none",
              cursor:selectable?"pointer":"default",
              background:isSel?z.color+"12":"transparent",
              borderLeft:isSel?`2px solid ${z.color}`:"2px solid transparent",
              opacity:unpriced?0.65:1,
              transition:"all .15s",
            }}>
            {mode!=="none"&&<div style={{width:12,height:12,borderRadius:isRadio?"50%":3,border:`1.5px solid ${isSel?z.color:(unpriced?"#2a2a2a":"#333")}`,background:isSel?z.color:"transparent",display:"flex",alignItems:"center",justifyContent:"center",flexShrink:0,transition:"all .15s"}}>
              {isSel&&<span style={{fontSize:8,color:"#fff",lineHeight:1}}>✓</span>}
            </div>}
            <span style={{fontSize:7,fontWeight:700,color:z.color,background:z.color+"15",padding:"1px 4px",borderRadius:3,minWidth:30,textAlign:"center"}}>{it.tag}</span>
            <div style={{flex:1,minWidth:0}}>
              <div style={{fontSize:10.5,fontWeight:500,color:"#ddd"}}>{it.main}</div>
              {it.sub&&<div style={{fontSize:9,color:"#555"}}>{it.sub}</div>}
            </div>
            {(zoneKey==="hotel"||zoneKey==="transport")&&it.source&&<SourceBadge source={it.source}/>}
            {(it.rationale||explainDemo)&&onShowExplain&&(
              <button onClick={(e)=>{e.stopPropagation();onShowExplain(zoneKey,it);}}
                data-testid={`explain-button-${zoneKey}-${i}`}
                aria-label="Why this card?"
                title="Why this card?"
                style={{fontSize:9,fontWeight:700,color:"#888",background:"#1a1a1a",border:"1px solid #2a2a2a",borderRadius:"50%",width:16,height:16,display:"flex",alignItems:"center",justifyContent:"center",cursor:"pointer",flexShrink:0,padding:0,lineHeight:1}}
                onMouseEnter={e=>{e.currentTarget.style.color=z.color;e.currentTarget.style.borderColor=z.color+"66";}}
                onMouseLeave={e=>{e.currentTarget.style.color="#888";e.currentTarget.style.borderColor="#2a2a2a";}}>
                i
              </button>
            )}
            {it.price&&<span style={{fontSize:unpriced?9:10.5,fontWeight:unpriced?400:600,color:unpriced?"#666":(isSel?"#fff":"#888"),fontStyle:unpriced?"italic":"normal"}}>{it.price}</span>}
            {unpriced&&it.link&&<button data-testid={`book-unpriced-${zoneKey}-${i}`} onClick={(e)=>{e.stopPropagation();window.open(it.link,"_blank");}} style={{fontSize:8,padding:"2px 6px",borderRadius:3,border:`1px solid ${z.color}44`,background:"transparent",color:z.color,cursor:"pointer"}}>{linkActionLabel(it)} →</button>}
          </div>
        );
      })}
      {bookLabel&&hasSelection&&bookableItems.length>0&&(
        <div style={{padding:"6px 10px",borderTop:`1px solid ${z.color}22`}}>
          <button data-testid={`book-button-${zoneKey}`} onClick={(e)=>{e.stopPropagation();
            bookableItems.forEach(item=>{
              const url=item.link;
              if(url) window.open(url,"_blank");
            });
          }} style={{width:"100%",padding:"7px",borderRadius:5,border:"none",background:z.color,color:"#fff",fontSize:10,fontWeight:600,cursor:"pointer",display:"flex",alignItems:"center",justifyContent:"center",gap:4}}>
            <span style={{fontSize:12}}>{bookIcon}</span> {bookableItems.length===1?linkActionLabel(bookableItems[0]):`Open selected links (${bookableItems.length})`}
          </button>
          <div style={{fontSize:8,color:"#444",textAlign:"center",marginTop:3}}>Opens provider/search pages; not a purchase confirmation.</div>
        </div>
      )}
    </div>
  );
}
