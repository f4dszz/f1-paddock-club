import { useState, useEffect, useRef, useCallback, useMemo } from "react";

const ZONES = [
  { key:"ticket", label:"Tickets", color:"#F59E0B", x:8, y:8, w:42, h:38 },
  { key:"transport", label:"Flights", color:"#3B82F6", x:50, y:8, w:42, h:38 },
  { key:"hotel", label:"Hotel", color:"#A855F7", x:8, y:54, w:28, h:38 },
  { key:"plan", label:"Schedule", color:"#F97316", x:36, y:54, w:28, h:38 },
  { key:"tour", label:"Explore", color:"#06B6D4", x:64, y:54, w:28, h:38 },
];

const PIPELINE = [
  { zones:["ticket"], label:"Finding best tickets first..." },
  { zones:["transport","hotel"], label:"Searching flights + hotels in parallel..." },
  { zones:["plan","tour"], label:"Planning schedule + sights in parallel..." },
];

const CONC_HOME = { x:46, y:46 };

const THINK = {
  ticket:["Scanning platforms...","Comparing grandstands...","Checking sightlines...","Picks ready"],
  transport:["Searching flights...","Direct vs connecting...","Local rail...","Routes done"],
  hotel:["Race-week rates...","Distance filter...","Comparing...","Found"],
  plan:["Race weekend map...","FP / Quali / Race...","Free time...","Set"],
  tour:["Local gems...","F1 specials...","Restaurants...","Ready"],
};

// ── Backend connection config ───────────────────────────────────────
const API_BASE = "";
const WS_URL = `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws`;

// ── Transform backend data into card format ────────────────────────
function transformResults(data) {
  const r = {};
  if (data.tickets?.length) {
    r.ticket = { mode:"single", bookLabel:"Book tickets", bookIcon:"🎫", items:
      data.tickets.filter(t=>t.tag!=="INFO").map(t=>{
        const pv=t.price||0;
        return {
          tag:t.tag||"PICK", main:t.name||"Ticket", sub:t.section||"",
          price: pv>0 ? `${t.currency||"EUR"} ${t.price}` : "Price not provided",
          pv, priced: pv>0,
          currency:t.currency||"EUR", link:t.link||"",
        };
      })
    };
  }
  if (data.transport?.length) {
    // Flights changed to single-select: all current booking links route
    // to the same Google Flights search page, so multi-select is misleading.
    r.transport = { mode:"single", bookLabel:"Book flight", bookIcon:"✈", items:
      data.transport.filter(t=>t.tag!=="INFO").map(t=>{
        const pv=t.price||0;
        return {
          tag:t.tag||"OUT", main:t.summary||"Flight", sub:t.detail||"",
          price: pv>0 ? `${t.currency||"USD"} ${t.price}` : "Price not provided",
          pv, priced: pv>0,
          currency:t.currency||"USD", link:t.link||"",
        };
      })
    };
  }
  if (data.hotel?.length) {
    r.hotel = { mode:"single", bookLabel:"Book hotel", bookIcon:"🏨", items:
      data.hotel.filter(h=>h.tag!=="INFO").map(h=>{
        const pv=h.price_per_night||0;
        return {
          tag:h.tag||"NEAR", main:h.name||"Hotel",
          sub:`${h.distance||""} · ${h.rating||""}★ · ${h.nights||"?"}n`,
          price: pv>0 ? `${h.currency||"USD"} ${h.price_per_night}/n` : "Price not provided",
          pv, priced: pv>0,
          currency:h.currency||"USD", link:h.link||"",
        };
      })
    };
  }
  if (data.itinerary?.length) {
    r.plan = { mode:"none", items:
      data.itinerary.map((line,i)=>{
        const m = line.match(/^Day\s*\d+\s*\((\w+)\):\s*(.+)/i);
        return { tag:m?m[1].substring(0,3).toUpperCase():`D${i+1}`, main:m?m[2]:line, sub:"", price:"", priced:false };
      })
    };
  }
  if (data.tour?.length) {
    // Tour is display-only — the items come from an LLM and don't have
    // booking URLs, so selection/checkbox UX was misleading. Keep as
    // informational recommendations like itinerary.
    r.tour = { mode:"none", items:
      data.tour.map(line=>{
        const m = line.match(/^(.+?)\s*\(([^)]+)\)\s*[—–-]\s*(.+)/);
        return m
          ? { tag:"REC", main:m[1].replace(/^[^\w]+/,""), sub:m[3], price:m[2], pv:parseInt(m[2])||0, priced:true }
          : { tag:"REC", main:line.substring(0,40), sub:line.substring(40), price:"", pv:0, priced:false };
      })
    };
  }
  return r;
}

// Default empty RESULTS — will be replaced by live data
let RESULTS = {};

function PxChar({type,size=28}){
  const C={
    concierge:[["#333",12,1,8,2],["#1a1a1a",10,2,12,3],["#FFD5B0",13,5,6,5],["#333",14,7,1,1],["#333",17,7,1,1],["#E88B7A",15,9,2,1],["#1a1a1a",11,10,10,8],["#E10600",14,11,4,1],["#FFD700",15,12,2,1],["#1a1a1a",9,11,2,6],["#1a1a1a",21,11,2,6],["#333",12,18,3,5],["#333",17,18,3,5],["#1a1a1a",11,23,4,2],["#1a1a1a",17,23,4,2]],
    ticket:[["#F59E0B",12,1,8,3],["#FFD5B0",13,4,6,5],["#333",14,6,1,1],["#333",17,6,1,1],["#F59E0B",11,9,10,8],["#fff",13,10,6,2],["#1E3A5F",12,17,3,5],["#1E3A5F",17,17,3,5],["#8B4513",11,22,4,2],["#8B4513",17,22,4,2]],
    transport:[["#1E3A5F",12,1,8,3],["#3B82F6",16,1,5,2],["#FFD5B0",13,4,6,5],["#333",14,6,1,1],["#333",17,6,1,1],["#1E3A5F",11,9,10,8],["#FFD700",14,10,4,1],["#3B82F6",12,12,8,1],["#1E3A5F",12,17,3,5],["#1E3A5F",17,17,3,5],["#111",11,22,4,2],["#111",17,22,4,2]],
    hotel:[["#A855F7",12,1,8,3],["#FFD5B0",13,4,6,5],["#333",14,6,1,1],["#333",17,6,1,1],["#7E22CE",11,9,10,8],["#fff",14,10,4,2],["#FFD700",15,13,2,1],["#333",12,17,3,5],["#333",17,17,3,5],["#111",11,22,4,2],["#111",17,22,4,2]],
    plan:[["#F97316",13,1,6,3],["#FFD5B0",13,4,6,5],["#333",14,6,1,1],["#333",17,6,1,1],["#EA580C",11,9,10,8],["#FED7AA",13,11,6,3],["#EA580C",14,12,4,1],["#78350F",12,17,3,5],["#78350F",17,17,3,5],["#451A03",11,22,4,2],["#451A03",17,22,4,2]],
    tour:[["#06B6D4",11,1,10,3],["#FFD5B0",13,4,6,5],["#333",14,6,1,1],["#333",17,6,1,1],["#0E7490",11,9,10,8],["#67E8F9",14,11,4,3],["#365314",12,17,3,5],["#365314",17,17,3,5],["#3B2507",11,22,4,2],["#3B2507",17,22,4,2]],
  };
  const px=C[type]||C.concierge;
  return <svg viewBox="0 0 32 26" width={size} height={size*26/32} style={{imageRendering:"pixelated"}}>{px.map(([f,x,y,w,h],i)=><rect key={i} x={x} y={y} width={w} height={h} fill={f} rx={0.5}/>)}</svg>;
}

function Zone({zone,status}){
  const a=status==="active",d=status==="done";
  return(
    <div style={{
      position:"absolute",left:`${zone.x}%`,top:`${zone.y}%`,width:`${zone.w}%`,height:`${zone.h}%`,
      background:a?zone.color+"15":d?zone.color+"08":"#141414",
      border:`1.5px solid ${a?zone.color:d?zone.color+"44":"#222"}`,
      borderRadius:10,display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",gap:2,
      transition:"all .4s",
      boxShadow:a?`0 0 20px ${zone.color}18, inset 0 0 12px ${zone.color}06`:"none",
    }}>
      <div style={{animation:a?"cBounce .5s ease-in-out infinite":"none"}}><PxChar type={zone.key} size={a?28:22}/></div>
      <div style={{fontSize:8,fontWeight:600,color:a?zone.color:d?zone.color+"99":"#444",letterSpacing:"0.04em"}}>{zone.label}</div>
      {a&&<div style={{width:4,height:4,borderRadius:"50%",background:zone.color,boxShadow:`0 0 6px ${zone.color}`,animation:"pulse 1s ease-in-out infinite"}}/>}
      {d&&<div style={{fontSize:7,color:zone.color,fontWeight:700}}>DONE</div>}
    </div>
  );
}

function ConFloat({x,y,speaking}){
  return(
    <div style={{position:"absolute",left:`${x}%`,top:`${y}%`,transform:"translate(-50%,-50%)",transition:"left .7s cubic-bezier(0.34,1.56,0.64,1), top .7s cubic-bezier(0.34,1.56,0.64,1)",zIndex:10,pointerEvents:"none"}}>
      <div style={{animation:speaking?"cBounce .5s ease-in-out infinite":"none"}}><PxChar type="concierge" size={30}/></div>
    </div>
  );
}

function SingleThinkStream({lines,color,onDone}){
  const[shown,setShown]=useState([]);const[cur,setCur]=useState("");const[li,setLi]=useState(0);const[ci,setCi]=useState(0);
  const doneRef=useRef(false);
  useEffect(()=>{
    if(li>=lines.length){if(!doneRef.current){doneRef.current=true;onDone?.();}return;}
    const line=lines[li];
    if(ci<line.length){const t=setTimeout(()=>{setCur(p=>p+line[ci]);setCi(c=>c+1);},18+Math.random()*12);return()=>clearTimeout(t);}
    else{const t=setTimeout(()=>{setShown(p=>[...p,line]);setCur("");setCi(0);setLi(l=>l+1);},130);return()=>clearTimeout(t);}
  },[li,ci,lines]);
  return(
    <div style={{fontSize:10,color:"#666",lineHeight:1.4}}>
      {shown.map((l,i)=><div key={i} style={{opacity:.5}}><span style={{color}}>› </span>{l}</div>)}
      {cur&&<div><span style={{color}}>› </span>{cur}<span style={{animation:"blink .7s step-end infinite",color}}>▋</span></div>}
    </div>
  );
}

// Currency symbol lookup (for cards which show source currency per plan A)
const CUR_SYMBOL={EUR:"€",USD:"$",CNY:"¥"};

function ResultCard({zoneKey,selections,onSelect,liveResults}){
  const z=ZONES.find(z=>z.key===zoneKey);
  const data=(liveResults||RESULTS)[zoneKey];
  if(!data||!data.items?.length) return null;
  const{mode,items,bookLabel,bookIcon}=data;
  const sel=selections[zoneKey]||[];
  const hasSelection=sel.length>0;
  // Only priced items can be selected; unpriced items are shown as
  // informational with optional click-through to the provider's site.
  const unpricedCount=items.filter(it=>it.priced===false&&it.pv===0&&(mode==="single"||mode==="multi")).length;
  // Chip logic: if all selected items share one currency, show that
  // total; if mixed (rare), show a neutral "N selected" instead of
  // pretending to know the currency. Avoids fake-€ summing across USD.
  const selectedItems=sel.map(idx=>items[idx]).filter(Boolean);
  const selectedCurs=new Set(selectedItems.filter(it=>it.priced!==false).map(it=>it.currency||"").filter(Boolean));
  const selectedTotal=selectedItems.filter(it=>it.priced!==false).reduce((s,it)=>(it.pv||0)+s,0);
  const chipSameCur=selectedCurs.size===1?[...selectedCurs][0]:null;
  const chipText=chipSameCur
    ?`${CUR_SYMBOL[chipSameCur]||(chipSameCur+" ")}${selectedTotal}`
    :`${sel.length} selected`;
  // Only priced items with a link are truly bookable via the batch button.
  // Unpriced items with links are still jumpable per-row (see render below).
  const bookableItems=sel.filter(idx=>items[idx]?.link&&items[idx]?.priced!==false);

  const toggle=(idx)=>{
    if(mode==="none")return;
    const it=items[idx];
    if(it&&it.priced===false)return;  // can't add unpriced to budget selection
    if(mode==="single") onSelect(zoneKey,sel[0]===idx?[]:[idx]);
    else{
      const next=sel.includes(idx)?sel.filter(x=>x!==idx):[...sel,idx];
      onSelect(zoneKey,next);
    }
  };

  return(
    <div style={{background:"#111",border:`1px solid ${hasSelection?z.color+"55":z.color+"33"}`,borderRadius:8,overflow:"hidden",animation:"cardSlide .4s cubic-bezier(0.16,1,0.3,1)",marginBottom:6,transition:"border-color .3s"}}>
      <div style={{padding:"6px 10px",borderBottom:`1px solid ${z.color}15`,display:"flex",alignItems:"center",gap:6}}>
        <PxChar type={zoneKey} size={16}/>
        <span style={{fontSize:10,fontWeight:600,color:"#ccc"}}>{z.label}</span>
        {mode!=="none"&&<span style={{fontSize:7,color:"#444",marginLeft:4}}>{mode==="single"?"pick one":"select any"}</span>}
        {hasSelection&&<span style={{marginLeft:"auto",fontSize:8,fontWeight:600,color:z.color}}>{chipText}</span>}
        {!hasSelection&&<div style={{marginLeft:"auto",width:4,height:4,borderRadius:"50%",background:z.color,boxShadow:`0 0 5px ${z.color}`}}/>}
      </div>
      {items.map((it,i)=>{
        const isSel=sel.includes(i);
        const selectable=mode!=="none" && it.priced!==false;
        const isRadio=mode==="single";
        const unpriced=it.priced===false && (mode==="single"||mode==="multi");
        return(
          <div key={i} onClick={()=>selectable&&toggle(i)}
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
            {it.price&&<span style={{fontSize:unpriced?9:10.5,fontWeight:unpriced?400:600,color:unpriced?"#666":(isSel?"#fff":"#888"),fontStyle:unpriced?"italic":"normal"}}>{it.price}</span>}
            {unpriced&&it.link&&<button onClick={(e)=>{e.stopPropagation();window.open(it.link,"_blank");}} style={{fontSize:8,padding:"2px 6px",borderRadius:3,border:`1px solid ${z.color}44`,background:"transparent",color:z.color,cursor:"pointer"}}>Check →</button>}
          </div>
        );
      })}
      {bookLabel&&hasSelection&&bookableItems.length>0&&(
        <div style={{padding:"6px 10px",borderTop:`1px solid ${z.color}22`}}>
          <button onClick={(e)=>{e.stopPropagation();
            bookableItems.forEach(idx=>{
              const url=items[idx].link;
              if(url) window.open(url,"_blank");
            });
          }} style={{width:"100%",padding:"7px",borderRadius:5,border:"none",background:z.color,color:"#fff",fontSize:10,fontWeight:600,cursor:"pointer",display:"flex",alignItems:"center",justifyContent:"center",gap:4}}>
            <span style={{fontSize:12}}>{bookIcon}</span> {bookLabel} ({bookableItems.length})
          </button>
          <div style={{fontSize:8,color:"#444",textAlign:"center",marginTop:3}}>Opens the official booking site in a new tab</div>
        </div>
      )}
    </div>
  );
}

function ThinkPanel({zoneKeys,onAllDone}){
  const doneCount=useRef(0);
  const total=zoneKeys.length;
  const handleOne=useCallback(()=>{
    doneCount.current+=1;
    if(doneCount.current>=total) setTimeout(()=>onAllDone?.(),100);
  },[total,onAllDone]);
  const isP=total>1;
  return(
    <div style={{display:"flex",gap:6,marginBottom:8}}>
      {zoneKeys.map(key=>{
        const z=ZONES.find(z=>z.key===key);
        return(
          <div key={key} style={{flex:1,background:"#111",border:`1px solid ${z.color}33`,borderRadius:8,padding:"8px 10px",animation:"slideUp .3s ease-out"}}>
            <div style={{display:"flex",alignItems:"center",gap:6,marginBottom:4}}>
              <PxChar type={key} size={16}/>
              <span style={{fontSize:9,fontWeight:600,color:z.color}}>{z.label}</span>
              {isP&&<span style={{fontSize:7,color:"#444",marginLeft:"auto",border:"1px solid #333",borderRadius:3,padding:"1px 4px"}}>PARALLEL</span>}
            </div>
            <SingleThinkStream lines={THINK[key]} color={z.color} onDone={handleOne}/>
          </div>
        );
      })}
    </div>
  );
}

// ── Country flag lookup ─────────────────────────────────────────────
const FLAGS={"Australia":"\u{1F1E6}\u{1F1FA}","China":"\u{1F1E8}\u{1F1F3}","Japan":"\u{1F1EF}\u{1F1F5}","USA":"\u{1F1FA}\u{1F1F8}","Canada":"\u{1F1E8}\u{1F1E6}","Monaco":"\u{1F1F2}\u{1F1E8}","Spain":"\u{1F1EA}\u{1F1F8}","Austria":"\u{1F1E6}\u{1F1F9}","UK":"\u{1F1EC}\u{1F1E7}","Belgium":"\u{1F1E7}\u{1F1EA}","Hungary":"\u{1F1ED}\u{1F1FA}","Netherlands":"\u{1F1F3}\u{1F1F1}","Italy":"\u{1F1EE}\u{1F1F9}","Azerbaijan":"\u{1F1E6}\u{1F1FF}","Singapore":"\u{1F1F8}\u{1F1EC}","Mexico":"\u{1F1F2}\u{1F1FD}","Brazil":"\u{1F1E7}\u{1F1F7}","Qatar":"\u{1F1F6}\u{1F1E6}","UAE":"\u{1F1E6}\u{1F1EA}"};
const HERO_COLORS=["#059669","#DC2626","#1E40AF","#EC4899","#7C3AED","#F59E0B","#06B6D4","#F97316"];
// GP short display names for cards
const SHORT_NAMES={"Australian GP":"Australia","Chinese GP":"China","Japanese GP":"Japan","Miami GP":"Miami","Canadian GP":"Canada","Monaco GP":"Monaco","Barcelona-Catalunya GP":"Barcelona","Austrian GP":"Austria","British GP":"Britain","Belgian GP":"Belgium","Hungarian GP":"Hungary","Dutch GP":"Netherlands","Italian GP":"Monza","Spanish GP":"Madrid","Azerbaijan GP":"Baku","Singapore GP":"Singapore","United States GP":"USA","Mexico City GP":"Mexico","Brazilian GP":"Brazil","Las Vegas GP":"Las Vegas","Qatar GP":"Qatar","Abu Dhabi GP":"Abu Dhabi"};
// Simplified but recognizable circuit outlines per GP
const TRACK_MAP={
  "Australian GP":"M30,60 L25,35 Q28,20 40,15 L55,12 Q70,10 75,20 L78,40 Q80,55 72,65 L60,72 Q50,78 40,75 L30,60Z",
  "Chinese GP":"M25,50 L30,25 Q35,15 50,12 L65,15 Q75,20 78,35 L75,50 Q72,60 65,65 L55,55 Q50,50 45,55 L35,65 Q28,60 25,50Z",
  "Japanese GP":"M25,45 Q35,20 50,25 Q60,30 55,45 Q50,55 60,60 Q70,65 65,75 Q50,80 35,70 Q25,60 25,45Z",
  "Miami GP":"M30,35 L65,20 Q80,25 75,40 L60,50 Q55,55 60,65 L40,75 Q25,70 25,55 L30,35Z",
  "Canadian GP":"M20,45 L25,20 Q30,12 45,15 L55,20 Q65,25 60,40 L65,50 Q70,60 60,70 L40,75 Q25,72 20,60 L20,45Z",
  "Monaco GP":"M35,30 Q45,15 60,20 L70,35 Q75,50 65,60 L50,70 Q35,75 30,60 L35,30Z",
  "Barcelona-Catalunya GP":"M25,55 L30,30 Q35,18 50,15 L65,18 Q75,22 78,35 L72,50 Q68,62 55,65 L45,60 Q38,58 35,62 L28,68 Q22,65 25,55Z",
  "Austrian GP":"M35,70 L30,45 Q32,30 45,20 L60,15 Q72,18 70,30 L65,55 Q62,68 50,72 L35,70Z",
  "British GP":"M25,45 Q30,20 50,15 Q70,12 80,30 Q85,45 78,60 Q65,75 45,78 Q25,70 25,45Z",
  "Belgian GP":"M25,35 L35,15 Q45,10 55,18 L65,35 Q70,50 60,60 L50,70 Q40,78 30,70 L22,50 Q20,42 25,35Z",
  "Hungarian GP":"M30,65 L25,40 Q28,25 40,18 L60,15 Q72,18 75,30 L72,50 Q70,62 60,68 L40,72 Q32,70 30,65Z",
  "Dutch GP":"M30,55 L35,30 Q40,18 55,15 Q68,14 72,25 L70,45 Q68,58 58,62 Q48,65 40,60 L30,55Z",
  "Italian GP":"M40,75 L35,30 Q38,15 50,12 Q62,10 68,25 L72,50 Q75,65 65,75 Q55,80 40,75Z",
  "Spanish GP":"M25,50 L35,25 Q42,15 55,12 L70,15 Q80,20 78,35 L72,55 Q68,68 55,72 L40,70 Q28,65 25,50Z",
  "Azerbaijan GP":"M30,75 L25,50 L28,30 L40,20 Q50,15 60,20 L72,30 L75,50 L70,70 Q60,78 45,78 L30,75Z",
  "Singapore GP":"M30,35 Q40,18 55,20 Q70,22 78,35 Q82,50 75,62 Q65,72 50,75 Q35,72 28,58 Q25,45 30,35Z",
  "United States GP":"M25,50 Q30,20 50,15 Q65,12 75,25 L80,45 Q82,60 70,70 Q55,78 40,75 Q25,65 25,50Z",
  "Mexico City GP":"M30,65 L25,40 Q28,22 45,15 L60,12 Q75,15 78,30 L75,55 Q72,68 58,72 L38,70 Q30,68 30,65Z",
  "Brazilian GP":"M70,25 Q78,35 75,50 L65,65 Q55,75 40,72 L30,55 Q25,40 35,28 Q50,18 70,25Z",
  "Las Vegas GP":"M30,30 L70,25 Q82,30 80,45 L75,60 Q70,72 55,75 L35,70 Q22,65 25,45 L30,30Z",
  "Qatar GP":"M30,60 L28,35 Q32,18 50,12 L65,15 Q78,20 75,35 L70,55 Q65,70 50,72 L35,68 Q28,65 30,60Z",
  "Abu Dhabi GP":"M28,55 L32,30 Q38,15 55,12 L68,15 Q80,20 78,35 L72,55 Q68,70 52,75 L38,72 Q25,68 28,55Z",
};

function TrackSVG({d,color,size=44}){
  return <svg width={size} height={size} viewBox="0 0 100 90"><path d={d} fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" opacity={0.6} style={{strokeDasharray:300,strokeDashoffset:300,animation:"drawTrack 1.5s ease-out forwards"}}/></svg>;
}

export default function App(){
  const debugMode=useMemo(()=>new URLSearchParams(window.location.search).has("debug"),[]);
  const[screen,setScreen]=useState("select");
  const[gpList,setGpList]=useState([]);
  const[gp,setGp]=useState(null);
  const[phase,setPhase]=useState("welcome");
  const[form,setForm]=useState({origin:"",budget:"2500",currency:"EUR",stand:"any",extraDays:2,special:"",stops:"",departDate:"",returnDate:""});
  const[zSt,setZSt]=useState({});
  const[conPos,setConPos]=useState(CONC_HOME);
  const[speaking,setSpeaking]=useState(false);
  const[thinkBatch,setThinkBatch]=useState(null);
  const[results,setResults]=useState([]);
  const[liveResults,setLiveResults]=useState({});
  const[budgetSummary,setBudgetSummary]=useState(null);
  const[chatInput,setChatInput]=useState("");
  const[chatMsgs,setChatMsgs]=useState([]);
  const[statusMsgs,setStatusMsgs]=useState([]);
  const[showStatus,setShowStatus]=useState(false);
  const[chatLoading,setChatLoading]=useState(false);
  const[updatedCards,setUpdatedCards]=useState(new Set());
  const[pipeIdx,setPipeIdx]=useState(-1);
  const[selections,setSelections]=useState({});
  const[debugLog,setDebugLog]=useState([]);
  const[copyStatus,setCopyStatus]=useState("copy");
  const cancelRef=useRef(false);
  const scrollRef=useRef(null);
  const resolveRef=useRef(null);
  const wsRef=useRef(null);

  const pushDebug=useCallback((label, data) => {
    const stamp = new Date().toLocaleTimeString("en-GB", { hour12: false });
    const line = data === undefined ? `${stamp} ${label}` : `${stamp} ${label} ${typeof data === "string" ? data : JSON.stringify(data)}`;
    console.log("[demo-debug]", line);
    setDebugLog(prev => [...prev.slice(-19), line]);
  }, []);

  // Fetch GP calendar from backend on mount
  useEffect(()=>{
    pushDebug("calendar.fetch.start", `${window.location.origin}/api/calendar`);
    fetch(`${API_BASE}/api/calendar`)
      .then(r=>{
        pushDebug("calendar.fetch.response", { status:r.status, ok:r.ok });
        return r.json();
      })
      .then(data=>{
        pushDebug("calendar.fetch.success", { count:data?.length || 0 });
        setGpList(data);
      })
      .catch(err=>{
        pushDebug("calendar.fetch.error", String(err));
      });
  },[pushDebug]);

  useEffect(()=>{if(scrollRef.current)setTimeout(()=>{scrollRef.current.scrollTop=scrollRef.current.scrollHeight;},80);},[results,thinkBatch,chatMsgs,statusMsgs]);

  const w=ms=>new Promise(r=>setTimeout(r,ms));
  const moveTo=(zoneKeys)=>{
    const targets=zoneKeys.map(k=>ZONES.find(z=>z.key===k));
    const cx=targets.reduce((s,z)=>s+z.x+z.w/2,0)/targets.length;
    const cy=targets.reduce((s,z)=>s+z.y+z.h/2,0)/targets.length-6;
    setConPos({x:cx,y:cy});
  };

  const handleBatchDone=useCallback(()=>{
    setThinkBatch(null);
    if(resolveRef.current){resolveRef.current();resolveRef.current=null;}
  },[]);

  // ── Shared ws message handler (used by both plan and chat) ────────
  const prevResultsRef=useRef(null);
  const highlightTimeoutRef=useRef(null);
  const handleWsMsg=useCallback((evt)=>{
    const msg=JSON.parse(evt.data);
    pushDebug("ws.message", msg.type);
    if(msg.type==="message"){
      const agent=msg.data?.agent||"concierge";
      const text=msg.data?.text||"";
      setStatusMsgs(prev=>[...prev,{agent,text}]);
      setSpeaking(true);
      const agentToZone={ticket:"ticket",transport:"transport",hotel:"hotel",plan:"plan",tour:"tour",budget:"tour"};
      const zone=agentToZone[agent];
      if(zone){
        setZSt(prev=>({...prev,[zone]:"active"}));
        setTimeout(()=>setZSt(prev=>({...prev,[zone]:"done"})),800);
      }
    }
    if(msg.type==="result"){
      const d=msg.data;
      const transformed=transformResults(d);
      // Detect which cards changed (for highlight after refine)
      if(prevResultsRef.current){
        const changed=new Set();
        for(const key of Object.keys(transformed)){
          if(JSON.stringify(transformed[key])!==JSON.stringify(prevResultsRef.current[key])) changed.add(key);
        }
        if(changed.size>0){
          setUpdatedCards(changed);
          if(highlightTimeoutRef.current) clearTimeout(highlightTimeoutRef.current);
          highlightTimeoutRef.current=setTimeout(()=>{setUpdatedCards(new Set());highlightTimeoutRef.current=null;},3000);
        }
      }
      prevResultsRef.current=transformed;
      RESULTS=transformed;
      setLiveResults(transformed);
      setBudgetSummary(d.budget_summary);
      setResults(Object.keys(transformed));
    }
    if(msg.type==="reply"){
      setChatMsgs(prev=>[...prev,{from:"c",text:msg.data}]);
    }
    if(msg.type==="trace"){
      // Backend-emitted debug trace event (only when session opted in).
      // Render as a pushDebug line so it lives alongside existing UI traces.
      const ev=msg.data||{};
      const eventName=ev.event||"trace";
      pushDebug(`trace.${eventName}`, ev);
    }
    if(msg.type==="done"){
      setConPos(CONC_HOME);setSpeaking(true);setPhase("done");setPipeIdx(-1);
      setTimeout(()=>setSpeaking(false),400);
      setChatLoading(false);
    }
    if(msg.type==="error"){
      setChatMsgs(prev=>[...prev,{from:"c",text:`Error: ${msg.data}`}]);
      setPhase(prev=>prev==="running"?"done":prev);
      setSpeaking(false);setChatLoading(false);
    }
  },[pushDebug]);

  // ── Connect WebSocket (persistent, survives re-renders) ──────────
  const connectWs=useCallback(()=>{
    if(wsRef.current&&wsRef.current.readyState<=1) return wsRef.current;
    pushDebug("ws.connect.start", WS_URL);
    const ws=new WebSocket(WS_URL);
    wsRef.current=ws;
    ws.onmessage=handleWsMsg;
    ws.onopen=()=>{
      pushDebug("ws.open", WS_URL);
    };
    ws.onerror=()=>{
      pushDebug("ws.error", WS_URL);
      setChatMsgs(prev=>[...prev,{from:"c",text:"Connection error. Backend or WebSocket proxy is unreachable."}]);
      setPhase(prev=>prev==="running"?"done":prev);setSpeaking(false);
    };
    ws.onclose=(evt)=>{
      pushDebug("ws.close", { code:evt.code, reason:evt.reason || "", wasClean:evt.wasClean });
      wsRef.current=null;
    };
    return ws;
  },[handleWsMsg, pushDebug]);

  // ── WebSocket-driven planning run ────────────────────────────────
  const run=()=>{
    pushDebug("plan.run.click", {
      gp_name: gp?.gp_name || null,
      gp_city: gp?.city || null,
      gp_date: gp?.race_date || null,
      origin: form.origin || "New York",
      budget: +(form.budget || 2500),
      currency: form.currency,
      extra_days: form.extraDays,
    });
    cancelRef.current=false;setResults([]);setLiveResults({});setBudgetSummary(null);setSelections({});setUpdatedCards(new Set());
    prevResultsRef.current=null;
    setChatMsgs([]);setStatusMsgs([{agent:"concierge",text:"Welcome, VIP! Connecting to your team..."}]);setShowStatus(false);
    setPhase("running");setSpeaking(true);setPipeIdx(0);

    const ws=connectWs();
    const planPayload=JSON.stringify({type:"plan",data:{
      gp_name:gp.gp_name, gp_city:gp.city, gp_date:gp.race_date,
      origin:form.origin||"New York", budget:+(form.budget||2500),
      currency:form.currency||"EUR",
      stand_pref:form.stand, extra_days:form.extraDays,
      stops:form.stops, special_requests:form.special,
      debug:debugMode,
    }});

    if(ws.readyState===WebSocket.OPEN){
      pushDebug("plan.run.send.immediate", "OPEN");
      ws.send(planPayload);
    } else {
      pushDebug("plan.run.wait_open", ws.readyState);
      ws.addEventListener("open",()=>{
        pushDebug("plan.run.send.onopen", "OPEN");
        ws.send(planPayload);
      },{once:true});
    }
  };

  const reset=()=>{cancelRef.current=true;resolveRef.current=null;try{if(wsRef.current&&wsRef.current.readyState<=1)wsRef.current.close();}catch(e){}wsRef.current=null;setPhase("welcome");setZSt({});setConPos(CONC_HOME);setSpeaking(false);setThinkBatch(null);setResults([]);setLiveResults({});setBudgetSummary(null);setChatMsgs([]);setStatusMsgs([]);setShowStatus(false);setChatInput("");setPipeIdx(-1);setSelections({});setChatLoading(false);setUpdatedCards(new Set());prevResultsRef.current=null;};
  const backToSelect=()=>{reset();setScreen("select");setGp(null);};

  // ── WebSocket-driven chat ────────────────────────────────────────
  const wsAlive=()=>wsRef.current&&wsRef.current.readyState===WebSocket.OPEN;

  const handleChat=()=>{
    const t=chatInput.trim();if(!t)return;
    if(!wsAlive()){
      pushDebug("chat.blocked.no_ws");
      setChatMsgs(prev=>[...prev,{from:"c",text:"Connection lost. Please restart planning to continue."}]);
      return;
    }
    pushDebug("chat.send", t);
    setChatInput("");setChatLoading(true);
    setChatMsgs(prev=>[...prev,{from:"u",text:t}]);
    wsRef.current.send(JSON.stringify({type:"chat",data:t}));
    // Response handled by shared handleWsMsg via ws.onmessage
  };

  if(screen==="select") return(
    <div style={{background:"#0a0a0a",minHeight:"100vh",fontFamily:"'DM Sans',sans-serif",color:"#fff",padding:"20px 16px",maxWidth:680,margin:"0 auto"}}>
      <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet"/>
      <div style={{textAlign:"center",marginBottom:20}}>
        <PxChar type="concierge" size={56}/>
        <div style={{fontSize:10,letterSpacing:"0.2em",color:"#555",marginTop:8}}>FORMULA 1</div>
        <div style={{fontSize:22,fontWeight:700}}>PADDOCK CLUB</div>
        <div style={{fontSize:11,color:"#666",marginTop:2}}>Choose your Grand Prix</div>
        <div style={{width:40,height:2,background:"#E10600",margin:"10px auto 0",borderRadius:1}}/>
      </div>
      <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:8}}>
        {(gpList.length?gpList:[]).map((g,i)=>{
          const flag=FLAGS[g.country]||"\u{1F3C1}";
          const hero=HERO_COLORS[i%HERO_COLORS.length];
          const track=TRACK_MAP[g.gp_name]||TRACK_MAP["Italian GP"];
          const shortName=SHORT_NAMES[g.gp_name]||g.city;
          const dateStr=g.race_date?new Date(g.race_date+"T00:00:00").toLocaleDateString("en",{month:"short",day:"numeric"}):"TBD";
          return(
            <div key={g.gp_name} onClick={()=>{pushDebug("card.click", { gp:g.gp_name, is_past:g.is_past }); if(!g.is_past){
              setGp({...g,hero,track});setScreen("paddock");setPhase("welcome");
              // Auto-compute travel dates: arrive Friday of race week, depart day after extra days
              if(g.race_date){
                const rd=new Date(g.race_date+"T00:00:00");
                const dep=new Date(rd); dep.setDate(rd.getDate()-2); // Friday
                const ret=new Date(rd); ret.setDate(rd.getDate()+1+form.extraDays); // day after race + extra
                setForm(f=>({...f, departDate:dep.toISOString().slice(0,10), returnDate:ret.toISOString().slice(0,10)}));
              }
            }}} style={{
              padding:"12px 8px",borderRadius:10,cursor:g.is_past?"not-allowed":"pointer",background:g.is_past?"#0a0a0a":"#111",border:`1px solid ${g.is_past?"#1a1a1a":"#222"}`,
              display:"flex",flexDirection:"column",alignItems:"center",gap:4,transition:"all .2s",
              opacity:g.is_past?0.4:1,
            }} onMouseEnter={e=>{if(!g.is_past){e.currentTarget.style.borderColor=hero;e.currentTarget.style.transform="translateY(-2px)";}}}
               onMouseLeave={e=>{e.currentTarget.style.borderColor=g.is_past?"#1a1a1a":"#222";e.currentTarget.style.transform="translateY(0)";}}>
              <TrackSVG d={track} color={g.is_past?"#333":hero} size={44}/>
              <span style={{fontSize:16}}>{flag}</span>
              <div style={{fontSize:10,fontWeight:600,color:g.is_past?"#444":"#ccc",textAlign:"center"}}>{shortName}</div>
              <div style={{fontSize:8,color:g.is_past?"#333":"#555"}}>{g.is_past?"Concluded":dateStr}</div>
            </div>
          );
        })}
        {!gpList.length&&<div style={{gridColumn:"1/-1",textAlign:"center",color:"#555",fontSize:11,padding:20}}>Loading calendar... (is backend running?)</div>}
      </div>
      <style>{`@keyframes drawTrack{to{stroke-dashoffset:0}}`}</style>
    </div>
  );

  return(
    <div style={{background:"#0a0a0a",fontFamily:"'DM Sans',sans-serif",color:"#fff",maxWidth:680,margin:"0 auto",display:"flex",flexDirection:"column",height:"100vh",maxHeight:920,boxSizing:"border-box"}}>
      <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet"/>

      <div style={{padding:"8px 16px",borderBottom:"1px solid #1a1a1a",flexShrink:0,display:"flex",alignItems:"center",gap:8}}>
        <div onClick={backToSelect} style={{cursor:"pointer",color:"#555",fontSize:14}}>←</div>
        {gp&&<TrackSVG d={gp.track||TRACKS[0]} color={gp.hero||"#059669"} size={28}/>}
        <div style={{flex:1}}>
          <div style={{fontSize:13,fontWeight:700}}>{gp?`${FLAGS[gp.country]||""} ${SHORT_NAMES[gp.gp_name]||gp.city}`:"Paddock Club"}</div>
          {gp&&<div style={{fontSize:9,color:"#555"}}>{gp.gp_name} · {gp.race_date?new Date(gp.race_date+"T00:00:00").toLocaleDateString("en",{month:"short",day:"numeric"}):"TBD"}</div>}
        </div>
        {phase==="running"&&<div style={{display:"flex",gap:3,alignItems:"center"}}>{PIPELINE.map((_,i)=><div key={i} style={{width:16,height:3,borderRadius:2,background:i<=pipeIdx?"#E10600":"#222",transition:"all .3s"}}/>)}</div>}
        {phase!=="welcome"&&<button onClick={reset} style={{padding:"3px 8px",borderRadius:5,border:"1px solid #222",background:"transparent",color:"#555",fontSize:8,cursor:"pointer"}}>RESET</button>}
      </div>

      <div style={{position:"relative",width:"100%",paddingTop:"50%",background:"#0c0c0c",borderBottom:"1px solid #1a1a1a",flexShrink:0,overflow:"hidden"}}>
        <div style={{position:"absolute",inset:0,padding:"3%"}}>
          {ZONES.map(z=><Zone key={z.key} zone={z} status={zSt[z.key]||"idle"}/>)}
          <ConFloat x={conPos.x} y={conPos.y} speaking={speaking}/>
        </div>
      </div>

      <div ref={scrollRef} style={{flex:1,overflowY:"auto",padding:"10px 14px 6px",minHeight:0}}>

        {phase==="welcome"&&(
          <div style={{animation:"slideUp .4s ease-out"}}>
            <div style={{display:"flex",gap:8,alignItems:"flex-end",marginBottom:10}}>
              <PxChar type="concierge" size={36}/>
              <div style={{background:"#151515",border:"1px solid #E1060033",borderRadius:"4px 10px 10px 10px",padding:"8px 12px",flex:1}}>
                <div style={{fontSize:11.5,color:"#ccc",lineHeight:1.5}}>Welcome, VIP! Fill in your details and any special wishes.</div>
              </div>
            </div>

            <div style={{background:"#111",border:"1px solid #222",borderRadius:10,padding:"12px",marginBottom:10}}>
              <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:6,marginBottom:6}}>
                {[{l:"Flying from",k:"origin",p:"e.g. New York",t:"text"},{l:`Budget (${form.currency})`,k:"budget",p:"2500",t:"number"}].map(f=>(
                  <div key={f.k}>
                    <label style={{fontSize:8,color:"#555",display:"block",marginBottom:2}}>{f.l}</label>
                    <input value={form[f.k]} onChange={e=>setForm({...form,[f.k]:e.target.value})} placeholder={f.p} type={f.t}
                      style={{width:"100%",padding:"6px 9px",borderRadius:5,border:"1px solid #222",background:"#0a0a0a",color:"#eee",fontSize:11,outline:"none",fontFamily:"inherit",boxSizing:"border-box"}}
                      onFocus={e=>e.target.style.borderColor="#E10600"} onBlur={e=>e.target.style.borderColor="#222"}/>
                  </div>
                ))}
              </div>
              <div style={{marginBottom:6}}>
                <label style={{fontSize:8,color:"#555",display:"block",marginBottom:3}}>Currency <span style={{color:"#333"}}>(budget amount is interpreted in this unit)</span></label>
                <div style={{display:"flex",gap:3}}>
                  {["EUR","USD","CNY"].map(c=>(
                    <button key={c} onClick={()=>setForm({...form,currency:c})} style={{flex:1,padding:"4px",borderRadius:4,fontSize:9,fontWeight:600,cursor:"pointer",border:`1px solid ${form.currency===c?"#E10600":"#222"}`,background:form.currency===c?"#E1060015":"transparent",color:form.currency===c?"#E10600":"#555"}}>{c}</button>
                  ))}
                </div>
              </div>
              <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:6,marginBottom:6}}>
                <div>
                  <label style={{fontSize:8,color:"#555",display:"block",marginBottom:2}}>Suggested depart</label>
                  <input type="date" value={form.departDate} readOnly
                    title="Derived automatically from the GP race weekend"
                    style={{width:"100%",padding:"5px 9px",borderRadius:5,border:"1px solid #222",background:"#0f0f0f",color:"#999",fontSize:10,outline:"none",fontFamily:"inherit",boxSizing:"border-box",colorScheme:"dark",cursor:"default"}}
                  />
                </div>
                <div>
                  <label style={{fontSize:8,color:"#555",display:"block",marginBottom:2}}>Suggested return</label>
                  <input type="date" value={form.returnDate} readOnly
                    title="Derived from race day plus extra days"
                    style={{width:"100%",padding:"5px 9px",borderRadius:5,border:"1px solid #222",background:"#0f0f0f",color:"#999",fontSize:10,outline:"none",fontFamily:"inherit",boxSizing:"border-box",colorScheme:"dark",cursor:"default"}}
                  />
                </div>
              </div>
              <div style={{marginBottom:6}}>
                <label style={{fontSize:8,color:"#555",display:"block",marginBottom:3}}>Grandstand</label>
                <div style={{display:"flex",gap:3}}>
                  {[["any","Any"],["ga","GA"],["mid","Mid"],["vip","VIP"]].map(([v,l])=>(
                    <button key={v} onClick={()=>setForm({...form,stand:v})} style={{flex:1,padding:"4px",borderRadius:4,fontSize:9,fontWeight:600,cursor:"pointer",border:`1px solid ${form.stand===v?"#E10600":"#222"}`,background:form.stand===v?"#E1060015":"transparent",color:form.stand===v?"#E10600":"#555"}}>{l}</button>
                  ))}
                </div>
              </div>
              <div style={{marginBottom:6}}>
                <label style={{fontSize:8,color:"#555",display:"block",marginBottom:2}}>Extra days after race: {form.extraDays}</label>
                <input type="range" min="0" max="5" value={form.extraDays} onChange={e=>{
                  const ed=+e.target.value;
                  const newForm={...form,extraDays:ed};
                  if(gp?.race_date){const rd=new Date(gp.race_date+"T00:00:00");const ret=new Date(rd);ret.setDate(rd.getDate()+1+ed);newForm.returnDate=ret.toISOString().slice(0,10);}
                  setForm(newForm);
                }} style={{width:"100%",accentColor:"#E10600"}}/>
              </div>
              <div>
                <label style={{fontSize:8,color:"#555",display:"block",marginBottom:2}}>Special requests <span style={{color:"#333"}}>(optional)</span></label>
                <textarea value={form.special} onChange={e=>setForm({...form,special:e.target.value})}
                  placeholder="e.g. stop in Milan 2 days, vegetarian meals, pit walk, wheelchair access, Michelin restaurant..."
                  style={{width:"100%",padding:"6px 9px",borderRadius:5,border:"1px solid #222",background:"#0a0a0a",color:"#eee",fontSize:10.5,outline:"none",fontFamily:"inherit",boxSizing:"border-box",resize:"none",height:48,lineHeight:1.5}}
                  onFocus={e=>e.target.style.borderColor="#E10600"} onBlur={e=>e.target.style.borderColor="#222"}/>
              </div>
              <div style={{fontSize:8,color:"#555",lineHeight:1.5,marginTop:6}}>
                Describe any stops, dietary needs, accessibility, or experiences you want. After results, use the chat to refine.
              </div>
            </div>
            <button onClick={run} style={{width:"100%",padding:"11px",borderRadius:8,border:"none",background:"#E10600",color:"#fff",fontSize:12,fontWeight:700,cursor:"pointer",letterSpacing:"0.03em"}}>START PLANNING</button>
          </div>
        )}

        {thinkBatch&&<ThinkPanel zoneKeys={thinkBatch} onAllDone={handleBatchDone}/>}

        {/* Status messages during planning — collapsible after done */}
        {phase==="running"&&statusMsgs.map((m,i)=>(
          <div key={`s${i}`} style={{marginBottom:3,animation:"slideUp .2s ease-out"}}>
            <div style={{display:"flex",gap:5,alignItems:"flex-end"}}><PxChar type="concierge" size={14}/><div style={{padding:"4px 9px",borderRadius:"3px 7px 7px 7px",background:"#151515",border:"1px solid #1a1a1a",fontSize:9.5,color:"#666",maxWidth:"80%"}}>[{m.agent}] {m.text}</div></div>
          </div>
        ))}
        {phase==="done"&&statusMsgs.length>0&&(
          <div style={{marginBottom:6}}>
            <button onClick={()=>setShowStatus(!showStatus)} style={{fontSize:8,color:"#444",background:"none",border:"none",cursor:"pointer",padding:0,textDecoration:"underline"}}>
              {showStatus?"Hide":"Show"} planning trace ({statusMsgs.length} messages)
            </button>
            {showStatus&&<div style={{marginTop:4,padding:"6px 8px",background:"#0d0d0d",borderRadius:6,border:"1px solid #1a1a1a",maxHeight:120,overflowY:"auto"}}>
              {statusMsgs.map((m,i)=>(
                <div key={i} style={{fontSize:8,color:"#555",padding:"1px 0"}}>[{m.agent}] {m.text}</div>
              ))}
            </div>}
          </div>
        )}

        {/* Result cards — with highlight animation for updated cards after refine */}
        {results.map(key=>(
          <div key={key} style={{borderRadius:8,border:updatedCards.has(key)?"1px solid #E1060066":"1px solid transparent",transition:"border-color 0.5s",animation:updatedCards.has(key)?"cardPulse 1s ease-out":"none"}}>
            <ResultCard zoneKey={key} selections={selections} onSelect={(zone,arr)=>setSelections(prev=>({...prev,[zone]:arr}))} liveResults={liveResults}/>
          </div>
        ))}

        {phase==="done"&&budgetSummary&&(()=>{
          const bs=budgetSummary;
          const total=bs.total||0;
          const budget=bs.budget||+(form.budget||2500);
          const within=bs.within_budget;
          const items=bs.items||[];
          const cur=bs.currency||form.currency||"EUR";
          const sym=CUR_SYMBOL[cur]||(cur+" ");
          // Count unpriced items across all live zones so the breakdown
          // can surface how many options were excluded from the total.
          const unpricedCount=Object.values(liveResults||{}).reduce((n,zone)=>
            n + (zone.items||[]).filter(it=>it.priced===false && (zone.mode==="single"||zone.mode==="multi")).length, 0);
          return(
            <div style={{background:"#111",border:`1px solid ${within?"#22C55E33":"#EF444433"}`,borderRadius:8,padding:"10px 14px",marginBottom:6,animation:"cardSlide .4s ease-out"}}>
              <div style={{fontSize:9,color:"#666",marginBottom:6}}>Budget breakdown ({cur})</div>
              {items.map((it,i)=>(
                <div key={i} style={{display:"flex",justifyContent:"space-between",fontSize:10,color:"#aaa",padding:"2px 0"}}>
                  <span>{it.name}</span><span style={{color:"#ddd"}}>{sym}{Math.round(it.amount)}</span>
                </div>
              ))}
              <div style={{borderTop:"1px solid #222",marginTop:4,paddingTop:4}}>
                <div style={{display:"flex",justifyContent:"space-between",marginBottom:5}}>
                  <span style={{fontSize:9,color:"#888"}}>Estimated total</span>
                  <span style={{fontSize:13,fontWeight:700,color:within?"#22C55E":"#EF4444"}}>{sym}{Math.round(total).toLocaleString()} <span style={{fontSize:9,fontWeight:400,color:"#555"}}>/ {sym}{Math.round(budget).toLocaleString()}</span></span>
                </div>
                <div style={{height:4,borderRadius:2,background:"#1a1a1a",overflow:"hidden"}}>
                  <div style={{height:"100%",borderRadius:2,background:within?"linear-gradient(90deg,#22C55E,#4ADE80)":"linear-gradient(90deg,#EF4444,#F87171)",width:`${Math.min(total/budget*100,100)}%`,transition:"width .5s"}}/>
                </div>
                {bs.savings_tip&&<div style={{fontSize:8,color:"#EF4444",marginTop:4}}>{bs.savings_tip}</div>}
                {unpricedCount>0&&<div style={{fontSize:8,color:"#666",marginTop:4,fontStyle:"italic"}}>{unpricedCount} option{unpricedCount>1?"s":""} without prices excluded. Budget based on cheapest available.</div>}
                {unpricedCount===0&&<div style={{fontSize:8,color:"#444",marginTop:4,fontStyle:"italic"}}>Budget based on cheapest available options.</div>}
              </div>
            </div>
          );
        })()}

        {/* Refine chat conversation — only user messages and supervisor replies */}
        {chatMsgs.map((m,i)=>(
          <div key={i} style={{marginBottom:5,animation:"slideUp .2s ease-out"}}>
            {m.from==="u"?(
              <div style={{display:"flex",justifyContent:"flex-end"}}><div style={{padding:"5px 10px",borderRadius:"7px 7px 3px 7px",background:"#E10600",fontSize:10.5,color:"#fff",maxWidth:"75%"}}>{m.text}</div></div>
            ):(
              <div style={{display:"flex",gap:5,alignItems:"flex-end"}}><PxChar type="concierge" size={16}/><div style={{padding:"5px 10px",borderRadius:"3px 7px 7px 7px",background:"#151515",border:"1px solid #1f1f1f",fontSize:10.5,color:"#999",maxWidth:"75%"}}>{m.text}</div></div>
            )}
          </div>
        ))}
      </div>

      {phase==="done"&&(
        <div style={{padding:"6px 14px 10px",borderTop:"1px solid #1a1a1a",flexShrink:0,display:"flex",gap:6}}>
          <input value={chatInput} onChange={e=>setChatInput(e.target.value)} onKeyDown={e=>{if(e.key==="Enter"){e.preventDefault();handleChat();}}}
            placeholder="Refine this plan... (e.g. cheaper hotels, direct flights only)" disabled={chatLoading}
            style={{flex:1,padding:"7px 10px",borderRadius:7,border:"1px solid #222",background:"#111",color:"#eee",fontSize:11,outline:"none",fontFamily:"inherit",opacity:chatLoading?0.5:1}}
            onFocus={e=>e.target.style.borderColor="#E10600"} onBlur={e=>e.target.style.borderColor="#222"}/>
          <button onClick={handleChat} disabled={!chatInput.trim()||chatLoading} style={{padding:"7px 12px",borderRadius:7,border:"none",background:chatInput.trim()&&!chatLoading?"#E10600":"#222",color:chatInput.trim()&&!chatLoading?"#fff":"#555",fontSize:10,fontWeight:600,cursor:chatInput.trim()&&!chatLoading?"pointer":"not-allowed"}}>{chatLoading?"...":"GO"}</button>
        </div>
      )}

      {debugMode&&(
        <div style={{padding:"6px 14px 10px",borderTop:"1px solid #141414",background:"#0b0b0b",flexShrink:0}}>
          <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:4}}>
            <div style={{fontSize:8,color:"#555"}}>Debug trace</div>
            <button onClick={async()=>{
              try{
                await navigator.clipboard.writeText(debugLog.join("\n"));
                setCopyStatus("copied");
              }catch(e){
                setCopyStatus("failed");
              }
              setTimeout(()=>setCopyStatus("copy"),1500);
            }} style={{fontSize:7,color:copyStatus==="failed"?"#EF4444":"#555",background:"#1a1a1a",border:"1px solid #333",borderRadius:3,padding:"1px 6px",cursor:"pointer"}}>{copyStatus}</button>
          </div>
          <div style={{maxHeight:88,overflowY:"auto",fontSize:8,color:"#777",fontFamily:"ui-monospace, SFMono-Regular, Consolas, monospace",lineHeight:1.5}}>
            {debugLog.length
              ? debugLog.map((line,i)=><div key={i}>{line}</div>)
              : <div>No events yet.</div>}
          </div>
        </div>
      )}

      <style>{`
        @keyframes slideUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
        @keyframes blink{0%,100%{opacity:1}50%{opacity:0}}
        @keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(1.5)}}
        @keyframes cBounce{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}
        @keyframes cardSlide{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:translateY(0)}}
        @keyframes cardPulse{0%{border-color:#E10600}50%{border-color:#E1060066}100%{border-color:transparent}}
        @keyframes drawTrack{to{stroke-dashoffset:0}}
        ::-webkit-scrollbar{width:4px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:#333;border-radius:4px}
      `}</style>
    </div>
  );
}
