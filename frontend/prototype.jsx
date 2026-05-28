import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import {
  AGENT_TO_BATCH,
  CONC_HOME,
  PIPELINE,
} from "./domain/planningConstants.js";
import { constraintLabels, RATIONALE_FIXTURES } from "./domain/display.js";
import { defaultTripDates } from "./domain/tripDates.js";
import { transformResults } from "./domain/transformResults.js";
import { AppHeader, DebugTrace, PaddockMap } from "./components/AppChrome.jsx";
import { BudgetPanel } from "./components/BudgetPanel.jsx";
import { ChatInput, ChatMessages } from "./components/ChatPanel.jsx";
import { ExplainabilityPanel } from "./components/ExplainabilityPanel.jsx";
import { GpSelect } from "./components/GpSelect.jsx";
import { PxChar } from "./components/PaddockVisuals.jsx";
import { ResultCard } from "./components/ResultCard.jsx";
import { ThinkPanel } from "./components/ThinkPanel.jsx";
import { WelcomeForm } from "./components/WelcomeForm.jsx";
import UserMenu from "./components/UserMenu.jsx";
import SavedTrips from "./components/SavedTrips.jsx";
import { useBackendToken, useDemoToken } from "./hooks/useBackendToken.js";

// ── Backend connection config ───────────────────────────────────────
const cleanBase=(url)=>(url||"").replace(/\/+$/,"");
const API_BASE=cleanBase(import.meta.env.VITE_BACKEND_URL||"");
const DEFAULT_WS_URL=`${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws`;
const RAW_WS_URL=import.meta.env.VITE_WS_URL||DEFAULT_WS_URL;
const HAS_CLERK = !!import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;
const redactToken=(url)=>url.replace(/(?:demo_)?token=[^&]+/,"token=***");

export default function App(){
  // HAS_CLERK is a build-time constant from import.meta.env, so the
  // hook choice here is stable across the bundle's lifetime — safe
  // against Rules of Hooks even though the call is conditional.
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const { getToken } = HAS_CLERK ? useBackendToken() : useDemoToken();
  const buildAuthHeaders = useCallback(async () => {
    const tok = await getToken();
    return tok ? { Authorization: `Bearer ${tok}` } : {};
  }, [getToken]);
  const buildWsUrl = useCallback(async () => {
    const tok = await getToken();
    if (!tok) return RAW_WS_URL;
    const sep = RAW_WS_URL.includes("?") ? "&" : "?";
    // Backend accepts both 'token' (Clerk JWT) and legacy 'demo_token'.
    const param = HAS_CLERK ? "token" : "demo_token";
    return `${RAW_WS_URL}${sep}${param}=${encodeURIComponent(tok)}`;
  }, [getToken]);

  const debugMode=useMemo(()=>new URLSearchParams(window.location.search).has("debug"),[]);
  const explainDemoMode=useMemo(()=>{
    const v=new URLSearchParams(window.location.search).get("explain");
    return v==="demo";
  },[]);
  const [explainState,setExplainState]=useState(null);
  const showExplain=useCallback((zoneKey,item)=>{
    const rationale=item?.rationale||(explainDemoMode?(RATIONALE_FIXTURES[zoneKey==="transport"?"flight":zoneKey]||null):null);
    if(!rationale)return;
    setExplainState({zoneKey,item,rationale});
  },[explainDemoMode]);
  const closeExplain=useCallback(()=>setExplainState(null),[]);
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
  const[baselineBudgetSummary,setBaselineBudgetSummary]=useState(null);
  const[activeConstraints,setActiveConstraints]=useState({});
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
  const[showSavedTrips,setShowSavedTrips]=useState(false);
  const[saveStatus,setSaveStatus]=useState(null);
  const cancelRef=useRef(false);
  const scrollRef=useRef(null);
  const resolveRef=useRef(null);
  const wsRef=useRef(null);
  const quoteSeqRef=useRef(0);

  const pushDebug=useCallback((label, data) => {
    const stamp = new Date().toLocaleTimeString("en-GB", { hour12: false });
    const line = data === undefined ? `${stamp} ${label}` : `${stamp} ${label} ${typeof data === "string" ? data : JSON.stringify(data)}`;
    console.log("[demo-debug]", line);
    setDebugLog(prev => [...prev.slice(-19), line]);
  }, []);

  // Fetch GP calendar from backend on mount
  useEffect(()=>{
    let cancelled = false;
    const calendarUrl=`${API_BASE||window.location.origin}/api/calendar`;
    pushDebug("calendar.fetch.start", calendarUrl);
    (async () => {
      try {
        const headers = await buildAuthHeaders();
        const r = await fetch(`${API_BASE}/api/calendar`, { headers });
        pushDebug("calendar.fetch.response", { status:r.status, ok:r.ok });
        const data = await r.json();
        if (cancelled) return;
        pushDebug("calendar.fetch.success", { count:data?.length || 0 });
        setGpList(data);
      } catch (err) {
        if (!cancelled) pushDebug("calendar.fetch.error", String(err));
      }
    })();
    return () => { cancelled = true; };
  },[pushDebug, buildAuthHeaders]);

  useEffect(()=>{if(scrollRef.current)setTimeout(()=>{scrollRef.current.scrollTop=scrollRef.current.scrollHeight;},80);},[results,thinkBatch,chatMsgs,statusMsgs]);

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
      const batchIdx=AGENT_TO_BATCH[agent];
      if(batchIdx!==undefined){
        setPipeIdx(prev=>Math.max(prev,batchIdx));
        setThinkBatch(prev=>{
          const target=PIPELINE[batchIdx].zones;
          const same=prev&&prev.length===target.length&&prev.every((z,i)=>z===target[i]);
          return same?prev:target;
        });
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
      setLiveResults(transformed);
      setBaselineBudgetSummary(d.budget_summary);
      setBudgetSummary(d.budget_summary);
      setActiveConstraints(d.active_constraints||{});
      setResults(Object.keys(transformed));
    }
    if(msg.type==="quote"){
      const d=msg.data||{};
      if(d.quote_id&&d.quote_id!==quoteSeqRef.current)return;
      setBudgetSummary(d.budget_summary||baselineBudgetSummary);
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
    if(msg.type==="save_trip_ack"){
      setSaveStatus({ok:true, id:msg.data?.id, ts:Date.now()});
      setTimeout(()=>setSaveStatus(prev=>prev&&Date.now()-prev.ts>2500?null:prev), 3000);
    }
    if(msg.type==="trip_loaded"){
      const d=msg.data||{};
      const snap=d.plan_snapshot||{};
      try{
        // Saved shape is {ticket?, transport?, hotel?, itinerary?, tour?,
        // selections?, activeConstraints?} — same as liveResults plus side
        // metadata. Restore the zone keys, then set selections/constraints
        // from either the snapshot or the top-level trip fields.
        const zoneKeys=["ticket","transport","hotel","itinerary","tour"]
          .filter(k=>snap[k]&&typeof snap[k]==="object");
        if(zoneKeys.length){
          const live={};
          for(const k of zoneKeys) live[k]=snap[k];
          setLiveResults(live);
          setResults(zoneKeys);
        }
        if(snap.selections) setSelections(snap.selections);
      }catch(e){
        pushDebug("trip_loaded.error", String(e));
      }
      if(d.budget_summary){
        setBudgetSummary(d.budget_summary);
        setBaselineBudgetSummary(d.budget_summary);
      }
      if(d.active_constraints) setActiveConstraints(d.active_constraints);
      else if(snap.activeConstraints) setActiveConstraints(snap.activeConstraints);
      setPhase("done");
      setShowSavedTrips(false);
      setStatusMsgs([{agent:"concierge",text:`Loaded saved trip: ${d.gp_slug}`}]);
    }
  },[pushDebug]);

  // ── Connect WebSocket (persistent, survives re-renders) ──────────
  // Token resolution is async, so connectWs is async. Callers await it
  // before using the returned WebSocket.
  const connectWs=useCallback(async ()=>{
    if(wsRef.current&&wsRef.current.readyState<=1) return wsRef.current;
    const wsUrl = await buildWsUrl();
    const wsLogUrl = redactToken(wsUrl);
    pushDebug("ws.connect.start", wsLogUrl);
    const ws=new WebSocket(wsUrl);
    wsRef.current=ws;
    ws.onmessage=handleWsMsg;
    ws.onopen=()=>{
      pushDebug("ws.open", wsLogUrl);
    };
    ws.onerror=()=>{
      pushDebug("ws.error", wsLogUrl);
      setChatMsgs(prev=>[...prev,{from:"c",text:"Connection error. Backend or WebSocket proxy is unreachable."}]);
      setPhase(prev=>prev==="running"?"done":prev);setSpeaking(false);
    };
    ws.onclose=(evt)=>{
      pushDebug("ws.close", { code:evt.code, reason:evt.reason || "", wasClean:evt.wasClean });
      wsRef.current=null;
    };
    return ws;
  },[handleWsMsg, pushDebug, buildWsUrl]);

  // ── WebSocket-driven planning run ────────────────────────────────
  const run=async ()=>{
    pushDebug("plan.run.click", {
      gp_name: gp?.gp_name || null,
      gp_city: gp?.city || null,
      gp_date: gp?.race_date || null,
      origin: form.origin || "New York",
      budget: +(form.budget || 2500),
      currency: form.currency,
      depart_date: form.departDate,
      return_date: form.returnDate,
    });
    cancelRef.current=false;setResults([]);setLiveResults({});setBudgetSummary(null);setBaselineBudgetSummary(null);setActiveConstraints({});setSelections({});setUpdatedCards(new Set());
    prevResultsRef.current=null;
    setChatMsgs([]);setStatusMsgs([{agent:"concierge",text:"Welcome, VIP! Connecting to your team..."}]);setShowStatus(false);
    setPhase("running");setSpeaking(true);setPipeIdx(0);

    const ws=await connectWs();
    const planPayload=JSON.stringify({type:"plan",data:{
      gp_name:gp.gp_name, gp_city:gp.city, gp_date:gp.race_date,
      origin:form.origin||"New York", budget:+(form.budget||2500),
      currency:form.currency||"EUR",
      stand_pref:form.stand,
      // Trip dates are now the first-class input. extra_days stays
      // in the payload as a harmless fallback so any backend that
      // receives an empty-dates legacy payload still computes a trip.
      depart_date:form.departDate||"", return_date:form.returnDate||"",
      extra_days:form.extraDays,
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

  const reset=()=>{cancelRef.current=true;resolveRef.current=null;try{if(wsRef.current&&wsRef.current.readyState<=1)wsRef.current.close();}catch(e){}wsRef.current=null;setPhase("welcome");setZSt({});setConPos(CONC_HOME);setSpeaking(false);setThinkBatch(null);setResults([]);setLiveResults({});setBudgetSummary(null);setBaselineBudgetSummary(null);setActiveConstraints({});setChatMsgs([]);setStatusMsgs([]);setShowStatus(false);setChatInput("");setPipeIdx(-1);setSelections({});setChatLoading(false);setUpdatedCards(new Set());setExplainState(null);prevResultsRef.current=null;};
  const backToSelect=()=>{reset();setScreen("select");setGp(null);};
  const handleGpSelect=useCallback((selectedGp)=>{
    setGp(selectedGp);
    setScreen("paddock");
    setPhase("welcome");
    const { depart, ret } = defaultTripDates(selectedGp.race_date);
    setForm(f=>({...f, departDate:depart, returnDate:ret}));
  },[]);

  const wsAlive=()=>wsRef.current&&wsRef.current.readyState===WebSocket.OPEN;

  const handleSelectionChange=(zone,arr)=>{
    const next={...selections,[zone]:arr};
    if(!arr.length) delete next[zone];
    const hasAny=Object.values(next).some(v=>Array.isArray(v)&&v.length>0);
    if(!hasAny){
      setSelections(next);
      setBudgetSummary(baselineBudgetSummary);
      return;
    }
    if(!wsAlive()){
      pushDebug("quote.blocked.no_ws");
      setChatMsgs(prev=>[...prev,{from:"c",text:"Connection lost. Please restart planning to refresh selected quote."}]);
      return;
    }
    setSelections(next);
    const quoteId=quoteSeqRef.current+1;
    quoteSeqRef.current=quoteId;
    pushDebug("quote.send", {quote_id:quoteId,selections:next});
    wsRef.current.send(JSON.stringify({type:"quote",data:{quote_id:quoteId,selections:next}}));
  };

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
    <GpSelect gpList={gpList} onSelectGp={handleGpSelect} pushDebug={pushDebug}/>
  );

  return(
    <div style={{background:"#0a0a0a",fontFamily:"'DM Sans',sans-serif",color:"#fff",maxWidth:680,margin:"0 auto",display:"flex",flexDirection:"column",height:"100vh",maxHeight:920,boxSizing:"border-box"}}>
      <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet"/>

      <AppHeader gp={gp} phase={phase} pipeIdx={pipeIdx} onBack={backToSelect} onReset={reset}
                 extraActions={(
                   <>
                     {phase==="done" && (
                       <button
                         data-testid="save-trip-btn"
                         disabled={!wsAlive() || results.length===0}
                         onClick={()=>{
                           if(!wsAlive()) return;
                           const snapshot = {
                             ...liveResults,
                             selections,
                             activeConstraints,
                           };
                           wsRef.current.send(JSON.stringify({
                             type:"save_trip",
                             data:{
                               gp_slug: gp?.gp_name ? gp.gp_name.toLowerCase().replace(/\s+/g,"-") : "unknown-gp",
                               depart_date: form.departDate || null,
                               return_date: form.returnDate || null,
                               plan_snapshot: snapshot,
                               budget_summary: budgetSummary,
                               active_constraints: activeConstraints,
                             },
                           }));
                         }}
                         style={{padding:"3px 8px",borderRadius:5,border:"1px solid #1d4ed8",background:"transparent",color:"#93c5fd",fontSize:8,cursor:"pointer"}}
                       >
                         {saveStatus?.ok ? "SAVED" : "SAVE"}
                       </button>
                     )}
                     <button
                       data-testid="my-trips-btn"
                       onClick={async ()=>{
                         // Open WS lazily if not yet connected, then show
                         // the panel only once we have a ws object to bind to.
                         if(!wsRef.current) await connectWs();
                         setShowSavedTrips(true);
                       }}
                       style={{padding:"3px 8px",borderRadius:5,border:"1px solid #222",background:"transparent",color:"#888",fontSize:8,cursor:"pointer"}}
                     >
                       MY TRIPS
                     </button>
                   </>
                 )}
                 rightSlot={HAS_CLERK ? <UserMenu /> : null}/>
      <PaddockMap zSt={zSt} conPos={conPos} speaking={speaking}/>

      <div ref={scrollRef} style={{flex:1,overflowY:"auto",padding:"10px 14px 6px",minHeight:0}}>

        {phase==="welcome"&&(
          <WelcomeForm form={form} setForm={setForm} gp={gp} onSubmit={run}/>
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

        {phase==="done"&&constraintLabels(activeConstraints).length>0&&(
          <div style={{display:"flex",flexWrap:"wrap",gap:4,marginBottom:6}}>
            {constraintLabels(activeConstraints).map(label=>(
              <span key={label} style={{fontSize:8,color:"#93C5FD",border:"1px solid #2563EB44",background:"#1D4ED814",borderRadius:999,padding:"2px 7px"}}>{label}</span>
            ))}
          </div>
        )}

        {/* Result cards — with highlight animation for updated cards after refine */}
        {results.map(key=>(
          <div key={key} style={{borderRadius:8,border:updatedCards.has(key)?"1px solid #E1060066":"1px solid transparent",transition:"border-color 0.5s",animation:updatedCards.has(key)?"cardPulse 1s ease-out":"none"}}>
            <ResultCard zoneKey={key} selections={selections} onSelect={handleSelectionChange} liveResults={liveResults} onShowExplain={showExplain} explainDemo={explainDemoMode}/>
          </div>
        ))}

        {phase==="done"&&budgetSummary&&(
          <BudgetPanel
            budgetSummary={budgetSummary}
            formBudget={form.budget}
            formCurrency={form.currency}
            liveResults={liveResults}
          />
        )}

        <ChatMessages chatMsgs={chatMsgs}/>
      </div>

      {phase==="done"&&(
        <ChatInput
          chatInput={chatInput}
          setChatInput={setChatInput}
          chatLoading={chatLoading}
          handleChat={handleChat}
        />
      )}

      {debugMode&&(
        <DebugTrace debugLog={debugLog} copyStatus={copyStatus} setCopyStatus={setCopyStatus}/>
      )}

      {explainState&&(
        <ExplainabilityPanel
          rationale={explainState.rationale}
          zoneKey={explainState.zoneKey}
          itemMain={explainState.item?.main}
          onClose={closeExplain}
        />
      )}

      {showSavedTrips&&(
        <SavedTrips
          ws={wsRef.current}
          onLoad={()=>{ /* trip_loaded handler in handleWsMsg restores state */ }}
          onClose={()=>setShowSavedTrips(false)}
        />
      )}

      <style>{`
        @keyframes slideUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
        @keyframes blink{0%,100%{opacity:1}50%{opacity:0}}
        @keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(1.5)}}
        @keyframes cBounce{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}
        @keyframes cardSlide{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:translateY(0)}}
        @keyframes cardPulse{0%{border-color:#E10600}50%{border-color:#E1060066}100%{border-color:transparent}}
        @keyframes drawTrack{to{stroke-dashoffset:0}}
        @keyframes explainSlideIn{from{transform:translateX(100%)}to{transform:translateX(0)}}
        @keyframes explainFadeIn{from{opacity:0}to{opacity:1}}
        ::-webkit-scrollbar{width:4px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:#333;border-radius:4px}
      `}</style>
    </div>
  );
}
