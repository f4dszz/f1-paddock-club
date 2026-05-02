const DAY_MS=24*60*60*1000;

function toIsoDateUTC(date){
  const y=date.getUTCFullYear();
  const m=String(date.getUTCMonth()+1).padStart(2,"0");
  const d=String(date.getUTCDate()).padStart(2,"0");
  return `${y}-${m}-${d}`;
}

function parseIsoDateUTC(iso){
  const m=/^(\d{4})-(\d{2})-(\d{2})$/.exec(iso||"");
  if(!m) return null;
  const y=Number(m[1]), mo=Number(m[2]), d=Number(m[3]);
  const utc=Date.UTC(y,mo-1,d);
  if(toIsoDateUTC(new Date(utc))!==iso) return null;
  return utc;
}

function addIsoDays(iso,days){
  const utc=parseIsoDateUTC(iso);
  if(utc===null) return "";
  return toIsoDateUTC(new Date(utc+days*DAY_MS));
}

export function defaultTripDates(raceDate){
  if(!raceDate) return { depart:"", ret:"" };
  return { depart:addIsoDays(raceDate,-2), ret:addIsoDays(raceDate,3) };
}

export function validateTripDates(depart, returnDate, raceDate){
  const warnings=[];
  if(!depart && !returnDate) return { valid:true, error:"", warnings };
  if(!depart || !returnDate) return { valid:false, error:"Please set both depart and return dates.", warnings };
  const iso=/^\d{4}-\d{2}-\d{2}$/;
  if(!iso.test(depart) || !iso.test(returnDate)) return { valid:false, error:"Dates must be YYYY-MM-DD.", warnings };
  const d=parseIsoDateUTC(depart);
  const r=parseIsoDateUTC(returnDate);
  if(d===null || r===null) return { valid:false, error:"One of the dates is invalid.", warnings };
  if(d>=r) return { valid:false, error:"Depart date must be strictly before return date (day-trips not yet supported).", warnings };
  const nights=Math.round((r-d)/DAY_MS);
  if(nights>30) return { valid:false, error:"Trip longer than 30 nights.", warnings };
  if(raceDate){
    const rc=parseIsoDateUTC(raceDate);
    if(rc!==null&&d>rc) warnings.push("You arrive after race day — you'll miss the Grand Prix.");
    if(rc!==null&&r<rc) warnings.push("You leave before race day — you won't see the race.");
  }
  if(nights>14) warnings.push(`Trip is ${nights} nights — that's a long F1 weekend.`);
  return { valid:true, error:"", warnings };
}
