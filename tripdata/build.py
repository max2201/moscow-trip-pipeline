"""Сборка данных сайтов: отели по городам, цены по остановкам, оценки, плюсы и минусы, «Коротко об отеле»."""
import json, re, os, math, statistics as st
from .analyze import analyze
from .paths import CONTENT, HOTEL_META, TRIP_DATA, SITE_DATA, read_json, write_json, list_path, load_settings, load_hotels

CENTER={"msk":(55.75393,37.62079)}  # Красная площадь
def hav(a,b,c,d):
    R=6371;p=math.pi/180
    return 2*R*math.asin(math.sqrt(math.sin((c-a)*p/2)**2+math.cos(a*p)*math.cos(c*p)*math.sin((d-b)*p/2)**2))
def fnum(s):
    try: return float(str(s).replace(",","."))
    except: return None
ZFIX={"Лай Wua":"Вуа Лай","Nawarat":"Наварат","San Phe Suea":"Сан Пхи Суа","Central Festival Chiang Mai":"Central Festival","Дой Су Тхеп":"Дой Сутхеп"}
def zone_of(city,m,lat,lng):
    """Район отеля для карточек «Районы»: ищем район Островка в списках зон из guides.json, иначе — последний (общий) район."""
    # Китай-город Островок почти никому не проставляет — считаем по расстоянию от Красной площади
    if city=="msk" and lat and lat>=55.7497 and hav(lat,lng,*CENTER[city])<=0.9: return "Китай-город и Кремль"
    for zn in [m.get("zone")]+list(m.get("zones") or []):
        for d in G[city]["districts"]:
            if zn and zn in d["z"]: return d["t"]
    return G[city]["districts"][-1]["t"]
POSTXT={"clean":"Чистоту хвалят","loc":"Расположение и транспорт хвалят","staff":"Персонал хвалят","breakfast":"Завтрак хвалят","pool":"Бассейн хвалят","bed":"Удобные кровати отмечают","value":"Соотношение цены и качества хвалят","quiet":"Тишину отмечают","spacious":"Просторные номера отмечают","view":"Вид из окна хвалят"}
CONTXT={"roach":"Тараканы, клопы","damp":"Сырость, плесень, затхлость","smell":"Неприятный запах","dirty":"Грязь, пыль, пятна","noise":"Шум, слабая звукоизоляция","old":"Устаревшее здание и мебель","ac":"Проблемы с кондиционером","bath":"Сантехника и душ","small":"Тесные номера","smoke":"Табачный дым","rude":"Грубость персонала","wifi":"Плохой Wi-Fi","ants":"Муравьи, комары, мошки"}
WEIGHT={"roach":3,"damp":2,"smell":2,"dirty":1.5,"noise":1,"old":1,"ac":1,"bath":1,"small":0.8,"smoke":1,"rude":1.2,"wifi":0.6,"ants":1.2}
AMR=[("pool",r"бассейн"),("gym",r"Фитнес"),("food",r"Ресторан|Restaurant|Кафе|cafe|Снэк-бар"),("bar",r"\bБар\b|Лобби-бар|\bbar\b"),("laundry",r"Прачечн|Услуги прачечной|Стиральный порошок"),("lift",r"^Лифт$"),("parking",r"парковка|Парковка"),("transfer",r"Трансфер от аэропорта"),("kitchen",r"Общая кухня"),("spa",r"Спа|Массаж|Сауна"),("work",r"Коворкинг|Бизнес-центр")]
DORM=re.compile(r"общ\S* (номер|спальн|комнат)|dorm|койк|кровать в |bunk|капсул|capsule|двухъярусн|смешанн|женск\S* (номер|спальн)|мужск\S* (номер|спальн)",re.I)
SHARED=re.compile(r"общ\S* ванн|shared bath|shared toilet|общ\S* санузел|общ\S* туалет",re.I)
NOWIN=re.compile(r"без окна|windowless|no window",re.I)
def pct(x): return f"{round(x*100):d}%" if x>=0.01 else "<1%"
def plural(n,a,b,c):
    n=abs(n)%100;n1=n%10
    if 10<n<20: return c
    if n1==1: return a
    if 2<=n1<=4: return b
    return c
def room_flags(room,name):
    room=room or ""
    private=bool(re.search(r"частн|private|отдельн",room,re.I))
    return bool(DORM.search(room)) and not private, bool(SHARED.search(room)), bool(NOWIN.search(room))
def build_trip(log=print):
  global G
  G=read_json(CONTENT/"guides.json"); SD=read_json(CONTENT/"stops.json"); STOPS=SD["stops"]
  SAVED={k:set(v) for k,v in read_json(CONTENT/"saved.json",{}).items()}
  META={int(k):v for k,v in read_json(HOTEL_META,{}).items()}
  LIMIT=load_settings()["limits"]
  OUT={"cities":{},"stops":[],"guides":G,"tripwide":SD["tripwide"]}
  for city in sorted({s["city"] for s in STOPS}):
      stops=[s for s in STOPS if s["city"]==city]
      lists={s["id"]:{h["id"]:h for h in read_json(list_path(s["id"]),[])} for s in stops}
      sv=SAVED.get(city,set())
      # отели из плана и сохранённые, которых нет в свежей выдаче: берём последний известный снимок
      # (цену — только если он снят на те же даты, иначе без цены)
      for s in stops:
          for hid in sv|{s["anchor"],s["proposed"]}:
              if hid not in lists[s["id"]] and hid in META:
                  m=dict(META[hid]); same=m.get("_ci")==s["ci"].replace("-","") and m.get("_co")==s["co"].replace("-","")
                  # снимок с других дат: без цены и без акций, но значки и рейтинги отеля оставляем
                  if not same: m.update(night=None,total=None,tags=[],tc={k:v for k,v in (m.get("tc") or {}).items() if k in ("m","a","n","r")})
                  lists[s["id"]][hid]=m
      meta={}
      for s in stops:
          for hid,h in lists[s["id"]].items(): meta.setdefault(hid,h)
      special={s["anchor"] for s in stops}|{s["proposed"] for s in stops}|sv
      ids=set()
      for s in stops:
          for hid,h in lists[s["id"]].items():
              if h.get("night") and h["night"]<=LIMIT.get(city,5000): ids.add(hid)
      ids|=special
      HOT=load_hotels(city)
      ids=[i for i in ids if i in HOT and i in meta]
      AN={}
      for hid in ids:
          rec=HOT[hid]; d={"cr":rec["cr"],"fac":rec["fac"],"total":rec["total"]}; AN[hid]=(rec["a"],d,meta[hid])
      def rate(a,k,src): return a[src][k]/max(1,(a["n"] if src=="c" else a["npos"]))
      keysC=next(iter(AN.values()))[0]["c"].keys(); keysP=next(iter(AN.values()))[0]["p"].keys()
      big=[a for a,_,_ in AN.values() if a["n"]>=30]
      MED_C={k:st.median([rate(a,k,"c") for a in big]) for k in keysC}
      MED_P={k:st.median([rate(a,k,"p") for a in big]) for k in keysP}
      MEDS=st.median([(d.get("cr") or {}).get("ratingAll") for a,d,_ in AN.values() if a["n"]>=30 and (d.get("cr") or {}).get("ratingAll")])
      H=[]
      for hid,(a,d,m) in AN.items():
          n=a["n"]; c=a["c"]; pp=a["p"]; cr=d.get("cr") or {}
          lat=fnum(m.get("lat")); lng=fnum(m.get("lng"))
          score=cr.get("ratingAll") or fnum(m.get("score"))
          pros=[]
          if n>=5:
              cand=[]
              for k,v in pp.items():
                  r=v/max(1,a["npos"])
                  if v>=2 and r>=0.05: cand.append((r>MED_P[k]*1.1,r,k))
              cand.sort(reverse=True)
              for _,r,k in cand[:3]: pros.append(f"{POSTXT[k]} {pct(r)} довольных гостей")
          cons=[]
          if n>=5:
              red=[];other=[]
              for k,v in c.items():
                  if k=="insect": continue
                  r=v/max(1,n)
                  if k in ("roach","ants","smell","damp"):
                      if v>=2 and (r>MED_C[k]*1.15 or v>=4): red.append((WEIGHT[k]*v,k,v,r))
                  elif v>=2 and r>=0.006 and r>MED_C[k]*1.15: other.append((WEIGHT[k]*(r+0.002)/(MED_C[k]+0.004),k,v,r))
              red.sort(reverse=True); other.sort(reverse=True)
              for _,k,v,r in (red+other)[:4]:
                  extra=f", из них {a['crec'][k]} за 2025–2026" if k in ("roach","ants","smell","damp") and a["crec"].get(k) else ""
                  cons.append(f"{CONTXT[k]} — {pct(r)} отзывов" if k=="noise" else f"{CONTXT[k]} — {v} {plural(v,'отзыв','отзыва','отзывов')}{extra}")
          for key,lab in (("ratingFacility","удобства"),("ratingRoom","чистота"),("ratingLocation","расположение")):
              v=cr.get(key)
              if v and v<8.0 and len(cons)<4: cons.append(f"Низкая оценка за {lab}: {str(v).replace('.',',')}")
          if 0<n<30: cons.append(f"Мало отзывов ({n}) — статистика неточная")
          if n==0: cons.append("Отзывов пока нет")
          if not cons: cons.append("Повторяющихся жалоб нет")
          yes=d["fac"]["yes"]; am=[k for k,rx in AMR if any(re.search(rx,f,re.I) for f in yes)]
          comp=None
          if n>=5 and score:
              per=lambda x:x/(n+50)*100
              pen=min(2.0,0.30*per(c["roach"])+0.10*per(c["ants"])+0.12*per(c["smell"])+0.20*per(c["damp"]))
              negsh=a["neg"]/max(1,n)*100
              negadj=max(-0.5,min(0.15,-(negsh-5)*0.03)) if n>=60 else min(0,-(negsh-5)*0.03)
              trend=max(-0.3,min(0.2,(a["recent"]-score)*0.5)) if n>=120 and a["recent"] else 0
              small=-0.3 if n<15 else 0
              base=round((n*score+25*MEDS)/(n+25),2)
              comp=[base,round(-pen,2),round(negadj,2),round(trend,2),small]
          H.append(dict(id=hid,nm=m["name"],cat=m.get("cat") or "",st=m.get("star") or 0,z=zone_of(city,m,lat or 0,lng or 0),la=lat,ln=lng,
            sc=score,cl=cr.get("ratingRoom"),fa=cr.get("ratingFacility"),lo=cr.get("ratingLocation"),se=cr.get("ratingService"),rv=cr.get("showCommentNum") or d.get("total") or 0,an=n,tot=d.get("total") or n,
            ng=round(a["neg"]/max(1,n)*100,1) if n else None,ns=round(c["noise"]/max(1,n)*100,1) if n else None,
            ro=c["roach"],ror=a["crec"]["roach"],at=c["ants"],sm=c["smell"],smr=a["crec"]["smell"],dm=c["damp"],dmr=a["crec"]["damp"],ins=c["insect"],insr=a["crec"]["insect"],
            am=am,amn=len(yes),yr=d["fac"].get("yr",""),ry=d["fac"].get("rn",""),pr=pros,co=cons[:5],cp=comp,sv=int(hid in sv),
            o=m.get("oid") or "",mt=m.get("metro") or [],ad=m.get("addr") or ""))
      # у части жилья (чаще квартир) Островок не указывает район: берём район ближайших соседей в радиусе 700 м
      rest=G[city]["districts"][-1]["t"]
      known=[h for h in H if h["z"]!=rest and h["la"]]
      for h in H:
          if h["z"]!=rest or not h["la"] or (AN[h["id"]][2].get("zone")): continue
          near=sorted(((hav(h["la"],h["ln"],k["la"],k["ln"]),k["z"]) for k in known),key=lambda x:x[0])[:5]
          near=[z for d,z in near if d<=0.7]
          if near: h["z"]=max(set(near),key=near.count)
      OUT["cities"][city]={"hotels":H,"meds":MEDS}
      for s in stops:
          L=lists[s["id"]]; P={}
          sp_stop={s["anchor"],s["proposed"]}|sv   # forced only for THIS period: its own plan hotels (+ saved)
          hidset={h["id"] for h in H}
          for hid in hidset:
              m=L.get(hid)
              if not m: continue
              night=m.get("night"); 
              if not night and hid not in sp_stop: continue
              if night and night>LIMIT.get(city,5000) and hid not in sp_stop: continue
              total=m.get("total") or (night*s["nights"] if night else None)
              dorm,shared,nowin=room_flags(m.get("room"),m.get("name"))
              free=any("Бесплатная отмена" in (t or "") for t in m.get("tags") or [])
              # 8-й элемент — отметки площадки бронирования (у Островка пока нет), 0
              P[hid]=[round(total/ s["nights"]) if total else night,total,int(free),m.get("room") or "",int(dorm),int(shared),int(nowin),m.get("tc") or 0]
          an=meta.get(s["anchor"]) or {}
          # точка отсчёта расстояний: отель из плана или просто место (у Москвы — Красная площадь, alat/alng в stops.json)
          so=dict(s); so["limit"]=LIMIT.get(city,5000); so["prices"]=P; so["alat"]=fnum(an.get("lat")) or s.get("alat"); so["alng"]=fnum(an.get("lng")) or s.get("alng")
          OUT["stops"].append(so)
      log(city,"hotels",len(H),"reviews",sum(h["an"] for h in H),"median",MEDS, {s["id"]:len([1 for p in OUT["stops"] if p["id"]==s["id"] for _ in p["prices"]]) for s in stops})
  OUT["stops"].sort(key=lambda s:s["ci"])
  return OUT


# ---------- «Коротко об отеле»: фишки, тревожные сигналы, расположение
from .notes import FEAT, FLAG
FL={k:l for k,l,_ in FEAT}; FW={k:(l,w) for k,l,w,_ in FLAG}
def hav(a,b,c,d):
    R=6371;p=math.pi/180
    return 2*R*math.asin(math.sqrt(math.sin((c-a)*p/2)**2+math.cos(a*p)*math.cos(c*p)*math.sin((d-b)*p/2)**2))
def plural(n,a,b,c):
    n=abs(n)%100;n1=n%10
    if 10<n<20: return c
    if n1==1: return a
    if 2<=n1<=4: return b
    return c
def dist(km): return f"{int(round(km*1000/10)*10)} м" if km<1 else f"{km:.1f} км".replace(".",",")
def how(km,city,island=False):
    if km<=1.2: return f"≈{max(1,round(km*16))} мин пешком"
    return f"≈{round(km*1.3/25*60+4)} мин на такси"
def loc(city,h):
    """«Где»: ближайшее метро по данным Островка."""
    la,ln=h.get("la"),h.get("ln")
    if not la: return ""
    parts=[]
    mt=[x for x in h.get("mt") or [] if x and x[0] and x[1] is not None]
    if mt:
        nm,d=mt[0]; km=d/1000
        parts.append(f"м. {nm} — {dist(km)}, {how(km,city)}" if km<=1.5 else f"до метро далеко: {nm} в {dist(km)}")
    # расстояние до Красной площади сайт пишет сам отдельной строкой
    return "; ".join(parts)


def merge_notes(D, RAW):
    """Накладывает на отели «Чем известен», «Осторожно», «Где» и счётчик балконов."""
    for city,o in D["cities"].items():
        R=RAW[city]; H=o["hotels"]
        big=[R[str(h["id"])] for h in H if R[str(h["id"])][0]>=30]
        MF={k:st.median([b[1][k]/b[0] for b in big]) for k,_,_ in FEAT}
        MR={k:st.median([b[2][k]/b[0] for b in big]) for k,_,_,_ in FLAG}
        for h in H:
            n,fc,rc=R[str(h["id"])]
            fx=[]
            if n>=5:
                for k,l,_ in FEAT:
                    c=fc[k]; s=c/n
                    if c>=(2 if n<40 else 3) and s>=max(0.02,2*MF[k]): fx.append(((s+0.005)/(MF[k]+0.01),l,c,s))
                fx.sort(reverse=True)
            h["fx"]=[(f"{l} — пишут в {round(s*100)}% отзывов" if s>=0.05 else f"{l} ({c} {plural(c,'отзыв','отзыва','отзывов')})") for _,l,c,s in fx[:4]]
            rf=[]
            if n>=5:
                for k,l,w,_ in FLAG:
                    c=rc[k]; s=c/n
                    if k=="notrec":
                        if c>=3 and s>=0.02: rf.append((w*s*50,f"{l} — {c} {plural(c,'отзыв','отзыва','отзывов')}"))
                        continue
                    if c>=2 and (s>=max(0.008,2*MR[k]) or (w>=2.5 and c>=2)): rf.append((w*s*50+w,f"{l} — {c} {plural(c,'отзыв','отзыва','отзывов')}"))
                rf.sort(reverse=True); rf=[x[1] for x in rf[:4]]
                sc=h.get("sc")
                rec=None
            else: rf=[]
            if h.get("ng") is not None and h["ng"]>=15: rf.append(f"негативный каждый {max(2,round(100/h['ng']))}-й отзыв")
            h["rf"]=rf
            h["lc"]=loc(city,h)
            h["bal"]=fc["balcony"]
        print(city,"fx>0:",sum(1 for h in H if h["fx"]),"rf>0:",sum(1 for h in H if h["rf"]),"lc:",sum(1 for h in H if h["lc"]))

    return D


def notes_raw(D):
    """Счётчики фишек и сигналов из кеша отелей (посчитаны при скачивании отзывов)."""
    RAW = {}
    for c in D["cities"]:
        HOT = load_hotels(c)
        RAW[c] = {str(h["id"]): HOT[h["id"]]["nt"] for h in D["cities"][c]["hotels"]}
    return RAW


def export_site(D, out=SITE_DATA, built_at=""):
    """Раскладывает данные для сайтов: index.json, cities/<город>.json, prices/<остановка>.json."""
    stops = []
    for s in D["stops"]:
        s = dict(s); prices = s.pop("prices")
        write_json(out / "prices" / f"{s['id']}.json", prices)
        s["priceCount"] = len(prices); stops.append(s)
    cities = {}
    for c, o in D["cities"].items():
        write_json(out / "cities" / f"{c}.json", o["hotels"])
        cities[c] = {"meds": o["meds"], "count": len(o["hotels"])}
    idx = {"stops": stops, "guides": D["guides"], "tripwide": D["tripwide"], "cities": cities,
           "saved": read_json(CONTENT / "saved.json", {}), "builtAt": built_at,
           # координаты мест для карт на вкладках «Что посмотреть», «Поездки», «События»: город → вид → название → [lat, lng]
           "places": read_json(CONTENT / "places.json", {}),
           "reviews": sum(sum(h["an"] for h in o["hotels"]) for o in D["cities"].values())}
    write_json(out / "index.json", idx)
    return idx
