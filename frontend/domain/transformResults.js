export function transformResults(data) {
  const r = {};
  if (data.tickets?.length) {
    const items = [];
    let selectionIndex = -1;
    for (const t of data.tickets) {
      if (t.tag === "INFO") continue;
      selectionIndex += 1;
      const pv = t.price || 0;
      items.push({
        selectionIndex,
        tag: t.tag || "PICK", main: t.name || "Ticket", sub: t.section || "",
        price: pv > 0 ? `${t.currency || "EUR"} ${t.price}` : "Price not provided",
        pv, priced: pv > 0,
        currency: t.currency || "EUR", link: t.link || "",
        provider: t.provider || "Formula 1", linkType: t.link_type || "search",
        bookingConfidence: t.booking_confidence || "medium",
        rationale: t._rationale || null,
      });
    }
    r.ticket = { mode:"single", bookLabel:"Book tickets", bookIcon:"🎫", items };
  }
  if (data.transport?.length) {
    const items = [];
    let selectionIndex = -1;
    for (const t of data.transport) {
      if (t.tag === "INFO") continue;
      selectionIndex += 1;
      if (t.tag === "LOCAL") continue;
      const pv = t.price || 0;
      items.push({
        selectionIndex,
        tag: t.tag || "OUT", main: t.summary || "Flight", sub: t.detail || "",
        price: pv > 0 ? `${t.currency || "USD"} ${t.price}` : "Price not provided",
        pv, priced: pv > 0,
        currency: t.currency || "USD", link: t.link || "",
        source: t._source || "mock", degraded: t._degraded === true || !t._source,
        provider: t.provider || "Google Flights", linkType: t.link_type || "search",
        bookingConfidence: t.booking_confidence || "medium",
        rationale: t._rationale || null,
      });
    }
    if (items.length) r.transport = { mode:"single", bookLabel:"Book flight", bookIcon:"✈", items };
  }
  if (data.hotel?.length) {
    const items = [];
    let selectionIndex = -1;
    for (const h of data.hotel) {
      if (h.tag === "INFO") continue;
      selectionIndex += 1;
      const pv = h.price_per_night || 0;
      items.push({
        selectionIndex,
        tag: h.tag || "NEAR", main: h.name || "Hotel",
        sub: `${h.distance || ""} · ${h.rating || ""}★ · ${h.nights || "?"}n`,
        price: pv > 0 ? `${h.currency || "USD"} ${h.price_per_night}/n` : "Price not provided",
        pv, priced: pv > 0,
        currency: h.currency || "USD", link: h.link || "",
        source: h._source || "mock", degraded: h._degraded === true || !h._source,
        provider: h.provider || "Hotel provider", linkType: h.link_type || "homepage",
        bookingConfidence: h.booking_confidence || "medium",
        rationale: h._rationale || null,
      });
    }
    r.hotel = { mode:"single", bookLabel:"Book hotel", bookIcon:"🏨", items };
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
