import os,sqlite3,secrets,hashlib,base64,hmac,json,re,threading,time
from datetime import datetime,timezone,timedelta
from fastapi import FastAPI,HTTPException,Header,Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel,EmailStr,Field

DB=os.getenv("SQLITE_PATH","./bidpilot.db"); SECRET=os.getenv("APP_SECRET") or secrets.token_hex(32); ADMIN=os.getenv("RADAR_ADMIN_TOKEN","")
BOK=os.getenv("BOK_ACCOUNT_NUMBER",""); BOK_NAME=os.getenv("BOK_ACCOUNT_NAME","الأمين عثمان الدين الأمين محمد")
PLANS={"starter":(10000,5),"pro":(25000,30),"business":(50000,200)}
app=FastAPI(title="BidPilot",version="2.0.0")

def now(): return datetime.now(timezone.utc)
def iso(d=None): return (d or now()).isoformat()
def db():
 c=sqlite3.connect(DB,timeout=30,check_same_thread=False); c.row_factory=sqlite3.Row; c.execute("PRAGMA journal_mode=WAL"); return c
def init():
 c=db(); c.executescript("""
 CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE,name TEXT,password TEXT,created TEXT);
 CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT,expires TEXT);
 CREATE TABLE IF NOT EXISTS tenders(id TEXT PRIMARY KEY,user_id TEXT,title TEXT,buyer TEXT,deadline TEXT,value TEXT,status TEXT,source TEXT,created TEXT);
 CREATE TABLE IF NOT EXISTS requirements(id TEXT PRIMARY KEY,tender_id TEXT,text TEXT,category TEXT,mandatory INTEGER,done INTEGER);
 CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,user_id TEXT,name TEXT,content TEXT,created TEXT);
 CREATE TABLE IF NOT EXISTS submissions(id TEXT PRIMARY KEY,tender_id TEXT,user_id TEXT,answers TEXT,status TEXT,updated TEXT);
 CREATE TABLE IF NOT EXISTS subscriptions(id TEXT PRIMARY KEY,user_id TEXT,plan TEXT,status TEXT,amount INTEGER,renew TEXT);
 CREATE TABLE IF NOT EXISTS payments(id TEXT PRIMARY KEY,subscription_id TEXT,reference TEXT,amount INTEGER,status TEXT,created TEXT);
 """); c.commit(); c.close()
init()

class Signup(BaseModel): name:str=Field(min_length=2,max_length=80); email:EmailStr; password:str=Field(min_length=8,max_length=128)
class Login(BaseModel): email:EmailStr; password:str
class TenderIn(BaseModel): title:str=Field(min_length=3,max_length=250); buyer:str=""; deadline:str=""; value:str=""; source:str=""; text:str=""
class ReqIn(BaseModel): text:str=Field(min_length=2,max_length=1000); category:str="general"; mandatory:bool=True
class DocIn(BaseModel): name:str=Field(min_length=2,max_length=150); content:str=Field(min_length=20,max_length=100000)
class AnswerIn(BaseModel): answers:dict
class SubIn(BaseModel): plan:str
class PayIn(BaseModel): subscription_id:str; reference:str=Field(min_length=3,max_length=120)

def ph(p):
 s=secrets.token_bytes(16); d=hashlib.pbkdf2_hmac("sha256",p.encode(),s,180000); return base64.b64encode(s+d).decode()
def pv(p,x):
 try:
  z=base64.b64decode(x); return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256",p.encode(),z[:16],180000),z[16:])
 except:return False
def auth(u):
 raw=f"{u}.{int(time.time())+2592000}"; sig=hmac.new(SECRET.encode(),raw.encode(),"sha256").hexdigest()
 return base64.urlsafe_b64encode(f"{raw}.{sig}".encode()).decode()
def user(authorization:str|None=Header(None)):
 if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401,"تسجيل الدخول مطلوب")
 c=db(); s=c.execute("SELECT * FROM sessions WHERE token=?",(authorization[7:],)).fetchone()
 if not s or s["expires"]<iso(): c.close(); raise HTTPException(401,"الجلسة منتهية")
 u=c.execute("SELECT * FROM users WHERE id=?",(s["user_id"],)).fetchone(); c.close()
 if not u: raise HTTPException(401,"الحساب غير موجود")
 return u
def create_session(uid):
 t=auth(uid); c=db(); c.execute("INSERT INTO sessions VALUES(?,?,?)",(t,uid,iso(now()+timedelta(days=30)))); c.commit(); c.close(); return t
def extract(text,tender_id):
 pats=[("deadline",r"(?:deadline|closing date|submission date|آخر موعد|تاريخ الإغلاق)[:\s-]*([^\n.;]{3,60})"),("budget",r"(?:budget|value|contract value|قيمة العقد|الميزانية)[:\s-]*([^\n.;]{2,60})"),("eligibility",r"(?:eligible|eligibility|qualification|أهلية|شروط التأهيل)[:\s-]*([^\n.]{5,200})")]
 c=db()
 for cat,p in pats:
  for m in re.finditer(p,text,re.I):
   c.execute("INSERT INTO requirements VALUES(?,?,?,?,?,?)",("req_"+secrets.token_hex(7),tender_id,m.group(1).strip(),cat,1,0))
 for line in text.splitlines():
  s=line.strip()
  if len(s)>15 and any(k in s.lower() for k in ["must ","required","shall ","يجب","يشترط","يلزم"]):
   c.execute("INSERT INTO requirements VALUES(?,?,?,?,?,?)",("req_"+secrets.token_hex(7),tender_id,s,"compliance",1,0))
 c.commit(); c.close()
@app.get("/health")
def health(): return {"status":"ok","service":"bidpilot","version":"2.0.0"}
@app.post("/api/signup")
def signup(x:Signup):
 c=db()
 if c.execute("SELECT 1 FROM users WHERE email=?",(x.email.lower(),)).fetchone(): c.close(); raise HTTPException(409,"البريد مستخدم")
 uid="u_"+secrets.token_hex(8); c.execute("INSERT INTO users VALUES(?,?,?,?,?)",(uid,x.email.lower(),x.name,ph(x.password),iso())); c.commit(); c.close()
 return {"token":create_session(uid),"name":x.name}
@app.post("/api/login")
def login(x:Login):
 c=db(); u=c.execute("SELECT * FROM users WHERE email=?",(x.email.lower(),)).fetchone(); c.close()
 if not u or not pv(x.password,u["password"]): raise HTTPException(401,"بيانات الدخول غير صحيحة")
 return {"token":create_session(u["id"]),"name":u["name"]}
@app.post("/api/tenders")
def tender(x:TenderIn,u=Depends(user)):
 tid="t_"+secrets.token_hex(8); c=db(); c.execute("INSERT INTO tenders VALUES(?,?,?,?,?,?,?,?,?)",(tid,u["id"],x.title,x.buyer,x.deadline,x.value,"active",x.source,iso())); c.commit(); c.close()
 if x.text.strip(): extract(x.text,tid)
 return {"tender_id":tid}
@app.get("/api/tenders")
def tenders(u=Depends(user)):
 c=db(); rows=c.execute("SELECT t.*,COUNT(r.id) requirements,SUM(CASE WHEN r.done=1 THEN 1 ELSE 0 END) done FROM tenders t LEFT JOIN requirements r ON r.tender_id=t.id WHERE t.user_id=? GROUP BY t.id ORDER BY t.created DESC",(u["id"],)).fetchall(); c.close(); return [dict(x) for x in rows]
@app.get("/api/tenders/{tid}")
def tender_get(tid,u=Depends(user)):
 c=db(); t=c.execute("SELECT * FROM tenders WHERE id=? AND user_id=?",(tid,u["id"])).fetchone()
 if not t: c.close(); raise HTTPException(404,"المناقصة غير موجودة")
 r=c.execute("SELECT * FROM requirements WHERE tender_id=? ORDER BY mandatory DESC,id",(tid,)).fetchall(); s=c.execute("SELECT * FROM submissions WHERE tender_id=? AND user_id=?",(tid,u["id"])).fetchone(); c.close()
 return {"tender":dict(t),"requirements":[dict(x) for x in r],"submission":dict(s) if s else None}
@app.post("/api/tenders/{tid}/requirements")
def requirement(tid,x:ReqIn,u=Depends(user)):
 c=db(); t=c.execute("SELECT id FROM tenders WHERE id=? AND user_id=?",(tid,u["id"])).fetchone()
 if not t:c.close();raise HTTPException(404,"غير موجود")
 rid="req_"+secrets.token_hex(7);c.execute("INSERT INTO requirements VALUES(?,?,?,?,?,?)",(rid,tid,x.text,x.category,1 if x.mandatory else 0,0));c.commit();c.close();return {"id":rid}
@app.post("/api/requirements/{rid}/done")
def req_done(rid,u=Depends(user)):
 c=db(); r=c.execute("SELECT r.id FROM requirements r JOIN tenders t ON t.id=r.tender_id WHERE r.id=? AND t.user_id=?",(rid,u["id"])).fetchone()
 if not r:c.close();raise HTTPException(404,"غير موجود")
 c.execute("UPDATE requirements SET done=CASE done WHEN 1 THEN 0 ELSE 1 END WHERE id=?",(rid,));c.commit();c.close();return {"ok":True}
@app.post("/api/documents")
def document(x:DocIn,u=Depends(user)):
 did="doc_"+secrets.token_hex(8);c=db();c.execute("INSERT INTO documents VALUES(?,?,?,?,?)",(did,u["id"],x.name,x.content,iso()));c.commit();c.close();return {"document_id":did}
@app.get("/api/documents")
def documents(u=Depends(user)):
 c=db();r=c.execute("SELECT id,name,created FROM documents WHERE user_id=? ORDER BY created DESC",(u["id"],)).fetchall();c.close();return [dict(x) for x in r]
@app.post("/api/tenders/{tid}/draft")
def draft(tid,u=Depends(user)):
 c=db();t=c.execute("SELECT * FROM tenders WHERE id=? AND user_id=?",(tid,u["id"],)).fetchone(); req=c.execute("SELECT * FROM requirements WHERE tender_id=?",(tid,)).fetchall(); docs=c.execute("SELECT * FROM documents WHERE user_id=?",(u["id"],)).fetchall()
 if not t:c.close();raise HTTPException(404,"غير موجود")
 answers={}
 for r in req:
  best=""
  terms=[w.lower() for w in re.findall(r"[A-Za-z\u0600-\u06ff]{4,}",r["text"])[:8]]
  for d in docs:
   if sum(1 for w in terms if w in d["content"].lower())>=max(1,len(terms)//4): best=d["content"][:1200];break
  answers[r["id"]]=best or "مطلوب إعداد إجابة مخصصة بعد مراجعة هذا الشرط."
 sid="sub_"+secrets.token_hex(8);c.execute("INSERT INTO submissions VALUES(?,?,?,?,?,?)",(sid,tid,u["id"],json.dumps(answers,ensure_ascii=False),"draft",iso()));c.commit();c.close();return {"submission_id":sid,"answers":answers}
@app.post("/api/subscribe")
def subscribe(x:SubIn,u=Depends(user)):
 if x.plan not in PLANS:raise HTTPException(400,"الخطة غير صحيحة")
 amount,_=PLANS[x.plan];sid="sub_"+secrets.token_hex(8);c=db();c.execute("INSERT INTO subscriptions VALUES(?,?,?,?,?,?)",(sid,u["id"],x.plan,"pending",amount,iso(now()+timedelta(days=30))));c.commit();c.close();return {"subscription_id":sid,"amount":amount,"account_name":BOK_NAME,"account_number":BOK}
@app.post("/api/payment")
def payment(x:PayIn,u=Depends(user)):
 c=db();s=c.execute("SELECT * FROM subscriptions WHERE id=? AND user_id=?",(x.subscription_id,u["id"])).fetchone()
 if not s:c.close();raise HTTPException(404,"الاشتراك غير موجود")
 pid="p_"+secrets.token_hex(8);c.execute("INSERT INTO payments VALUES(?,?,?,?,?,?)",(pid,s["id"],x.reference,s["amount"],"pending",iso()));c.commit();c.close();return {"payment_id":pid,"status":"pending"}
@app.get("/api/admin/payments")
def admin_payments(authorization:str|None=Header(None)):
 if not ADMIN or authorization!="Bearer "+ADMIN:raise HTTPException(401,"غير مصرح")
 c=db();r=c.execute("SELECT p.*,s.plan,u.email FROM payments p JOIN subscriptions s ON s.id=p.subscription_id JOIN users u ON u.id=s.user_id WHERE p.status='pending' ORDER BY p.created").fetchall();c.close();return [dict(x) for x in r]
@app.post("/api/admin/payments/{pid}/approve")
def approve(pid,authorization:str|None=Header(None)):
 if not ADMIN or authorization!="Bearer "+ADMIN:raise HTTPException(401,"غير مصرح")
 c=db();p=c.execute("SELECT * FROM payments WHERE id=?",(pid,)).fetchone()
 if not p:c.close();raise HTTPException(404,"غير موجود")
 c.execute("UPDATE payments SET status='verified' WHERE id=?",(pid,));c.execute("UPDATE subscriptions SET status='active',renew=? WHERE id=?",(iso(now()+timedelta(days=30)),p["subscription_id"]));c.commit();c.close();return {"status":"active"}

@app.get("/",response_class=HTMLResponse)
def home(): return PAGE

PAGE="""<!doctype html><html lang=ar dir=rtl><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>BidPilot</title><style>
body{font-family:system-ui;margin:0;background:#f5f7fb;color:#162235}.w{max-width:1050px;margin:auto;padding:20px}.hero,.card{background:#fff;border:1px solid #dfe6ef;border-radius:18px;padding:20px;margin:12px 0;box-shadow:0 5px 20px #1622350d}.hero{background:#10233b;color:#fff}input,textarea,select,button{width:100%;box-sizing:border-box;padding:11px;margin:5px 0;border:1px solid #ccd6e3;border-radius:9px}button{background:#1769ff;color:white;border:0;font-weight:700}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}.tag{display:inline-block;background:#edf3ff;padding:4px 8px;border-radius:7px;margin:3px}.req{padding:10px;border-right:4px solid #e5a72b;margin:7px 0;background:#fafbfd}</style><div class=w>
<div class=hero><h1>BidPilot</h1><p>منصة إدارة المناقصات وطلبات العروض للشركات الصغيرة: تحليل المتطلبات، متابعة الالتزام، بناء مسودة الإجابات وإعادة استخدام معرفة الشركة.</p></div>
<div id=auth class=card><div class=grid><div><h2>حساب جديد</h2><input id=n placeholder=الاسم><input id=e placeholder=البريد><input id=p type=password placeholder="كلمة المرور"><button onclick=signup()>إنشاء</button></div><div><h2>دخول</h2><input id=le placeholder=البريد><input id=lp type=password placeholder="كلمة المرور"><button onclick=login()>دخول</button></div></div></div>
<div id=app style=display:none><div class=card><h2>مناقصة جديدة</h2><input id=t placeholder="اسم المناقصة"><input id=b placeholder="الجهة"><input id=d placeholder="الموعد النهائي"><input id=v placeholder="القيمة"><input id=s placeholder="رابط المصدر"><textarea id=tx rows=7 placeholder="الصق نص المناقصة هنا لتحليل المتطلبات تلقائياً"></textarea><button onclick=add()>تحليل وحفظ</button></div><div id=list></div><div class=card><h2>اشتراك شهري</h2><select id=pl><option value=starter>Starter — 10,000 SDG</option><option value=pro>Pro — 25,000 SDG</option><option value=business>Business — 50,000 SDG</option></select><button onclick=sub()>طلب الاشتراك</button><div id=pay></div></div></div></div>
<script>let T=localStorage.bp;const $=i=>document.getElementById(i);async function api(u,o={}){o.headers={...(o.headers||{}),...(T?{Authorization:"Bearer "+T}:{})};let r=await fetch(u,o),x=await r.json();if(!r.ok)throw Error(x.detail);return x}function post(x){return{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(x)}}async function signup(){try{let x=await api("/api/signup",post({name:$("n").value,email:$("e").value,password:$("p").value}));T=x.token;localStorage.bp=T;show()}catch(e){alert(e.message)}}async function login(){try{let x=await api("/api/login",post({email:$("le").value,password:$("lp").value}));T=x.token;localStorage.bp=T;show()}catch(e){alert(e.message)}}async function show(){$("auth").style.display="none";$("app").style.display="block";load()}async function add(){try{await api("/api/tenders",post({title:$("t").value,buyer:$("b").value,deadline:$("d").value,value:$("v").value,source:$("s").value,text:$("tx").value}));load()}catch(e){alert(e.message)}}async function load(){let a=await api("/api/tenders");$("list").innerHTML=a.map(x=>'<div class=card><h2>'+x.title+'</h2><p>'+x.buyer+' — '+x.deadline+'</p><span class=tag>المتطلبات: '+(x.requirements||0)+'</span><span class=tag>المكتمل: '+(x.done||0)+'</span><button onclick="openT(\''+x.id+'\')">فتح وتحليل</button></div>').join("")||'<div class=card>أضف أول مناقصة.</div>'}async function openT(id){let x=await api("/api/tenders/"+id);let h='<div class=card><h2>'+x.tender.title+'</h2>';x.requirements.forEach(r=>h+='<div class=req><b>'+r.category+'</b> — '+r.text+'<br><button onclick="done(\''+r.id+'\',\''+id+'\')">'+(r.done?'إلغاء الإنجاز':'تم الإنجاز')+'</button></div>');h+='<button onclick="draft(\''+id+'\')">إنشاء مسودة إجابات من مكتبة المعرفة</button><div id=draft></div></div>';$("list").innerHTML=h}async function done(r,id){await api("/api/requirements/"+r+"/done",post({}));openT(id)}async function draft(id){let x=await api("/api/tenders/"+id+"/draft",post({}));$("draft").innerHTML='<h3>المسودة</h3>'+Object.values(x.answers).map(a=>'<div class=req>'+a+'</div>').join("")}async function sub(){try{let x=await api("/api/subscribe",post({plan:$("pl").value}));$("pay").innerHTML='<p>المبلغ: <b>'+x.amount+' SDG</b><br>اسم الحساب: '+x.account_name+'</p><input id=ref placeholder="مرجع التحويل"><button onclick="pay(\''+x.subscription_id+'\')">إرسال</button>'}catch(e){alert(e.message)}}async function pay(id){await api("/api/payment",post({subscription_id:id,reference:$("ref").value}));$("pay").innerHTML="تم تسجيل الدفع للمراجعة."}if(T)show();</script></html>"""
