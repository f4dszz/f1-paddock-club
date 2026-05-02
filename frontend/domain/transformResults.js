export function transformResults(data) {
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
          provider:t.provider||"Formula 1", linkType:t.link_type||"official_ticket_page",
          bookingConfidence:t.booking_confidence||"medium",
          rationale:t._rationale||null,
        };
      })
    };
  }
  if (data.transport?.length) {
    r.transport = { mode:"single", bookLabel:"Book flight", bookIcon:"✈", items:
      data.transport.filter(t=>t.tag!=="INFO").map(t=>{
        const pv=t.price||0;
        return {
          tag:t.tag||"OUT", main:t.summary||"Flight", sub:t.detail||"",
          price: pv>0 ? `${t.currency||"USD"} ${t.price}` : "Price not provided",
          pv, priced: pv>0,
          currency:t.currency||"USD", link:t.link||"",
          source:t._source||"mock", degraded:t._degraded===true||!t._source,
          provider:t.provider||"Google Flights", linkType:t.link_type||"flight_search",
          bookingConfidence:t.booking_confidence||"search",
          rationale:t._rationale||null,
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
          source:h._source||"mock", degraded:h._degraded===true||!h._source,
          provider:h.provider||"Hotel provider", linkType:h.link_type||"hotel_listing",
          bookingConfidence:h.booking_confidence||"medium",
          rationale:h._rationale||null,
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
