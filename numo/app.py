import os,sqlite3,secrets,json
from datetime import datetime,timezone,timedelta
from fastapi import FastAPI,HTTPException,Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
DB=os.getenv("SQLITE_PATH","./fatoraty.db"); ADMIN=os.getenv("RADAR_ADMIN_TOKEN",""); BOK=os.getenv("BOK_ACCOUNT_NUMBER",""); NAME=os.getenv("BOK_ACCOUNT_NAME","الأمين عثمان الدين الأمين محمد")
app=FastAPI(title="فاتورتي",version="1.0.0")
def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def uid(p): return p+"_"+secrets.token_hex(6)
c=db(); c.executescript("""CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE,name TEXT,created TEXT);
CREATE TABLE IF NOT EXISTS businesses(id TEXT PRIMARY KEY,user_id TEXT,name TEXT,phone TEXT,address TEXT);
CREATE TABLE IF NOT EXISTS customers(id TEXT PRIMARY KEY,business_id TEXT,name TEXT,phone TEXT);
CREATE TABLE IF NOT EXISTS invoices(id TEXT PRIMARY KEY,business_id TEXT,number TEXT,items TEXT,total INTEGER,created TEXT);
CREATE TABLE IF NOT EXISTS subscriptions(id TEXT PRIMARY KEY,user_id TEXT,plan TEXT,status TEXT,amount INTEGER,renew TEXT);
CREATE TABLE IF NOT EXISTS payments(id TEXT PRIMARY KEY,subscription_id TEXT,reference TEXT,amount INTEGER,status TEXT,created TEXT);"""); c.commit(); c.close()
class Signup(BaseModel): name:str; email:str
class Business(BaseModel): user_id:str; name:str; phone:str=""; address:str=""
class Customer(BaseModel): user_id:str; name:str; phone:str=""
class Invoice(BaseModel): user_id:str; items:list[dict]
class Subscribe(BaseModel): user_id:str; plan:str
class Payment(BaseModel): subscription_id:str; reference:str
def business(c,u):
 b=c.execute("SELECT * FROM businesses WHERE user_id=?",(u,)).fetchone()
 if not b: raise HTTPException(400,"أنشئ النشاط أولاً")
 return b
@app.get("/health")
def health(): return {"status":"ok","service":"fatoraty"}
@app.post("/api/signup")
def signup(x:Signup):
 c=db(); u=c.execute("SELECT id FROM users WHERE email=?",(x.email.lower(),)).fetchone()
 if u: c.close(); return {"user_id":u["id"]}
 i=uid("usr"); c.execute("INSERT INTO users VALUES(?,?,?,?)",(i,x.email.lower(),x.name,datetime.now(timezone.utc).isoformat())); c.commit(); c.close(); return {"user_id":i}
@app.post("/api/business")
def save(x:Business):
 c=db(); old=c.execute("SELECT id FROM businesses WHERE user_id=?",(x.user_id,)).fetchone(); i=old["id"] if old else uid("biz")
 if old: c.execute("UPDATE businesses SET name=?,phone=?,address=? WHERE id=?",(x.name,x.phone,x.address,i))
 else: c.execute("INSERT INTO businesses VALUES(?,?,?,?,?)",(i,x.user_id,x.name,x.phone,x.address))
 c.commit(); c.close(); return {"business_id":i}
@app.post("/api/customers")
def customer(x:Customer):
 c=db(); b=business(c,x.user_id); i=uid("cus"); c.execute("INSERT INTO customers VALUES(?,?,?,?)",(i,b["id"],x.name,x.phone)); c.commit(); c.close(); return {"customer_id":i}
@app.post("/api/invoices")
def invoice(x:Invoice):
 c=db(); b=business(c,x.user_id); total=sum(int(z.get("qty",1))*int(z.get("price",0)) for z in x.items); i=uid("inv"); n="INV-"+datetime.now().strftime("%Y%m%d")+"-"+secrets.token_hex(3).upper()
 c.execute("INSERT INTO invoices VALUES(?,?,?,?,?,?)",(i,b["id"],n,json.dumps(x.items,ensure_ascii=False),total,datetime.now(timezone.utc).isoformat())); c.commit(); c.close(); return {"invoice_id":i,"number":n,"total":total}
@app.get("/invoice/{i}",response_class=HTMLResponse)
def show(i):
 c=db(); r=c.execute("SELECT i.*,b.name bn,b.phone bp FROM invoices i JOIN businesses b ON b.id=i.business_id WHERE i.id=?",(i,)).fetchone(); c.close()
 if not r: raise HTTPException(404,"غير موجود")
 rows="".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"%(z.get("name","خدمة"),z.get("qty",1),z.get("price",0),int(z.get("qty",1))*int(z.get("price",0))) for z in json.loads(r["items"]))
 return "<html lang=ar dir=rtl><meta charset=utf-8><style>body{font-family:Arial;max-width:760px;margin:30px auto}table{width:100%%}td,th{padding:10px;border-bottom:1px solid #ddd}</style><button onclick=print()>طباعة/PDF</button><h1>%s</h1><p>%s</p><h2>فاتورة %s</h2><table><tr><th>الوصف</th><th>الكمية</th><th>السعر</th><th>الإجمالي</th></tr>%s</table><h2>%s SDG</h2></html>"%(r["bn"],r["bp"] or "",r["number"],rows,r["total"])
@app.post("/api/subscribe")
def subscribe(x:Subscribe):
 p={"starter":5000,"pro":15000,"business":30000}; amount=p.get(x.plan)
 if not amount: raise HTTPException(400,"خطة غير صحيحة")
 c=db(); i=uid("sub"); c.execute("INSERT INTO subscriptions VALUES(?,?,?,?,?,?)",(i,x.user_id,x.plan,"pending",amount,(datetime.now(timezone.utc)+timedelta(days=30)).isoformat())); c.commit(); c.close()
 return {"subscription_id":i,"amount":amount,"account_name":NAME,"account_number":BOK}
@app.post("/api/payment")
def payment(x:Payment):
 c=db(); s=c.execute("SELECT * FROM subscriptions WHERE id=?",(x.subscription_id,)).fetchone()
 if not s: c.close(); raise HTTPException(404,"الاشتراك غير موجود")
 i=uid("pay"); c.execute("INSERT INTO payments VALUES(?,?,?,?,?,?)",(i,x.subscription_id,x.reference,s["amount"],"pending",datetime.now(timezone.utc).isoformat())); c.commit(); c.close(); return {"payment_id":i,"status":"pending"}
@app.post("/api/admin/payments/{i}/approve")
def approve(i:str,authorization:str|None=Header(None)):
 if not ADMIN or authorization!="Bearer "+ADMIN: raise HTTPException(401,"غير مصرح")
 c=db(); p=c.execute("SELECT * FROM payments WHERE id=?",(i,)).fetchone()
 if not p: c.close(); raise HTTPException(404,"الدفع غير موجود")
 c.execute("UPDATE payments SET status='verified' WHERE id=?",(i,)); c.execute("UPDATE subscriptions SET status='active' WHERE id=?",(p["subscription_id"],)); c.commit(); c.close(); return {"status":"active"}
@app.get("/",response_class=HTMLResponse)
def home():
 return """<!doctype html><html lang=ar dir=rtl><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><style>body{font-family:system-ui;background:#f4f7fb;color:#152033}.w{max-width:950px;margin:auto;padding:22px}.hero,.card{background:white;border-radius:20px;padding:24px;margin:14px 0}.hero{background:#10243e;color:white}input,button,select{width:100%;padding:12px;margin:5px 0;box-sizing:border-box;border-radius:10px;border:1px solid #ccd5e1}button{background:#1769ff;color:white;border:0;font-weight:700}</style><div class=w><div class=hero><h1>فاتورتي</h1><p>فواتير ومبيعات وعملاء للتاجر السوداني.</p></div><div class=card><h2>إنشاء حساب</h2><input id=n placeholder="الاسم"><input id=e placeholder="البريد"><button onclick=start()>ابدأ</button></div><div id=a class=card style=display:none><h2>نشاطك</h2><input id=bn placeholder="اسم المتجر"><input id=ph placeholder="الهاتف"><input id=ad placeholder="العنوان"><button onclick=save()>حفظ النشاط</button><h3>عميل</h3><input id=cn placeholder="اسم العميل"><input id=cp placeholder="الهاتف"><button onclick=addc()>إضافة</button><h3>فاتورة</h3><input id=it placeholder="المنتج/الخدمة"><input id=pr type=number placeholder="السعر"><input id=qt type=number value=1><button onclick=inv()>إنشاء فاتورة</button><div id=o></div><h3>اشتراك شهري</h3><select id=pl><option value=starter>5,000 SDG</option><option value=pro>15,000 SDG</option><option value=business>30,000 SDG</option></select><button onclick=sub()>الدفع عبر بنك الخرطوم</button><div id=p></div></div></div><script>let u=localStorage.fu;async function api(x,o){let r=await fetch(x,o),d=await r.json();if(!r.ok)throw Error(d.detail);return d}async function start(){let d=await api("/api/signup",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({name:n.value,email:e.value})});u=d.user_id;localStorage.fu=u;a.style.display="block"}async function save(){await api("/api/business",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({user_id:u,name:bn.value,phone:ph.value,address:ad.value}))}async function addc(){await api("/api/customers",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({user_id:u,name:cn.value,phone:cp.value}));cn.value=""}async function inv(){let d=await api("/api/invoices",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({user_id:u,items:[{name:it.value,qty:+qt.value||1,price:+pr.value||0}]})});o.innerHTML="<a target=_blank href=/invoice/"+d.invoice_id+">فتح الفاتورة "+d.number+"</a> — "+d.total+" SDG"}async function sub(){let d=await api("/api/subscribe",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({user_id:u,plan:pl.value})});p.innerHTML="<b>بنك الخرطوم</b><br>المبلغ: "+d.amount+" SDG<br>اسم الحساب: "+d.account_name+"<br><input id=r placeholder=مرجع التحويل><button onclick='pay(""+d.subscription_id+"")'>إرسال</button>"}async function pay(i){await api("/api/payment",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({subscription_id:i,reference:r.value})});p.innerHTML="تم تسجيل الدفع للمراجعة."}if(u)a.style.display="block";</script></html>"""
if __name__=="__main__":
 import uvicorn; uvicorn.run(app,host="0.0.0.0",port=int(os.getenv("PORT","10000")))
