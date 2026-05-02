export const CUR_SYMBOL={EUR:"€",USD:"$",CNY:"¥"};

export const SOURCE_LABELS={
  google_flights:{text:"Live · SerpAPI",color:"#22C55E"},
  google_search:{text:"Live · SerpAPI",color:"#22C55E"},
  google_hotels:{text:"Live · SerpAPI",color:"#22C55E"},
  google_maps:{text:"Live · SerpAPI",color:"#22C55E"},
  llm_estimate:{text:"Estimated · LLM",color:"#F59E0B"},
  mock:{text:"Mock data",color:"#6B7280"},
};

export function sourceLabel(src){
  return SOURCE_LABELS[src]?.text || (src||"unknown");
}

export function sourceColor(src){
  return SOURCE_LABELS[src]?.color || "#6B7280";
}

const LINK_LABELS={
  official_ticket_page:"Open official ticket page",
  flight_search:"Open flight search",
  hotel_listing:"Open hotel listing",
  maps_listing:"Open maps listing",
  hotel_search:"Open hotel search",
  provider_search:"Open provider search",
  local_info:"Open local info",
};

export function linkActionLabel(item){
  return LINK_LABELS[item?.linkType]||"Open provider";
}

export function constraintLabels(c){
  const labels=[];
  if(c?.direct_only)labels.push("Direct flights only");
  if(c?.allowed_hotel_brands?.length)labels.push(`Hotels: ${c.allowed_hotel_brands.join(" / ")}`);
  if(c?.dietary)labels.push(`Dietary: ${c.dietary}`);
  if(c?.accessibility)labels.push("Accessibility");
  if(c?.avoid_luxury)labels.push("Avoid luxury");
  if(c?.budget_strategy&&c.budget_strategy!=="balanced")labels.push(`Budget: ${c.budget_strategy}`);
  return labels;
}

export const RATIONALE_FIXTURES={
  hotel:{
    card_type:"hotel",
    source:"google_hotels",
    fallback_chain:["serpapi"],
    source_path_note:"Configured data path inferred from the final card source.",
    reasons:[
      "Distance: 8.2 km from circuit",
      "Brand: Marriott portfolio matched per request",
      "Price: EUR 145/night x 5 nights = EUR 725",
    ],
    constraint_matches:{allowed_hotel_brands:{matched:"Marriott"}},
    trade_offs:[
      {against:"Hotel de la Ville",advantage:"Closer to circuit",cost:"+EUR 10/night"},
      {against:"Apartment Central",advantage:"Hotel amenities",cost:"+EUR 50/night"},
    ],
  },
  flight:{
    card_type:"flight",
    source:"google_flights",
    fallback_chain:["serpapi"],
    source_path_note:"Configured data path inferred from the final card source.",
    reasons:[
      "Direct flight matched per request",
      "Route: JFK -> destination airport",
      "Provider: Google Flights",
    ],
    constraint_matches:{direct_only:true},
    trade_offs:[
      {against:"Connecting fare",advantage:"Direct routing",cost:"Usually higher price"},
    ],
  },
  ticket:{
    card_type:"ticket",
    source:"firecrawl",
    fallback_chain:["firecrawl","llm_estimate"],
    source_path_note:"Configured data path inferred from the final card source.",
    reasons:[
      "Tag: PICK for price and view balance",
      "Reserved grandstand seat",
      "Official ticket page available",
    ],
    constraint_matches:{},
    trade_offs:[
      {against:"General Admission",advantage:"Reserved seat",cost:"Higher price"},
    ],
  },
};

export function describeConstraintMatch(key,val){
  if(key==="direct_only"&&val)return "Direct flights only";
  if(key==="allowed_hotel_brands"&&val&&typeof val==="object"){
    return `Hotel brand: ${val.matched||"matched"}`;
  }
  if(key==="accessibility")return val?"Accessibility requested":"Accessibility not required";
  if(key==="avoid_luxury"&&val)return "Avoid luxury";
  if(key==="dietary"&&val)return `Dietary: ${typeof val==="string"?val:"matched"}`;
  return `${key}: ${typeof val==="object"?JSON.stringify(val):String(val)}`;
}
