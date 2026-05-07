import { PxChar } from "./PaddockVisuals.jsx";

export function ChatMessages({chatMsgs}){
  return chatMsgs.map((m,i)=>(
    <div key={i} style={{marginBottom:5,animation:"slideUp .2s ease-out"}}>
      {m.from==="u"?(
        <div style={{display:"flex",justifyContent:"flex-end"}}><div style={{padding:"5px 10px",borderRadius:"7px 7px 3px 7px",background:"#E10600",fontSize:10.5,color:"#fff",maxWidth:"75%"}}>{m.text}</div></div>
      ):(
        <div style={{display:"flex",gap:5,alignItems:"flex-end"}}><PxChar type="concierge" size={16}/><div style={{padding:"5px 10px",borderRadius:"3px 7px 7px 7px",background:"#151515",border:"1px solid #1f1f1f",fontSize:10.5,color:"#999",maxWidth:"75%"}}>{m.text}</div></div>
      )}
    </div>
  ));
}

export function ChatInput({chatInput,setChatInput,chatLoading,handleChat}){
  return(
    <div style={{padding:"6px 14px 10px",borderTop:"1px solid #1a1a1a",flexShrink:0,display:"flex",gap:6}}>
      <input data-testid="chat-input" value={chatInput} onChange={e=>setChatInput(e.target.value)} onKeyDown={e=>{if(e.key==="Enter"){e.preventDefault();handleChat();}}}
        placeholder="Refine this plan... (e.g. cheaper hotels, direct flights only)" disabled={chatLoading}
        style={{flex:1,padding:"7px 10px",borderRadius:7,border:"1px solid #222",background:"#111",color:"#eee",fontSize:11,outline:"none",fontFamily:"inherit",opacity:chatLoading?0.5:1}}
        onFocus={e=>e.target.style.borderColor="#E10600"} onBlur={e=>e.target.style.borderColor="#222"}/>
      <button data-testid="chat-send" onClick={handleChat} disabled={!chatInput.trim()||chatLoading} style={{padding:"7px 12px",borderRadius:7,border:"none",background:chatInput.trim()&&!chatLoading?"#E10600":"#222",color:chatInput.trim()&&!chatLoading?"#fff":"#555",fontSize:10,fontWeight:600,cursor:chatInput.trim()&&!chatLoading?"pointer":"not-allowed"}}>{chatLoading?"...":"GO"}</button>
    </div>
  );
}
