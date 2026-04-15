import { useState, useEffect, useRef, useCallback } from "react";

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
const API_BASE = "http://localhost:8000";
const WS_URL = "ws://localhost:8000/ws";

// ── Transform backend data into card format ────────────────────────
function transformResults(data) {
  const r = {};
  if (data.tickets?.length) {
    r.ticket = { mode:"single", bookLabel:"Book tickets", bookIcon:"🎫", items:
      data.tickets.filter(t=>t.tag!=="INFO").map(t=>({
        tag:t.tag||"PICK", main:t.name||"Ticket", sub:t.section||"",
        price:`${t.currency||"EUR"} ${t.price}`, pv:t.price||0, link:t.link||"",
      }))
    };
  }
  if (data.transport?.length) {
    r.transport = { mode:"multi", bookLabel:"Book flights", bookIcon:"✈", items:
      data.transport.filter(t=>t.tag!=="INFO").map(t=>({
        tag:t.tag||"OUT", main:t.summary||"Flight", sub:t.detail||"",
        price:`${t.currency||"USD"} ${t.price}`, pv:t.price||0, link:t.link||"",
      }))
    };
  }
  if (data.hotel?.length) {
    r.hotel = { mode:"single", bookLabel:"Book hotel", bookIcon:"🏨", items:
      data.hotel.filter(h=>h.tag!=="INFO").map(h=>({
        tag:h.tag||"NEAR", main:h.name||"Hotel",
        sub:`${h.distance||""} · ${h.rating||""}★ · ${h.nights||"?"}n`,
        price:`${h.currency||"USD"} ${h.price_per_night}/n`, pv:h.price_per_night||0, link:h.link||"",
      }))
    };
  }
  if (data.itinerary?.length) {
    r.plan = { mode:"none", items:
      data.itinerary.map((line,i)=>{
        const m = line.match(/^Day\s*\d+\s*\((\w+)\):\s*(.+)/i);
        return { tag:m?m[1].substring(0,3).toUpperCase():`D${i+1}`, main:m?m[2]:line, sub:"", price:"" };
      })
    };
  }
  if (data.tour?.length) {
    r.tour = { mode:"multi", bookLabel:"Book activities", bookIcon:"🗺", items:
      data.tour.map(line=>{
        const m = line.match(/^(.+?)\s*\(([^)]+)\)\s*[—–-]\s*(.+)/);
        return m
          ? { tag:"REC", main:m[1].replace(/^[^\w]+/,""), sub:m[3], price:m[2], pv:parseInt(m[2])||0 }
          : { tag:"REC", main:line.substring(0,40), sub:line.substring(40), price:"", pv:0 };
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

function ResultCard({zoneKey,selections,onSelect,liveResults}){
  const z=ZONES.find(z=>z.key===zoneKey);
  const data=(liveResults||RESULTS)[zoneKey];
  if(!data||!data.items?.length) return null;
  const{mode,items,bookLabel,bookIcon}=data;
  const sel=selections[zoneKey]||[];
  const hasSelection=sel.length>0;
  const selectedTotal=sel.reduce((s,idx)=>(items[idx]?.pv||0)+s,0);
  const bookableItems=sel.filter(idx=>items[idx]?.link);

  const toggle=(idx)=>{
    if(mode==="none")return;
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
        {hasSelection&&<span style={{marginLeft:"auto",fontSize:8,fontWeight:600,color:z.color}}>€{selectedTotal}</span>}
        {!hasSelection&&<div style={{marginLeft:"auto",width:4,height:4,borderRadius:"50%",background:z.color,boxShadow:`0 0 5px ${z.color}`}}/>}
      </div>
      {items.map((it,i)=>{
        const isSel=sel.includes(i);
        const clickable=mode!=="none";
        const isRadio=mode==="single";
        return(
          <div key={i} onClick={()=>toggle(i)}
            style={{display:"flex",alignItems:"center",gap:6,padding:"5px 10px",borderBottom:i<items.length-1?"1px solid #1a1a1a":"none",
              cursor:clickable?"pointer":"default",
              background:isSel?z.color+"12":"transparent",
              borderLeft:isSel?`2px solid ${z.color}`:"2px solid transparent",
              transition:"all .15s",
            }}>
            {clickable&&<div style={{width:12,height:12,borderRadius:isRadio?"50%":3,border:`1.5px solid ${isSel?z.color:"#333"}`,background:isSel?z.color:"transparent",display:"flex",alignItems:"center",justifyContent:"center",flexShrink:0,transition:"all .15s"}}>
              {isSel&&<span style={{fontSize:8,color:"#fff",lineHeight:1}}>✓</span>}
            </div>}
            <span style={{fontSize:7,fontWeight:700,color:z.color,background:z.color+"15",padding:"1px 4px",borderRadius:3,minWidth:30,textAlign:"center"}}>{it.tag}</span>
            <div style={{flex:1,minWidth:0}}>
              <div style={{fontSize:10.5,fontWeight:500,color:"#ddd"}}>{it.main}</div>
              {it.sub&&<div style={{fontSize:9,color:"#555"}}>{it.sub}</div>}
            </div>
            {it.price&&<span style={{fontSize:10.5,fontWeight:600,color:isSel?"#fff":"#888"}}>{it.price}</span>}
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
          <div style={{fontSize:8,color:"#444",textAlign:"center",marginTop:3}}>Opens booking site with your dates pre-filled</div>
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
// Generic track SVGs — one per GP would be ideal, but these cover the demo
const TRACKS=["M40,75 L35,30 Q38,15 50,12 Q62,10 68,25 L72,50 Q75,65 65,75 Q55,80 40,75Z","M35,30 Q45,15 60,20 L70,35 Q75,50 65,60 L50,70 Q35,75 30,60 L35,30Z","M25,45 Q30,20 50,15 Q70,12 80,30 Q85,45 78,60 Q65,75 45,78 Q25,70 25,45Z","M25,50 Q30,20 50,15 Q65,12 75,25 L80,45 Q82,60 70,70 Q55,78 40,75 Q25,65 25,50Z","M30,35 L65,20 Q80,25 75,40 L60,50 Q55,55 60,65 L40,75 Q25,70 25,55 L30,35Z","M30,30 L70,25 Q82,30 80,45 L75,60 Q70,72 55,75 L35,70 Q22,65 25,45Z"];

function TrackSVG({d,color,size=44}){
  return <svg width={size} height={size} viewBox="0 0 100 90"><path d={d} fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" opacity={0.6} style={{strokeDasharray:300,strokeDashoffset:300,animation:"drawTrack 1.5s ease-out forwards"}}/></svg>;
}

export default function App(){
  const[screen,setScreen]=useState("select");
  const[gpList,setGpList]=useState([]);
  const[gp,setGp]=useState(null);
  const[phase,setPhase]=useState("welcome");
  const[form,setForm]=useState({origin:"",budget:"2500",stand:"any",extraDays:2,special:"",stops:""});
  const[zSt,setZSt]=useState({});
  const[conPos,setConPos]=useState(CONC_HOME);
  const[speaking,setSpeaking]=useState(false);
  const[thinkBatch,setThinkBatch]=useState(null);
  const[results,setResults]=useState([]);
  const[liveResults,setLiveResults]=useState({});
  const[budgetSummary,setBudgetSummary]=useState(null);
  const[chatInput,setChatInput]=useState("");
  const[chatMsgs,setChatMsgs]=useState([]);
  const[chatLoading,setChatLoading]=useState(false);
  const[pipeIdx,setPipeIdx]=useState(-1);
  const[selections,setSelections]=useState({});
  const cancelRef=useRef(false);
  const scrollRef=useRef(null);
  const resolveRef=useRef(null);
  const wsRef=useRef(null);

  // Fetch GP calendar from backend on mount
  useEffect(()=>{
    fetch(`${API_BASE}/api/calendar`).then(r=>r.json()).then(setGpList).catch(()=>{});
  },[]);

  useEffect(()=>{if(scrollRef.current)setTimeout(()=>{scrollRef.current.scrollTop=scrollRef.current.scrollHeight;},80);},[results,thinkBatch,chatMsgs]);

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

  // ── WebSocket-driven planning run ────────────────────────────────
  const run=async()=>{
    cancelRef.current=false;setResults([]);setLiveResults({});setBudgetSummary(null);setSelections({});
    setChatMsgs([{from:"c",text:"Welcome, VIP! Connecting to your team..."}]);
    setPhase("running");setSpeaking(true);

    // Open WebSocket
    const ws=new WebSocket(WS_URL);
    wsRef.current=ws;
    let pipelineStep=0;

    ws.onopen=()=>{
      ws.send(JSON.stringify({type:"plan",data:{
        gp_name:gp.gp_name, gp_city:gp.city, gp_date:gp.race_date,
        origin:form.origin||"New York", budget:+(form.budget||2500),
        stand_pref:form.stand, extra_days:form.extraDays,
        stops:form.stops, special_requests:form.special,
      }}));
    };

    ws.onmessage=(evt)=>{
      const msg=JSON.parse(evt.data);
      if(msg.type==="message"){
        const agent=msg.data?.agent||"concierge";
        const text=msg.data?.text||"";
        setChatMsgs(prev=>[...prev,{from:"c",text:`[${agent}] ${text}`}]);
        setSpeaking(true);
        // Drive zone animation based on agent name
        const agentToZone={ticket:"ticket",transport:"transport",hotel:"hotel",plan:"plan",tour:"tour",budget:"tour"};
        const zone=agentToZone[agent];
        if(zone){
          setZSt(prev=>({...prev,[zone]:"active"}));
          setTimeout(()=>setZSt(prev=>({...prev,[zone]:"done"})),800);
        }
        // Advance pipeline progress bar
        if(agent==="ticket"&&pipelineStep<1){pipelineStep=0;setPipeIdx(0);}
        if((agent==="transport"||agent==="hotel")&&pipelineStep<2){pipelineStep=1;setPipeIdx(1);}
        if((agent==="plan"||agent==="tour")&&pipelineStep<3){pipelineStep=2;setPipeIdx(2);}
      }
      if(msg.type==="result"){
        const d=msg.data;
        const transformed=transformResults(d);
        RESULTS=transformed;
        setLiveResults(transformed);
        setBudgetSummary(d.budget_summary);
        setResults(Object.keys(transformed));
      }
      if(msg.type==="done"){
        setConPos(CONC_HOME);setSpeaking(true);setPhase("done");setPipeIdx(-1);
        const bs=budgetSummary;
        // Budget message will use latest state
        setChatMsgs(prev=>[...prev,{from:"c",text:"All done! Review your plan below and adjust anything in chat."}]);
        setTimeout(()=>setSpeaking(false),400);
      }
      if(msg.type==="error"){
        setChatMsgs(prev=>[...prev,{from:"c",text:`Error: ${msg.data}`}]);
        setPhase("done");setSpeaking(false);
      }
    };

    ws.onerror=()=>{
      setChatMsgs(prev=>[...prev,{from:"c",text:"Connection error. Is the backend running on localhost:8000?"}]);
      setPhase("done");setSpeaking(false);
    };
  };

  const reset=()=>{cancelRef.current=true;resolveRef.current=null;if(wsRef.current)wsRef.current.close();wsRef.current=null;setPhase("welcome");setZSt({});setConPos(CONC_HOME);setSpeaking(false);setThinkBatch(null);setResults([]);setLiveResults({});setBudgetSummary(null);setChatMsgs([]);setChatInput("");setPipeIdx(-1);setSelections({});setChatLoading(false);};
  const backToSelect=()=>{reset();setScreen("select");setGp(null);};

  // ── WebSocket-driven chat ────────────────────────────────────────
  const handleChat=()=>{
    const t=chatInput.trim();if(!t)return;
    setChatInput("");setChatLoading(true);
    setChatMsgs(prev=>[...prev,{from:"u",text:t}]);

    const ws=wsRef.current;
    if(!ws||ws.readyState!==WebSocket.OPEN){
      // Reconnect if ws closed
      const newWs=new WebSocket(WS_URL);
      wsRef.current=newWs;
      newWs.onopen=()=>{newWs.send(JSON.stringify({type:"chat",data:t}));};
      newWs.onmessage=(evt)=>{
        const msg=JSON.parse(evt.data);
        if(msg.type==="reply"){
          setChatMsgs(prev=>[...prev,{from:"c",text:msg.data}]);
        }
        if(msg.type==="result"){
          const transformed=transformResults(msg.data);
          RESULTS=transformed;
          setLiveResults(transformed);
          setBudgetSummary(msg.data.budget_summary);
          setResults(Object.keys(transformed));
        }
        if(msg.type==="done")setChatLoading(false);
        if(msg.type==="error"){setChatMsgs(prev=>[...prev,{from:"c",text:msg.data}]);setChatLoading(false);}
      };
      return;
    }
    ws.send(JSON.stringify({type:"chat",data:t}));
    // Response handled by existing ws.onmessage — but we need chat-specific handling
    const origHandler=ws.onmessage;
    ws.onmessage=(evt)=>{
      const msg=JSON.parse(evt.data);
      if(msg.type==="reply"){
        setChatMsgs(prev=>[...prev,{from:"c",text:msg.data}]);
      }
      if(msg.type==="result"){
        const transformed=transformResults(msg.data);
        RESULTS=transformed;
        setLiveResults(transformed);
        setBudgetSummary(msg.data.budget_summary);
        setResults(Object.keys(transformed));
      }
      if(msg.type==="done"){setChatLoading(false);ws.onmessage=origHandler;}
      if(msg.type==="message"){
        setChatMsgs(prev=>[...prev,{from:"c",text:msg.data?.text||""}]);
      }
      if(msg.type==="error"){setChatMsgs(prev=>[...prev,{from:"c",text:msg.data}]);setChatLoading(false);ws.onmessage=origHandler;}
    };
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
          const track=TRACKS[i%TRACKS.length];
          const dateStr=g.race_date?new Date(g.race_date+"T00:00:00").toLocaleDateString("en",{month:"short",day:"numeric"}):"TBD";
          return(
            <div key={g.gp_name} onClick={()=>{setGp({...g,hero,track});setScreen("paddock");setPhase("welcome");}} style={{
              padding:"12px 8px",borderRadius:10,cursor:"pointer",background:g.is_past?"#0a0a0a":"#111",border:`1px solid ${g.is_past?"#1a1a1a":"#222"}`,
              display:"flex",flexDirection:"column",alignItems:"center",gap:4,transition:"all .2s",
              opacity:g.is_past?0.5:1,
            }} onMouseEnter={e=>{if(!g.is_past){e.currentTarget.style.borderColor=hero;e.currentTarget.style.transform="translateY(-2px)";}}}
               onMouseLeave={e=>{e.currentTarget.style.borderColor=g.is_past?"#1a1a1a":"#222";e.currentTarget.style.transform="translateY(0)";}}>
              <TrackSVG d={track} color={hero} size={44}/>
              <span style={{fontSize:16}}>{flag}</span>
              <div style={{fontSize:10,fontWeight:600,color:g.is_past?"#555":"#ccc",textAlign:"center"}}>{g.city}</div>
              <div style={{fontSize:8,color:g.is_past?"#333":"#555"}}>{dateStr}{g.is_past?" (past)":""}</div>
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
          <div style={{fontSize:13,fontWeight:700}}>{gp?`${FLAGS[gp.country]||""} ${gp.gp_name}`:"Paddock Club"}</div>
          {gp&&<div style={{fontSize:9,color:"#555"}}>{gp.city} · {gp.race_date?new Date(gp.race_date+"T00:00:00").toLocaleDateString("en",{month:"short",day:"numeric"}):"TBD"}</div>}
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
                {[{l:"Flying from",k:"origin",p:"e.g. New York",t:"text"},{l:"Budget (€)",k:"budget",p:"2500",t:"number"}].map(f=>(
                  <div key={f.k}>
                    <label style={{fontSize:8,color:"#555",display:"block",marginBottom:2}}>{f.l}</label>
                    <input value={form[f.k]} onChange={e=>setForm({...form,[f.k]:e.target.value})} placeholder={f.p} type={f.t}
                      style={{width:"100%",padding:"6px 9px",borderRadius:5,border:"1px solid #222",background:"#0a0a0a",color:"#eee",fontSize:11,outline:"none",fontFamily:"inherit",boxSizing:"border-box"}}
                      onFocus={e=>e.target.style.borderColor="#E10600"} onBlur={e=>e.target.style.borderColor="#222"}/>
                  </div>
                ))}
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
                <label style={{fontSize:8,color:"#555",display:"block",marginBottom:2}}>Extra days: {form.extraDays}</label>
                <input type="range" min="0" max="5" value={form.extraDays} onChange={e=>setForm({...form,extraDays:+e.target.value})} style={{width:"100%",accentColor:"#E10600"}}/>
              </div>
              <div>
                <label style={{fontSize:8,color:"#555",display:"block",marginBottom:2}}>Stops along the way <span style={{color:"#333"}}>(optional)</span></label>
                <input value={form.stops} onChange={e=>setForm({...form,stops:e.target.value})}
                  placeholder="e.g. Milan 2 days → Lake Como → Monza"
                  style={{width:"100%",padding:"6px 9px",borderRadius:5,border:"1px solid #222",background:"#0a0a0a",color:"#eee",fontSize:10.5,outline:"none",fontFamily:"inherit",boxSizing:"border-box"}}
                  onFocus={e=>e.target.style.borderColor="#E10600"} onBlur={e=>e.target.style.borderColor="#222"}/>
              </div>
              <div>
                <label style={{fontSize:8,color:"#555",display:"block",marginBottom:2}}>Special requests <span style={{color:"#333"}}>(optional)</span></label>
                <textarea value={form.special} onChange={e=>setForm({...form,special:e.target.value})}
                  placeholder="Wheelchair access, vegetarian, Michelin restaurant, want pit walk experience..."
                  style={{width:"100%",padding:"6px 9px",borderRadius:5,border:"1px solid #222",background:"#0a0a0a",color:"#eee",fontSize:10.5,outline:"none",fontFamily:"inherit",boxSizing:"border-box",resize:"none",height:40,lineHeight:1.5}}
                  onFocus={e=>e.target.style.borderColor="#E10600"} onBlur={e=>e.target.style.borderColor="#222"}/>
              </div>
            </div>
            <button onClick={run} style={{width:"100%",padding:"11px",borderRadius:8,border:"none",background:"#E10600",color:"#fff",fontSize:12,fontWeight:700,cursor:"pointer",letterSpacing:"0.03em"}}>START PLANNING</button>
          </div>
        )}

        {thinkBatch&&<ThinkPanel zoneKeys={thinkBatch} onAllDone={handleBatchDone}/>}

        {results.map(key=><ResultCard key={key} zoneKey={key} selections={selections} onSelect={(zone,arr)=>setSelections(prev=>({...prev,[zone]:arr}))} liveResults={liveResults}/>)}

        {phase==="done"&&budgetSummary&&(()=>{
          const bs=budgetSummary;
          const total=bs.total||0;
          const budget=bs.budget||+(form.budget||2500);
          const within=bs.within_budget;
          const items=bs.items||[];
          return(
            <div style={{background:"#111",border:`1px solid ${within?"#22C55E33":"#EF444433"}`,borderRadius:8,padding:"10px 14px",marginBottom:6,animation:"cardSlide .4s ease-out"}}>
              <div style={{fontSize:9,color:"#666",marginBottom:6}}>Budget breakdown (EUR)</div>
              {items.map((it,i)=>(
                <div key={i} style={{display:"flex",justifyContent:"space-between",fontSize:10,color:"#aaa",padding:"2px 0"}}>
                  <span>{it.name}</span><span style={{color:"#ddd"}}>€{Math.round(it.amount)}</span>
                </div>
              ))}
              <div style={{borderTop:"1px solid #222",marginTop:4,paddingTop:4}}>
                <div style={{display:"flex",justifyContent:"space-between",marginBottom:5}}>
                  <span style={{fontSize:9,color:"#888"}}>Estimated total</span>
                  <span style={{fontSize:13,fontWeight:700,color:within?"#22C55E":"#EF4444"}}>€{Math.round(total).toLocaleString()} <span style={{fontSize:9,fontWeight:400,color:"#555"}}>/ €{Math.round(budget).toLocaleString()}</span></span>
                </div>
                <div style={{height:4,borderRadius:2,background:"#1a1a1a",overflow:"hidden"}}>
                  <div style={{height:"100%",borderRadius:2,background:within?"linear-gradient(90deg,#22C55E,#4ADE80)":"linear-gradient(90deg,#EF4444,#F87171)",width:`${Math.min(total/budget*100,100)}%`,transition:"width .5s"}}/>
                </div>
                {bs.savings_tip&&<div style={{fontSize:8,color:"#EF4444",marginTop:4}}>{bs.savings_tip}</div>}
              </div>
            </div>
          );
        })()}

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

      {phase!=="welcome"&&(
        <div style={{padding:"6px 14px 10px",borderTop:"1px solid #1a1a1a",flexShrink:0,display:"flex",gap:6}}>
          <input value={chatInput} onChange={e=>setChatInput(e.target.value)} onKeyDown={e=>{if(e.key==="Enter"){e.preventDefault();handleChat();}}}
            placeholder="Adjust your plan... (e.g. cheaper hotels, direct flights only)" disabled={chatLoading}
            style={{flex:1,padding:"7px 10px",borderRadius:7,border:"1px solid #222",background:"#111",color:"#eee",fontSize:11,outline:"none",fontFamily:"inherit",opacity:chatLoading?0.5:1}}
            onFocus={e=>e.target.style.borderColor="#E10600"} onBlur={e=>e.target.style.borderColor="#222"}/>
          <button onClick={handleChat} disabled={!chatInput.trim()||chatLoading} style={{padding:"7px 12px",borderRadius:7,border:"none",background:chatInput.trim()&&!chatLoading?"#E10600":"#222",color:chatInput.trim()&&!chatLoading?"#fff":"#555",fontSize:10,fontWeight:600,cursor:chatInput.trim()&&!chatLoading?"pointer":"not-allowed"}}>{chatLoading?"...":"GO"}</button>
        </div>
      )}

      <style>{`
        @keyframes slideUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
        @keyframes blink{0%,100%{opacity:1}50%{opacity:0}}
        @keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(1.5)}}
        @keyframes cBounce{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}
        @keyframes cardSlide{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:translateY(0)}}
        @keyframes drawTrack{to{stroke-dashoffset:0}}
        ::-webkit-scrollbar{width:4px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:#333;border-radius:4px}
      `}</style>
    </div>
  );
}
