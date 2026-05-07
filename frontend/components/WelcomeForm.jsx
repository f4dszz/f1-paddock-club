import { validateTripDates } from "../domain/tripDates.js";
import { PxChar } from "./PaddockVisuals.jsx";

export function WelcomeForm({ form, setForm, gp, onSubmit }) {
  const dateValidation = validateTripDates(form.departDate, form.returnDate, gp?.race_date);
  const budgetFilled = String(form.budget ?? "").trim() !== "";
  const budgetValue = Number(form.budget);
  const budgetInvalid = budgetFilled && (!Number.isFinite(budgetValue) || budgetValue <= 0);
  const disabled = !dateValidation.valid || budgetInvalid;
  const errBorder = dateValidation.error ? "#EF4444" : "#222";

  return (
    <div style={{animation:"slideUp .4s ease-out"}}>
      <div style={{display:"flex",gap:8,alignItems:"flex-end",marginBottom:10}}>
        <PxChar type="concierge" size={36}/>
        <div style={{background:"#151515",border:"1px solid #E1060033",borderRadius:"4px 10px 10px 10px",padding:"8px 12px",flex:1}}>
          <div style={{fontSize:11.5,color:"#ccc",lineHeight:1.5}}>Welcome, VIP! Fill in your details and any special wishes.</div>
        </div>
      </div>

      <div style={{background:"#111",border:"1px solid #222",borderRadius:10,padding:"12px",marginBottom:10}}>
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:6,marginBottom:6}}>
          {[{l:"Flying from",k:"origin",p:"e.g. New York",t:"text"},{l:`Budget (${form.currency})`,k:"budget",p:"2500",t:"number"}].map(f => (
            <div key={f.k}>
              <label style={{fontSize:8,color:"#555",display:"block",marginBottom:2}}>{f.l}</label>
              <input
                data-testid={f.k==="origin"?"origin-input":"budget-input"}
                value={form[f.k]}
                onChange={e => {
                  const value = e.target.value;
                  setForm(prev => ({...prev,[f.k]:value}));
                }}
                placeholder={f.p}
                type={f.t}
                min={f.k==="budget" ? "1" : undefined}
                step={f.k==="budget" ? "1" : undefined}
                style={{width:"100%",padding:"6px 9px",borderRadius:5,border:"1px solid #222",background:"#0a0a0a",color:"#eee",fontSize:11,outline:"none",fontFamily:"inherit",boxSizing:"border-box"}}
                onFocus={e => e.target.style.borderColor="#E10600"}
                onBlur={e => e.target.style.borderColor=f.k==="budget"&&budgetInvalid?"#EF4444":"#222"}
              />
              {f.k==="budget"&&budgetInvalid&&<div style={{fontSize:8,color:"#EF4444",marginTop:3}}>Budget must be greater than 0.</div>}
            </div>
          ))}
        </div>

        <div style={{marginBottom:6}}>
          <label style={{fontSize:8,color:"#555",display:"block",marginBottom:3}}>Currency <span style={{color:"#333"}}>(budget amount is interpreted in this unit)</span></label>
          <div style={{display:"flex",gap:3}}>
            {["EUR","USD","CNY"].map(c => (
              <button
                key={c}
                data-testid={`currency-${c}`}
                onClick={() => setForm(prev => ({...prev,currency:c}))}
                style={{flex:1,padding:"4px",borderRadius:4,fontSize:9,fontWeight:600,cursor:"pointer",border:`1px solid ${form.currency===c?"#E10600":"#222"}`,background:form.currency===c?"#E1060015":"transparent",color:form.currency===c?"#E10600":"#555"}}
              >
                {c}
              </button>
            ))}
          </div>
        </div>

        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:6,marginBottom:dateValidation.error||dateValidation.warnings.length?3:6}}>
          <div>
            <label style={{fontSize:8,color:"#555",display:"block",marginBottom:2}}>Depart date</label>
            <input
              data-testid="depart-date-input"
              type="date"
              value={form.departDate}
              onChange={e => {
                const value = e.target.value;
                setForm(prev => ({...prev,departDate:value}));
              }}
              onInput={e => {
                const value = e.currentTarget.value;
                setForm(prev => ({...prev,departDate:value}));
              }}
              style={{width:"100%",padding:"5px 9px",borderRadius:5,border:`1px solid ${errBorder}`,background:"#0a0a0a",color:"#eee",fontSize:10,outline:"none",fontFamily:"inherit",boxSizing:"border-box",colorScheme:"dark"}}
            />
          </div>
          <div>
            <label style={{fontSize:8,color:"#555",display:"block",marginBottom:2}}>Return date</label>
            <input
              data-testid="return-date-input"
              type="date"
              value={form.returnDate}
              onChange={e => {
                const value = e.target.value;
                setForm(prev => ({...prev,returnDate:value}));
              }}
              onInput={e => {
                const value = e.currentTarget.value;
                setForm(prev => ({...prev,returnDate:value}));
              }}
              style={{width:"100%",padding:"5px 9px",borderRadius:5,border:`1px solid ${errBorder}`,background:"#0a0a0a",color:"#eee",fontSize:10,outline:"none",fontFamily:"inherit",boxSizing:"border-box",colorScheme:"dark"}}
            />
          </div>
        </div>
        {dateValidation.error && <div style={{fontSize:9,color:"#EF4444",marginBottom:6}}>{dateValidation.error}</div>}
        {!dateValidation.error && dateValidation.warnings.length > 0 && (
          <div style={{fontSize:8,color:"#F59E0B",marginBottom:6,lineHeight:1.4}}>
            {dateValidation.warnings.map((w,i) => <div key={i}>Warning: {w}</div>)}
          </div>
        )}

        <div style={{marginBottom:6}}>
          <label style={{fontSize:8,color:"#555",display:"block",marginBottom:3}}>Grandstand</label>
          <div style={{display:"flex",gap:3}}>
            {[["any","Any"],["ga","GA"],["mid","Mid"],["vip","VIP"]].map(([v,l]) => (
              <button
                key={v}
                data-testid={`stand-${v}`}
                onClick={() => setForm(prev => ({...prev,stand:v}))}
                style={{flex:1,padding:"4px",borderRadius:4,fontSize:9,fontWeight:600,cursor:"pointer",border:`1px solid ${form.stand===v?"#E10600":"#222"}`,background:form.stand===v?"#E1060015":"transparent",color:form.stand===v?"#E10600":"#555"}}
              >
                {l}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label style={{fontSize:8,color:"#555",display:"block",marginBottom:2}}>Special requests <span style={{color:"#333"}}>(optional)</span></label>
          <textarea
            data-testid="special-requests-input"
            value={form.special}
            onChange={e => {
              const value = e.target.value;
              setForm(prev => ({...prev,special:value}));
            }}
            placeholder="e.g. stop in Milan 2 days, vegetarian meals, pit walk, wheelchair access, Michelin restaurant..."
            style={{width:"100%",padding:"6px 9px",borderRadius:5,border:"1px solid #222",background:"#0a0a0a",color:"#eee",fontSize:10.5,outline:"none",fontFamily:"inherit",boxSizing:"border-box",resize:"none",height:48,lineHeight:1.5}}
            onFocus={e => e.target.style.borderColor="#E10600"}
            onBlur={e => e.target.style.borderColor="#222"}
          />
        </div>
        <div style={{fontSize:8,color:"#555",lineHeight:1.5,marginTop:6}}>
          Describe any stops, dietary needs, accessibility, or experiences you want. Trips must stay between 1 and 30 nights; after results, use the chat to refine.
        </div>
      </div>

      <button
        data-testid="plan-submit"
        onClick={onSubmit}
        disabled={disabled}
        style={{width:"100%",padding:"11px",borderRadius:8,border:"none",background:disabled?"#333":"#E10600",color:disabled?"#777":"#fff",fontSize:12,fontWeight:700,cursor:disabled?"not-allowed":"pointer",letterSpacing:"0.03em",transition:"all .15s"}}
      >
        {disabled ? "FIX DATES TO CONTINUE" : "START PLANNING"}
      </button>
    </div>
  );
}
