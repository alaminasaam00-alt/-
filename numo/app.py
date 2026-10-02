import os, sqlite3, secrets
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

DB_FILE=os.getenv('SQLITE_PATH','./numo.db')
BOK_ACCOUNT=os.getenv('BOK_ACCOUNT_NUMBER','')
BOK_NAME=os.getenv('BOK_ACCOUNT_NAME','')
ADMIN_TOKEN=os.getenv('NUMO_ADMIN_TOKEN','')
app=FastAPI(title='NOVA — نمو AI',version='10.0.0')

def db():
    c=sqlite3.connect(DB_FILE); c.row_factory=sqlite3.Row; return c

def init():
    c=db(); c.executescript('''CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE,name TEXT,created_at TEXT); CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY,name TEXT,amount INTEGER,currency TEXT,interval TEXT); CREATE TABLE IF NOT EXISTS subscriptions(id TEXT PRIMARY KEY,user_id TEXT,plan_id TEXT,status TEXT,created_at TEXT,renew_at TEXT); CREATE TABLE IF NOT EXISTS payments(id TEXT PRIMARY KEY,user_id TEXT,subscription_id TEXT,amount INTEGER,currency TEXT,reference TEXT,status TEXT,created_at TEXT); CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,action TEXT,payload TEXT,created_at TEXT);''')
    if not c.execute('SELECT 1 FROM plans').fetchone():
        c.executemany('INSERT INTO plans VALUES(?,?,?,?,?)',[('basic','الأساسية',5000,'SDG','monthly'),('growth','النمو',15000,'SDG','monthly'),('pro','الاحتراف',30000,'SDG','monthly')])
    c.commit(); c.close()
init()
class Signup(BaseModel): email:str; name:str=Field(min_length=1,max_length=120)
class Subscribe(BaseModel): user_id:str; plan_id:str
class Payment(BaseModel): subscription_id:str; reference:str=Field(min_length=3,max_length=120); amount:int=Field(gt=0)

def audit(action,payload):
    c=db(); c.execute('INSERT INTO audit(action,payload,created_at) VALUES(?,?,?)',(action,str(payload),datetime.now(timezone.utc).isoformat())); c.commit(); c.close()

@app.get('/health')
def health(): return {'status':'ok','service':'numo-ai','version':'10.0.0'}
@app.get('/ready')
def ready(): return {'status':'ready','database':True,'payments':'bank-transfer-manual-verification'}
@app.get('/api/plans')
def plans():
    c=db(); rows=[dict(x) for x in c.execute('SELECT * FROM plans').fetchall()]; c.close(); return rows
@app.post('/api/signup')
def signup(x:Signup):
    c=db(); u=c.execute('SELECT * FROM users WHERE email=?',(x.email,)).fetchone()
    if u: return dict(u)
    uid='usr_'+secrets.token_hex(8); c.execute('INSERT INTO users VALUES(?,?,?,?)',(uid,x.email,x.name,datetime.now(timezone.utc).isoformat())); c.commit(); c.close(); audit('user.created',{'user_id':uid}); return {'id':uid,'email':x.email,'name':x.name}
@app.post('/api/subscribe')
def subscribe(x:Subscribe):
    c=db(); p=c.execute('SELECT * FROM plans WHERE id=?',(x.plan_id,)).fetchone(); u=c.execute('SELECT * FROM users WHERE id=?',(x.user_id,)).fetchone()
    if not p or not u: raise HTTPException(404,'User or plan not found')
    sid='sub_'+secrets.token_hex(8); now=datetime.now(timezone.utc); renew=now+timedelta(days=30)
    c.execute('INSERT INTO subscriptions VALUES(?,?,?,?,?,?)',(sid,x.user_id,x.plan_id,'pending_payment',now.isoformat(),renew.isoformat())); c.commit(); c.close(); audit('subscription.created',{'subscription_id':sid}); return {'subscription_id':sid,'status':'pending_payment','amount':p['amount'],'currency':p['currency'],'payment':{'method':'Bank of Khartoum transfer','account_name':BOK_NAME,'account_number':BOK_ACCOUNT,'reference_required':True}}
@app.post('/api/payment/submit')
def payment(x:Payment):
    c=db(); s=c.execute('SELECT * FROM subscriptions WHERE id=?',(x.subscription_id,)).fetchone()
    if not s: raise HTTPException(404,'Subscription not found')
    p=c.execute('SELECT * FROM plans WHERE id=?',(s['plan_id'],)).fetchone()
    if x.amount!=p['amount']: raise HTTPException(400,'Amount does not match the subscription plan')
    pid='pay_'+secrets.token_hex(8); c.execute('INSERT INTO payments VALUES(?,?,?,?,?,?,?,?)',(pid,s['user_id'],s['id'],x.amount,p['currency'],x.reference,'pending_review',datetime.now(timezone.utc).isoformat())); c.commit(); c.close(); audit('payment.submitted',{'payment_id':pid}); return {'payment_id':pid,'status':'pending_review','message':'تم استلام الطلب. لا يتم تفعيل الاشتراك قبل التحقق من التحويل.'}
@app.post('/api/admin/payments/{payment_id}/approve')
def approve(payment_id:str,authorization:str|None=Header(None)):
    if not ADMIN_TOKEN or authorization!=f'Bearer {ADMIN_TOKEN}': raise HTTPException(401,'Admin authentication required')
    c=db(); pay=c.execute('SELECT * FROM payments WHERE id=?',(payment_id,)).fetchone()
    if not pay: raise HTTPException(404,'Payment not found')
    c.execute('UPDATE payments SET status=? WHERE id=?',('verified',payment_id)); c.execute('UPDATE subscriptions SET status=? WHERE id=?',('active',pay['subscription_id'])); c.commit(); c.close(); audit('payment.verified',{'payment_id':payment_id}); return {'status':'active'}
@app.get('/api/status/{user_id}')
def status(user_id:str):
    c=db(); rows=[dict(x) for x in c.execute('SELECT * FROM subscriptions WHERE user_id=? ORDER BY created_at DESC',(user_id,)).fetchall()]; c.close(); return rows
@app.get('/',response_class=HTMLResponse)
def home():
    return '''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NOVA — نمو AI</title><style>body{font-family:system-ui;background:#07111f;color:#fff;max-width:900px;margin:auto;padding:40px}.card{background:#101d30;border:1px solid #243a55;border-radius:18px;padding:22px;margin:16px 0}button{padding:12px 18px;border:0;border-radius:10px;cursor:pointer}input{padding:12px;border-radius:10px;border:1px solid #345;background:#0b1727;color:#fff;margin:5px;width:90%}</style><h1>NOVA — نمو AI</h1><p>خدمة رقمية باشتراك شهري وتشغيل آلي.</p><div id="plans"></div><div class="card"><h2>ابدأ</h2><input id="name" placeholder="الاسم"><input id="email" placeholder="البريد الإلكتروني"><button onclick="go()">إنشاء الحساب</button><pre id="out"></pre></div><script>fetch('/api/plans').then(r=>r.json()).then(ps=>plans.innerHTML=ps.map(p=>`<div class="card"><h2>${p.name}</h2><b>${p.amount} ${p.currency} / شهر</b><p>تفعيل الخدمة بعد التحقق من التحويل البنكي.</p></div>`).join(''));async function go(){let r=await fetch('/api/signup',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({name:name.value,email:email.value})});out.textContent=JSON.stringify(await r.json(),null,2)}</script></html>'''
