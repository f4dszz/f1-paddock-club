export const ZONES = [
  { key:"ticket", label:"Tickets", color:"#F59E0B", x:8, y:8, w:42, h:38 },
  { key:"transport", label:"Flights", color:"#3B82F6", x:50, y:8, w:42, h:38 },
  { key:"hotel", label:"Hotel", color:"#A855F7", x:8, y:54, w:28, h:38 },
  { key:"plan", label:"Schedule", color:"#F97316", x:36, y:54, w:28, h:38 },
  { key:"tour", label:"Explore", color:"#06B6D4", x:64, y:54, w:28, h:38 },
];

export const PIPELINE = [
  { zones:["ticket"], label:"Finding best tickets first..." },
  { zones:["transport","hotel"], label:"Searching flights + hotels in parallel..." },
  { zones:["plan","tour"], label:"Planning schedule + sights in parallel..." },
];

export const AGENT_TO_BATCH = { ticket:0, transport:1, hotel:1, plan:2, tour:2, budget:2 };
export const CONC_HOME = { x:46, y:46 };

export const THINK = {
  ticket:["Scanning platforms...","Comparing grandstands...","Checking sightlines...","Picks ready"],
  transport:["Searching flights...","Direct vs connecting...","Local rail...","Routes done"],
  hotel:["Race-week rates...","Distance filter...","Comparing...","Found"],
  plan:["Race weekend map...","FP / Quali / Race...","Free time...","Set"],
  tour:["Local gems...","F1 specials...","Restaurants...","Ready"],
};

export const FLAGS={"Australia":"🇦🇺","China":"🇨🇳","Japan":"🇯🇵","USA":"🇺🇸","Canada":"🇨🇦","Monaco":"🇲🇨","Spain":"🇪🇸","Austria":"🇦🇹","UK":"🇬🇧","Belgium":"🇧🇪","Hungary":"🇭🇺","Netherlands":"🇳🇱","Italy":"🇮🇹","Azerbaijan":"🇦🇿","Singapore":"🇸🇬","Mexico":"🇲🇽","Brazil":"🇧🇷","Qatar":"🇶🇦","UAE":"🇦🇪"};
export const HERO_COLORS=["#059669","#DC2626","#1E40AF","#EC4899","#7C3AED","#F59E0B","#06B6D4","#F97316"];
export const SHORT_NAMES={"Australian GP":"Australia","Chinese GP":"China","Japanese GP":"Japan","Miami GP":"Miami","Canadian GP":"Canada","Monaco GP":"Monaco","Barcelona-Catalunya GP":"Barcelona","Austrian GP":"Austria","British GP":"Britain","Belgian GP":"Belgium","Hungarian GP":"Hungary","Dutch GP":"Netherlands","Italian GP":"Monza","Spanish GP":"Madrid","Azerbaijan GP":"Baku","Singapore GP":"Singapore","United States GP":"USA","Mexico City GP":"Mexico","Brazilian GP":"Brazil","Las Vegas GP":"Las Vegas","Qatar GP":"Qatar","Abu Dhabi GP":"Abu Dhabi"};

export const TRACK_MAP={
  "Australian GP":"M30,60 L25,35 Q28,20 40,15 L55,12 Q70,10 75,20 L78,40 Q80,55 72,65 L60,72 Q50,78 40,75 L30,60Z",
  "Chinese GP":"M25,50 L30,25 Q35,15 50,12 L65,15 Q75,20 78,35 L75,50 Q72,60 65,65 L55,55 Q50,50 45,55 L35,65 Q28,60 25,50Z",
  "Japanese GP":"M25,45 Q35,20 50,25 Q60,30 55,45 Q50,55 60,60 Q70,65 65,75 Q50,80 35,70 Q25,60 25,45Z",
  "Miami GP":"M30,35 L65,20 Q80,25 75,40 L60,50 Q55,55 60,65 L40,75 Q25,70 25,55 L30,35Z",
  "Canadian GP":"M20,45 L25,20 Q30,12 45,15 L55,20 Q65,25 60,40 L65,50 Q70,60 60,70 L40,75 Q25,72 20,60 L20,45Z",
  "Monaco GP":"M35,30 Q45,15 60,20 L70,35 Q75,50 65,60 L50,70 Q35,75 30,60 L35,30Z",
  "Barcelona-Catalunya GP":"M25,55 L30,30 Q35,18 50,15 L65,18 Q75,22 78,35 L72,50 Q68,62 55,65 L45,60 Q38,58 35,62 L28,68 Q22,65 25,55Z",
  "Austrian GP":"M35,70 L30,45 Q32,30 45,20 L60,15 Q72,18 70,30 L65,55 Q62,68 50,72 L35,70Z",
  "British GP":"M25,45 Q30,20 50,15 Q70,12 80,30 Q85,45 78,60 Q65,75 45,78 Q25,70 25,45Z",
  "Belgian GP":"M25,35 L35,15 Q45,10 55,18 L65,35 Q70,50 60,60 L50,70 Q40,78 30,70 L22,50 Q20,42 25,35Z",
  "Hungarian GP":"M30,65 L25,40 Q28,25 40,18 L60,15 Q72,18 75,30 L72,50 Q70,62 60,68 L40,72 Q32,70 30,65Z",
  "Dutch GP":"M30,55 L35,30 Q40,18 55,15 Q68,14 72,25 L70,45 Q68,58 58,62 Q48,65 40,60 L30,55Z",
  "Italian GP":"M40,75 L35,30 Q38,15 50,12 Q62,10 68,25 L72,50 Q75,65 65,75 Q55,80 40,75Z",
  "Spanish GP":"M25,50 L35,25 Q42,15 55,12 L70,15 Q80,20 78,35 L72,55 Q68,68 55,72 L40,70 Q28,65 25,50Z",
  "Azerbaijan GP":"M30,75 L25,50 L28,30 L40,20 Q50,15 60,20 L72,30 L75,50 L70,70 Q60,78 45,78 L30,75Z",
  "Singapore GP":"M30,35 Q40,18 55,20 Q70,22 78,35 Q82,50 75,62 Q65,72 50,75 Q35,72 28,58 Q25,45 30,35Z",
  "United States GP":"M25,50 Q30,20 50,15 Q65,12 75,25 L80,45 Q82,60 70,70 Q55,78 40,75 Q25,65 25,50Z",
  "Mexico City GP":"M30,65 L25,40 Q28,22 45,15 L60,12 Q75,15 78,30 L75,55 Q72,68 58,72 L38,70 Q30,68 30,65Z",
  "Brazilian GP":"M70,25 Q78,35 75,50 L65,65 Q55,75 40,72 L30,55 Q25,40 35,28 Q50,18 70,25Z",
  "Las Vegas GP":"M30,30 L70,25 Q82,30 80,45 L75,60 Q70,72 55,75 L35,70 Q22,65 25,45 L30,30Z",
  "Qatar GP":"M30,60 L28,35 Q32,18 50,12 L65,15 Q78,20 75,35 L70,55 Q65,70 50,72 L35,68 Q28,65 30,60Z",
  "Abu Dhabi GP":"M28,55 L32,30 Q38,15 55,12 L68,15 Q80,20 78,35 L72,55 Q68,70 52,75 L38,72 Q25,68 28,55Z",
};
