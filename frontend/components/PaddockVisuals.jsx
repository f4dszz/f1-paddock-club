export function PxChar({type,size=28}){
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

export function Zone({zone,status}){
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

export function ConFloat({x,y,speaking}){
  return(
    <div style={{position:"absolute",left:`${x}%`,top:`${y}%`,transform:"translate(-50%,-50%)",transition:"left .7s cubic-bezier(0.34,1.56,0.64,1), top .7s cubic-bezier(0.34,1.56,0.64,1)",zIndex:10,pointerEvents:"none"}}>
      <div style={{animation:speaking?"cBounce .5s ease-in-out infinite":"none"}}><PxChar type="concierge" size={30}/></div>
    </div>
  );
}

export function TrackSVG({d,color,size=44}){
  return <svg width={size} height={size} viewBox="0 0 100 90"><path d={d} fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" opacity={0.6} style={{strokeDasharray:300,strokeDashoffset:300,animation:"drawTrack 1.5s ease-out forwards"}}/></svg>;
}
