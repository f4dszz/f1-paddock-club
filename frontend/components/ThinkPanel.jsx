import { useCallback, useEffect, useRef, useState } from "react";
import { THINK, ZONES } from "../domain/planningConstants.js";
import { PxChar } from "./PaddockVisuals.jsx";

function SingleThinkStream({lines,color,onDone}){
  const[shown,setShown]=useState([]);const[cur,setCur]=useState("");const[li,setLi]=useState(0);const[ci,setCi]=useState(0);
  const doneRef=useRef(false);
  useEffect(()=>{
    if(li>=lines.length){if(!doneRef.current){doneRef.current=true;onDone?.();}return;}
    const line=lines[li];
    if(ci<line.length){const t=setTimeout(()=>{setCur(p=>p+line[ci]);setCi(c=>c+1);},18+Math.random()*12);return()=>clearTimeout(t);}
    else{const t=setTimeout(()=>{setShown(p=>[...p,line]);setCur("");setCi(0);setLi(l=>l+1);},130);return()=>clearTimeout(t);}
  },[li,ci,lines,onDone]);
  return(
    <div style={{fontSize:10,color:"#666",lineHeight:1.4}}>
      {shown.map((l,i)=><div key={i} style={{opacity:.5}}><span style={{color}}>› </span>{l}</div>)}
      {cur&&<div><span style={{color}}>› </span>{cur}<span style={{animation:"blink .7s step-end infinite",color}}>▋</span></div>}
    </div>
  );
}

export function ThinkPanel({zoneKeys,onAllDone}){
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
