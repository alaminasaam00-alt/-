import os, re, sqlite3, secrets, json, hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
import httpx, feedparser, threading, time
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

DATABASE_URL=os.getenv("DATABASE_URL","").strip()
DB_FILE=os.getenv("SQLITE_PATH","./radar.db")
ADMIN_TOKEN=os.getenv("RADAR_ADMIN_TOKEN","")
BOK_ACCOUNT=os.getenv("BOK_ACCOUNT_NUMBER","")
BOK_NAME=os.getenv("BOK_ACCOUNT_NAME","")
PG=bool(DATABASE_URL)
if PG:
    import psycopg
    from psycopg.rows import dict_row
app=FastAPI(title="NOVA RADAR",version="1.1.0")
_last_scan=0.0
_scan_lock=threading.Lock()

SOURCES=[
 {"id":"grants_us","name":"Grants.gov","type":"grant","url":"https://api.grants.gov/v1/api/search2"},
 {"id":"ted_comp","name":"TED — Computer & IT","type":"tender","url":"https://ted.europa.eu/en/simap/rss-feed/-/rss/search/comp"},
 {"id":"ted_serv","name":"TED — Services","type":"tender","url":"https://ted.europa.eu/en/simap/rss-feed/-/rss/search/serv"},
 {"id":"ted_ener","name":"TED — Energy","type":"tender","url":"https://ted.europa.eu/en/simap/rss-feed/-/rss/search/ener"},
 {"id":"ted_tran","name":"TED — Transport","type":"tender","url":"https://ted.europa.eu/en/simap/rss-feed/-/rss/search/tran"},
 {"id":"ted_reco","name":"TED — R&D","type":"tender","url":"https://ted.europa.eu/en/simap/rss-feed/-/rss/search/reco"},
 {"id":"worldbank","name":"World Bank Procurement","type":"tender","url":"https://search.worldbank.org/api/v2/procnotices"}]

def conn():
    if PG: return psycopg.connect(DATABASE_URL,row_factory=dict_row)
    c=sqlite3.connect(DB_FILE); c.row_factory=sqlite3.Row; return c
def q(s): return s.replace("?","%s") if PG else s

def init():
    c=conn()
    stmts=[
      "CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE,name TEXT,created_at TEXT)",
      "CREATE TABLE IF NOT EXISTS profiles(user_id TEXT PRIMARY KEY,keywords TEXT,regions TEXT,types TEXT,min_score INTEGER DEFAULT 20)",
      "CREATE TABLE IF NOT EXISTS opportunities(id TEXT PRIMARY KEY,source_id TEXT,external_id TEXT,title TEXT,description TEXT,url TEXT,deadline TEXT,amount TEXT,country TEXT,kind TEXT,score INTEGER,first_seen TEXT,last_seen TEXT,UNIQUE(source_id,external_id))",
      "CREATE TABLE IF NOT EXISTS matches(id TEXT PRIMARY KEY,user_id TEXT,opportunity_id TEXT,score INTEGER,status TEXT,created_at TEXT,UNIQUE(user_id,opportunity_id))",
      "CREATE TABLE IF NOT EXISTS subscriptions(id TEXT PRIMARY KEY,user_id TEXT,plan TEXT,status TEXT,amount INTEGER,currency TEXT,created_at TEXT,renew_at TEXT)",
      "CREATE TABLE IF NOT EXISTS payments(id TEXT PRIMARY KEY,subscription_id TEXT,amount INTEGER,currency TEXT,reference TEXT,status TEXT,created_at TEXT)",
      "CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,source_id TEXT,status TEXT,items INTEGER,error TEXT,created_at TEXT)",
      "CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,action TEXT,payload TEXT,created_at TEXT)"]
    for s in stmts: c.execute(s)
    c.commit(); c.close()
init()

class Signup(BaseModel): email:str; name:str=Field(min_length=1,max_length=120)
class Profile(BaseModel): user_id:str; keywords:str=Field(min_length=1); regions:str=""; types:str="tender,grant"; min_score:int=20
class Subscribe(BaseModel): user_id:str; plan:str="pro"
class Payment(BaseModel): subscription_id:str; reference:str=Field(min_length=3,max_length=120); amount:int=Field(gt=0)

def audit(action,payload):
    c=conn(); c.execute(q("INSERT INTO audit(action,payload,created_at) VALUES(?,?,?)"),(action,json.dumps(payload,ensure_ascii=False),datetime.now(timezone.utc).isoformat())); c.commit(); c.close()

def token_for(email): return hashlib.sha256((email+"|nova-radar").encode()).hexdigest()[:24]

def score_item(title,desc,keywords,regions,types_text,kind,country):
    text=(title+" "+desc).lower()
    kws=[x.strip().lower() for x in re.split(r"[,;\n]+",keywords) if x.strip()]
    score=0
    for k in kws:
        if k in text: score+=min(18,8+len(k)//4)
    regs=[x.strip().lower() for x in re.split(r"[,;\n]+",regions) if x.strip()]
    if regs and any(r in (country+" "+text).lower() for r in regs): score+=18
    types=[x.strip().lower() for x in re.split(r"[,;\n]+",kind) if x.strip()]
    if types and kind.lower() in types: score+=12
    if any(w in text for w in ["deadline","closing","tender","grant","procurement","request for proposals","framework"]): score+=8
    return min(100,score)

def upsert(source_id,external_id,title,desc,url,deadline="",amount="",country="",kind="tender"):
    now=datetime.now(timezone.utc).isoformat()
    c=conn(); existing=c.execute(q("SELECT id FROM opportunities WHERE source_id=? AND external_id=?"),(source_id,external_id)).fetchone()
    oid=existing["id"] if existing else "opp_"+secrets.token_hex(9)
    if existing:
        c.execute(q("UPDATE opportunities SET title=?,description=?,url=?,deadline=?,amount=?,country=?,kind=?,last_seen=? WHERE id=?"),(title,desc,url,deadline,amount,country,kind,now,oid))
    else:
        c.execute(q("INSERT INTO opportunities VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)"),(oid,source_id,external_id,title,desc,url,deadline,amount,country,kind,0,now,now))
    c.commit(); c.close(); return oid

def ingest_grants():
    r=httpx.post("https://www.grants.gov/v1/api/search2",json={"rows":50,"keyword":"","oppStatuses":"forecasted|posted"},timeout=30)
    r.raise_for_status(); data=r.json().get("data",{}).get("oppHits",[]); n=0
    for x in data:
        oid=str(x.get("id") or x.get("number") or secrets.token_hex(6))
        url="https://www.grants.gov/search-results-detail/"+quote(str(x.get("id","")))
        upsert("grants_us",oid,x.get("title",""),x.get("title",""),url,x.get("closeDate",""),"",x.get("agencyName",""),"grant"); n+=1
    return n

def ingest_rss(src):
    resp=httpx.get(src["url"],headers={"User-Agent":"NOVA-RADAR/1.1 (+https://numo-nova.onrender.com)"},timeout=30,follow_redirects=True); resp.raise_for_status(); feed=feedparser.parse(resp.content); n=0
    for e in feed.entries[:120]:
        ext=e.get("id") or e.get("link") or e.get("title")
        title=e.get("title","").strip(); desc=re.sub("<[^>]+>"," ",e.get("summary",""))
        upsert(src["id"],ext,title,desc,e.get("link",""),e.get("published",""),"",title.split("–")[0].strip(),src["type"]); n+=1
    return n

def match_all():
    c=conn(); profiles=c.execute("SELECT * FROM profiles").fetchall(); opps=c.execute("SELECT * FROM opportunities ORDER BY last_seen DESC LIMIT 1000").fetchall()
    for p in profiles:
        for o in opps:
            sc=score_item(o["title"],o["description"],p["keywords"],p["regions"],p["types"],o["kind"],o["country"])
            if sc>=int(p["min_score"]):
                mid="mat_"+hashlib.sha1((p["user_id"]+"|"+o["id"]).encode()).hexdigest()[:18]
                c.execute(q("INSERT INTO matches(id,user_id,opportunity_id,score,status,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,opportunity_id) DO UPDATE SET score=excluded.score"),(mid,p["user_id"],o["id"],sc,"new",datetime.now(timezone.utc).isoformat()))
    c.commit(); c.close()

def ingest_worldbank():
    url="https://search.worldbank.org/api/v2/procnotices"
    r=httpx.get(url,params={"format":"json","rows":100,"os":0,"srt":"noticedate desc,id asc"},headers={"User-Agent":"NOVA-RADAR/1.1 (+https://numo-nova.onrender.com)"},timeout=30)
    r.raise_for_status(); data=r.json().get("procnotices",[])
    if isinstance(data,dict): data=list(data.values())
    n=0
    for x in data:
        ext=str(x.get("id") or x.get("bid_reference_no") or secrets.token_hex(6))
        title=x.get("bid_description") or x.get("project_name") or x.get("notice_type") or "World Bank procurement notice"
        desc=" ".join(str(x.get(k) or "") for k in ["project_name","bid_description","notice_type","procurement_method_name"])
        url2=x.get("url") or ("https://projects.worldbank.org/en/projects-operations/procurement-detail/"+ext)
        upsert("worldbank",ext,title,desc,url2,x.get("submission_date",""),"",x.get("project_ctry_name",""),"tender"); n+=1
    return n

def run_ingestion():
    results=[]
    for src in SOURCES:
        c=conn(); runid="run_"+secrets.token_hex(7); now=datetime.now(timezone.utc).isoformat()
        try:
            n=ingest_grants() if src["id"]=="grants_us" else (ingest_worldbank() if src["id"]=="worldbank" else ingest_rss(src))
            c.execute(q("INSERT INTO runs VALUES(?,?,?,?,?,?)"),(runid,src["id"],"ok",n,"",now)); c.commit(); results.append((src["id"],n,"ok"))
        except Exception as e:
            c.execute(q("INSERT INTO runs VALUES(?,?,?,?,?,?)"),(runid,src["id"],"error",0,str(e)[:500],now)); c.commit(); print("NOVA_RADAR_SOURCE_ERROR",src["id"],repr(e),flush=True); results.append((src["id"],0,"error"))
        finally: c.close()
    match_all(); print("NOVA_RADAR_SCAN", results, flush=True); return results

@app.get("/health")
def health():
    c=conn(); c.execute(q("SELECT 1")); c.close(); return {"status":"ok","service":"nova-radar","version":"1.0.0","sources":len(SOURCES)}

def _background_scan():
    time.sleep(5)
    print("NOVA_RADAR_SCHEDULER_STARTED", flush=True)
    while True:
        try:
            if _scan_lock.acquire(blocking=False):
                try:
                    run_ingestion()
                finally:
                    _scan_lock.release()
        except Exception as e:
            print("NOVA_RADAR_SCAN_ERROR", repr(e), flush=True)
        time.sleep(1800)

threading.Thread(target=_background_scan,daemon=True,name="radar-scheduler").start()

@app.get("/api/sources")
def sources(): return SOURCES

@app.post("/api/signup")
def signup(x:Signup):
    c=conn(); u=c.execute(q("SELECT * FROM users WHERE email=?"),(x.email.lower(),)).fetchone()
    if u: c.close(); return {"user_id":u["id"],"access_token":token_for(x.email.lower())}
    uid="usr_"+secrets.token_hex(8); c.execute(q("INSERT INTO users VALUES(?,?,?,?)"),(uid,x.email.lower(),x.name,datetime.now(timezone.utc).isoformat())); c.commit(); c.close(); return {"user_id":uid,"access_token":token_for(x.email.lower())}

@app.post("/api/profile")
def profile(x:Profile):
    c=conn(); u=c.execute(q("SELECT id FROM users WHERE id=?"),(x.user_id,)).fetchone()
    if not u: c.close(); raise HTTPException(404,"User not found")
    c.execute(q("INSERT INTO profiles(user_id,keywords,regions,types,min_score) VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET keywords=excluded.keywords,regions=excluded.regions,types=excluded.types,min_score=excluded.min_score"),(x.user_id,x.keywords,x.regions,x.types,max(0,min(100,x.min_score)))); c.commit(); c.close(); match_all(); return {"status":"saved"}

@app.post("/api/scan")
def scan(authorization:str|None=Header(None)):
    if ADMIN_TOKEN and authorization!=f"Bearer {ADMIN_TOKEN}": raise HTTPException(401,"Admin authentication required")
    return {"results":run_ingestion()}

@app.get("/api/opportunities")
def opportunities(user_id:str|None=None,limit:int=50):
    c=conn()
    if user_id: rows=c.execute(q("SELECT o.*,m.score AS match_score,m.status AS match_status FROM matches m JOIN opportunities o ON o.id=m.opportunity_id WHERE m.user_id=? ORDER BY m.score DESC,o.last_seen DESC LIMIT ?"),(user_id,min(limit,200))).fetchall()
    else: rows=c.execute("SELECT * FROM opportunities ORDER BY last_seen DESC LIMIT "+str(min(limit,200))).fetchall()
    c.close(); return [dict(r) for r in rows]

@app.post("/api/subscribe")
def subscribe(x:Subscribe):
    prices={"starter":5000,"pro":15000,"business":30000}; amount=prices.get(x.plan)
    if not amount: raise HTTPException(400,"Invalid plan")
    c=conn(); u=c.execute(q("SELECT id FROM users WHERE id=?"),(x.user_id,)).fetchone()
    if not u: c.close(); raise HTTPException(404,"User not found")
    sid="sub_"+secrets.token_hex(8); now=datetime.now(timezone.utc); renew=now+timedelta(days=30)
    c.execute(q("INSERT INTO subscriptions VALUES(?,?,?,?,?,?,?,?)"),(sid,x.user_id,x.plan,"pending_payment",amount,"SDG",now.isoformat(),renew.isoformat())); c.commit(); c.close()
    return {"subscription_id":sid,"status":"pending_payment","amount":amount,"currency":"SDG","payment_method":"bank_transfer","account_name":BOK_NAME,"account_number":BOK_ACCOUNT}

@app.post("/api/payment")
def payment(x:Payment):
    c=conn(); s=c.execute(q("SELECT * FROM subscriptions WHERE id=?"),(x.subscription_id,)).fetchone()
    if not s: c.close(); raise HTTPException(404,"Subscription not found")
    if x.amount!=s["amount"]: c.close(); raise HTTPException(400,"Amount mismatch")
    pid="pay_"+secrets.token_hex(8); c.execute(q("INSERT INTO payments VALUES(?,?,?,?,?,?,?)"),(pid,x.subscription_id,x.amount,s["currency"],x.reference,"pending_review",datetime.now(timezone.utc).isoformat())); c.commit(); c.close(); return {"payment_id":pid,"status":"pending_review"}

@app.post("/api/admin/payments/{payment_id}/approve")
def approve(payment_id:str,authorization:str|None=Header(None)):
    if not ADMIN_TOKEN or authorization!=f"Bearer {ADMIN_TOKEN}": raise HTTPException(401,"Admin authentication required")
    c=conn(); p=c.execute(q("SELECT * FROM payments WHERE id=?"),(payment_id,)).fetchone()
    if not p: c.close(); raise HTTPException(404,"Payment not found")
    c.execute(q("UPDATE payments SET status='verified' WHERE id=?"),(payment_id,)); c.execute(q("UPDATE subscriptions SET status='active' WHERE id=?"),(p["subscription_id"],)); c.commit(); c.close(); return {"status":"active"}

@app.get("/api/status/{user_id}")
def status(user_id:str):
    c=conn(); rows=c.execute(q("SELECT * FROM subscriptions WHERE user_id=? ORDER BY created_at DESC"),(user_id,)).fetchall(); c.close(); return [dict(x) for x in rows]

@app.get("/api/stats")
def stats():
    c=conn(); a=c.execute("SELECT COUNT(*) n FROM opportunities").fetchone()["n"]; m=c.execute("SELECT COUNT(*) n FROM matches").fetchone()["n"]; r=c.execute("SELECT COUNT(*) n FROM runs WHERE status='ok'").fetchone()["n"]; c.close(); return {"opportunities":a,"matches":m,"successful_scans":r}

@app.get("/",response_class=HTMLResponse)
def home():
    return """<!doctype html><html lang='ar' dir='rtl'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>NOVA RADAR</title><style>body{font-family:system-ui;background:#07111f;color:#eef6ff;margin:0}.wrap{max-width:1050px;margin:auto;padding:28px}.hero,.card{background:#0e1b2e;border:1px solid #203653;border-radius:20px;padding:24px;margin:14px 0}.hero{background:linear-gradient(145deg,#102b46,#0b1728)}h1{font-size:42px;margin:0 0 8px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.pill{display:inline-block;padding:6px 10px;border-radius:999px;background:#173552;margin:3px}.price{font-size:25px;font-weight:700}input,button{width:100%;box-sizing:border-box;padding:12px;border-radius:10px;border:1px solid #34516f;background:#091626;color:#fff;margin:5px 0}button{background:#1b7cff;border:0;font-weight:700;cursor:pointer}.muted{color:#a9bdd1}.opp{border-top:1px solid #29415e;padding:14px 0}.score{font-weight:800;color:#6ee7b7}</style><body><div class='wrap'><div class='hero'><h1>رادار الفرص الذكي</h1><p>محرك يعمل باستمرار لالتقاط المناقصات والمنح والفرص العامة، تصفيتها حسب نشاطك وترتيبها حسب مدى ملاءمتها.</p><span class='pill'>TED</span><span class='pill'>Grants.gov</span><span class='pill'>فحص دوري</span><span class='pill'>مطابقة ذكية</span></div><div class='grid'><div class='card'><h2>Starter</h2><div class='price'>5,000 SDG / شهر</div><p>ملف فرصة + تنبيهات أساسية.</p></div><div class='card'><h2>Pro</h2><div class='price'>15,000 SDG / شهر</div><p>مطابقة أعمق + نتائج أكثر.</p></div><div class='card'><h2>Business</h2><div class='price'>30,000 SDG / شهر</div><p>فرق وملفات متعددة.</p></div></div><div class='card'><h2>ابدأ ملفك</h2><input id='name' placeholder='الاسم'><input id='email' placeholder='البريد'><input id='keywords' placeholder='مثال: software, cybersecurity, solar'><input id='regions' placeholder='الدول/المناطق المطلوبة (اختياري)'><button onclick='start()'>إنشاء الملف وبدء الرصد</button><pre id='out'></pre></div><div class='card'><h2>الفرص الحالية</h2><button onclick='loadOpps()'>تحديث النتائج</button><div id='ops' class='muted'>أنشئ ملفاً أولاً.</div></div></div><script>let uid=localStorage.getItem("uid");async function start(){let r=await fetch('/api/signup',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({name:document.getElementById("name").value.trim(),email:document.getElementById("email").value.trim()})});let x=await r.json();uid=x.user_id;localStorage.uid=uid;await fetch('/api/profile',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({user_id:uid,keywords:document.getElementById("keywords").value,regions:document.getElementById("regions").value,types:'tender,grant',min_score:20})});out.textContent='تم إنشاء الملف. يتم تحديث الرادار دورياً.';loadOpps()}async function loadOpps(){if(!uid)return;let r=await fetch('/api/opportunities?user_id='+encodeURIComponent(uid));let xs=await r.json();ops.innerHTML=xs.length?xs.map(o=>'<div class="opp"><b>'+o.title+'</b><div class="score">ملاءمة: '+o.match_score+'%</div><div>'+o.source_id+' — '+(o.country||'')+'</div><a href="'+o.url+'" target="_blank" rel="noopener" style="color:#8fc7ff">فتح المصدر</a></div>').join(''):'لا توجد نتائج مطابقة بعد.'}loadOpps();</script></body></html>"""

if __name__=="__main__":
    import uvicorn
    uvicorn.run(app,host="0.0.0.0",port=int(os.getenv("PORT","10000")))
