import http from 'node:http';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const dataDir = path.join(root, 'data');
const dbFile = path.join(dataDir, 'store.json');
fs.mkdirSync(dataDir, { recursive: true });
const state = fs.existsSync(dbFile) ? JSON.parse(fs.readFileSync(dbFile, 'utf8')) : { leads: [], runs: [], events: [] };
for (const key of ['leads', 'runs', 'events']) if (!Array.isArray(state[key])) state[key] = [];
for (const lead of state.leads) { lead.status ||= 'new'; lead.updatedAt ||= lead.createdAt; }
const id = () => crypto.randomUUID();
const save = () => fs.writeFileSync(dbFile, JSON.stringify(state, null, 2));
const clean = (v, max = 5000) => String(v ?? '').trim().slice(0, max);
const validStatuses = new Set(['new', 'contacted', 'qualified', 'won', 'lost']);
const json = (res, code, payload) => {
  res.writeHead(code, {'content-type':'application/json; charset=utf-8','cache-control':'no-store','access-control-allow-origin':'*','x-content-type-options':'nosniff','x-frame-options':'DENY','referrer-policy':'no-referrer'});
  res.end(JSON.stringify(payload));
};
const html = fs.readFileSync(path.join(root, 'public/app.html'), 'utf8');
const rate = new Map();
function allowed(req) { const ip=req.socket.remoteAddress||'unknown', now=Date.now(); const item=rate.get(ip)||{at:now,count:0}; if(now-item.at>60000){item.at=now;item.count=0;} item.count++; rate.set(ip,item); return item.count<=120; }
async function body(req){let s='';for await(const chunk of req){s+=chunk;if(s.length>100000)throw new Error('payload too large')}return s?JSON.parse(s):{}}
function scoreLead(lead){
  const text=`${lead.name} ${lead.company} ${lead.need}`.toLowerCase();
  const hot=/urgent|today|asap|price|quote|ready|buy|شراء|سعر|عاجل|اليوم|محتاج|أريد|عايز/.test(text);
  const budget=/\$|usd|دولار|ميزانية|budget|عرض سعر/.test(text);
  const contact=Boolean(lead.phone||lead.email);
  const score=Math.min(99,35+(hot?32:0)+(budget?18:0)+(contact?10:0)+(lead.company?4:0));
  const priority=score>=75?'high':score>=55?'medium':'normal';
  const next=priority==='high'?'اتصل بالعميل خلال 15 دقيقة':priority==='medium'?'أرسل عرضاً أولياً خلال ساعة':'أرسل رسالة تأهيل واسأل عن الموعد والميزانية';
  const reply=`مرحباً ${lead.name}، شكراً لتواصلك. فهمت أنك مهتم بـ ${lead.need||'الخدمة'}. يمكننا مساعدتك، وسأرتب معك الخطوة التالية الآن. هل يناسبك أن نكمل التفاصيل اليوم؟`;
  const reason=hot?'نية شراء أو طلب عاجل':budget?'إشارة تجارية واضحة':contact?'بيانات تواصل متاحة وتحتاج إلى تأهيل':'يحتاج إلى تأهيل إضافي';
  return {score,priority,next,reply,reason};
}
function recordEvent(type,data={}){state.events.push({id:id(),type,at:new Date().toISOString(),...data});if(state.events.length>5000)state.events.splice(0,state.events.length-5000)}
function buildLead(b, source='manual') { return {id:id(),name:clean(b.name,120),company:clean(b.company,160),phone:clean(b.phone,80),email:clean(b.email,160),need:clean(b.need,3000),source:clean(b.source,80)||source,status:validStatuses.has(b.status)?b.status:'new',createdAt:new Date().toISOString(),updatedAt:new Date().toISOString()}; }
function authApi(req) { const expected=process.env.REVENUEFLOW_API_KEY; if(!expected)return true; return req.headers.authorization===`Bearer ${expected}` || req.headers['x-api-key']===expected; }
function dashboard(){
  const runs=state.runs, leads=state.leads, avg=runs.length?Math.round(runs.reduce((a,x)=>a+x.score,0)/runs.length):0;
  const statusCounts=Object.fromEntries([...validStatuses].map(s=>[s,leads.filter(x=>x.status===s).length]));
  const sourceCounts={}; for(const l of leads) sourceCounts[l.source||'manual']=(sourceCounts[l.source||'manual']||0)+1;
  const won=statusCounts.won, closed=won+statusCounts.lost;
  return {leads:leads.length,processed:runs.length,hot:runs.filter(x=>x.priority==='high').length,intentSignal:avg,today:runs.filter(x=>x.createdAt.slice(0,10)===new Date().toISOString().slice(0,10)).length,statusCounts,sourceCounts,won,closed,winRate:closed?Math.round(won/closed*100):0,recent:runs.slice(-20).reverse()};
}
const server=http.createServer(async(req,res)=>{try{
  if(!allowed(req))return json(res,429,{error:'rate limit exceeded'});
  const u=new URL(req.url,`http://${req.headers.host||'localhost'}`);
  if(req.method==='OPTIONS'){res.writeHead(204,{'access-control-allow-origin':'*','access-control-allow-methods':'GET,POST,PATCH,OPTIONS','access-control-allow-headers':'content-type,authorization,x-api-key,idempotency-key'});return res.end()}
  if(req.method==='GET'&&u.pathname==='/api/health')return json(res,200,{ok:true,service:'RevenueFlow',mode:'live',time:new Date().toISOString(),version:'1.4.0'});
  if(req.method==='GET'&&u.pathname==='/api/dashboard')return json(res,200,dashboard());
  if(req.method==='GET'&&u.pathname==='/api/leads'){
    const q=clean(u.searchParams.get('q'),120).toLowerCase(), status=u.searchParams.get('status');
    const limit=Math.max(1,Math.min(200,Number(u.searchParams.get('limit')||50))), offset=Math.max(0,Number(u.searchParams.get('offset')||0));
    let leads=state.leads.slice().reverse();
    if(q) leads=leads.filter(x=>`${x.name} ${x.company} ${x.phone} ${x.email} ${x.need}`.toLowerCase().includes(q));
    if(status&&validStatuses.has(status)) leads=leads.filter(x=>x.status===status);
    return json(res,200,{total:leads.length,leads:leads.slice(offset,offset+limit)});
  }
  if(req.method==='GET'&&u.pathname==='/api/runs'){
    const limit=Math.max(1,Math.min(200,Number(u.searchParams.get('limit')||50))), offset=Math.max(0,Number(u.searchParams.get('offset')||0));
    const runs=state.runs.slice().reverse(); return json(res,200,{total:runs.length,runs:runs.slice(offset,offset+limit)});
  }
  if(req.method==='GET'&&u.pathname==='/api/analytics'){
    const days=Math.max(1,Math.min(90,Number(u.searchParams.get('days')||30)));
    const cutoff=Date.now()-days*86400000;
    const recentLeads=state.leads.filter(x=>Date.parse(x.createdAt)>=cutoff);
    const recentRuns=state.runs.filter(x=>Date.parse(x.createdAt)>=cutoff);
    const byDay={}; for(let i=days-1;i>=0;i--){const d=new Date(Date.now()-i*86400000).toISOString().slice(0,10);byDay[d]=0;} for(const r of recentRuns){const d=r.createdAt.slice(0,10);if(d in byDay)byDay[d]++;}
    const bySource={}; for(const l of recentLeads){const k=l.source||'manual';bySource[k]=(bySource[k]||0)+1;}
    const byStatus=Object.fromEntries([...validStatuses].map(s=>[s,recentLeads.filter(x=>x.status===s).length]));
    return json(res,200,{days,leads:recentLeads.length,processed:recentRuns.length,byDay,bySource,byStatus});
  }
  if(req.method==='POST'&&u.pathname==='/api/demo-request'){
    const b=await body(req),lead=buildLead({...b,source:'website-demo'},'website-demo');
    if(!lead.name||!lead.need)return json(res,400,{error:'name and need are required'});
    if(lead.email&&!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(lead.email))return json(res,400,{error:'invalid email'});
    state.leads.push(lead);recordEvent('demo_request',{leadId:lead.id,source:lead.source});
    const result=scoreLead(lead),run={id:id(),leadId:lead.id,leadName:lead.name,status:lead.status,...result,createdAt:new Date().toISOString()};
    state.runs.push(run);recordEvent('lead_processed',{leadId:lead.id,priority:result.priority,score:result.score});save();
    return json(res,201,{ok:true,leadId:lead.id,priority:result.priority});
  }
  if(req.method==='POST'&&u.pathname==='/api/leads'){
    const b=await body(req),lead=buildLead(b,'manual');
    if(!lead.name||!lead.need)return json(res,400,{error:'name and need are required'});
    if(lead.email&&!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(lead.email))return json(res,400,{error:'invalid email'});
    state.leads.push(lead);recordEvent('lead_created',{leadId:lead.id,source:lead.source});save();return json(res,201,{lead});
  }
  if(req.method==='POST'&&u.pathname==='/api/ingest'){
    if(!authApi(req))return json(res,401,{error:'api key required'});
    const idem=clean(req.headers['idempotency-key'],160);
    if(idem){const prior=state.events.find(x=>x.type==='lead_ingested'&&x.idempotencyKey===idem);if(prior){const existing=state.leads.find(x=>x.id===prior.leadId);const priorRun=state.runs.find(x=>x.leadId===prior.leadId);if(existing)return json(res,200,{lead:existing,run:priorRun,replayed:true});}}
    const b=await body(req),lead=buildLead(b,b.source||'api');
    if(!lead.name||!lead.need)return json(res,400,{error:'name and need are required'});
    if(lead.email&&!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(lead.email))return json(res,400,{error:'invalid email'});
    state.leads.push(lead);recordEvent('lead_ingested',{leadId:lead.id,source:lead.source,idempotencyKey:idem||null});
    const result=scoreLead(lead),run={id:id(),leadId:lead.id,leadName:lead.name,status:lead.status,...result,createdAt:new Date().toISOString()};
    state.runs.push(run);recordEvent('lead_processed',{leadId:lead.id,priority:result.priority,score:result.score});save();
    return json(res,201,{lead,run});
  }
  if(req.method==='PATCH'&&u.pathname.startsWith('/api/leads/')){
    const parts=u.pathname.split('/'),leadId=parts[3];
    if(parts.length!==4)return json(res,404,{error:'not found'});
    const lead=state.leads.find(x=>x.id===leadId);if(!lead)return json(res,404,{error:'lead not found'});
    const b=await body(req);if(!validStatuses.has(b.status))return json(res,400,{error:'invalid status',allowed:[...validStatuses]});
    const previous=lead.status;lead.status=b.status;lead.updatedAt=new Date().toISOString();recordEvent('lead_status_changed',{leadId,from:previous,to:lead.status});save();return json(res,200,{lead});
  }
  if(req.method==='POST'&&u.pathname.startsWith('/api/leads/')&&u.pathname.endsWith('/run')){
    const leadId=u.pathname.split('/')[3],lead=state.leads.find(x=>x.id===leadId);if(!lead)return json(res,404,{error:'lead not found'});
    const result=scoreLead(lead),run={id:id(),leadId,leadName:lead.name,status:lead.status,...result,createdAt:new Date().toISOString()};state.runs.push(run);recordEvent('lead_processed',{leadId,priority:result.priority,score:result.score});save();return json(res,200,{run});
  }
  if(req.method==='GET'&&u.pathname==='/app'){res.writeHead(200,{'content-type':'text/html; charset=utf-8','cache-control':'no-cache'});return res.end(html)}
  if(req.method==='GET'&&u.pathname==='/'){res.writeHead(200,{'content-type':'text/html; charset=utf-8','cache-control':'no-cache'});return res.end(fs.readFileSync(path.join(root,'public/landing.html'),'utf8'))}
  return json(res,404,{error:'not found'});
}catch(e){return json(res,e instanceof SyntaxError?400:e.message==='payload too large'?413:500,{error:e instanceof SyntaxError?'invalid JSON':e.message==='payload too large'?'payload too large':'internal error'})}});
const port=Number(process.env.PORT||3000);server.listen(port,()=>console.log(`RevenueFlow listening on ${port}`));
