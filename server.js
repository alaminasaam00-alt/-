import http from 'node:http';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const dataDir = path.join(root, 'data');
const dbFile = path.join(dataDir, 'store.json');
fs.mkdirSync(dataDir, { recursive: true });
const state = fs.existsSync(dbFile)
  ? JSON.parse(fs.readFileSync(dbFile, 'utf8'))
  : { leads: [], runs: [], events: [] };

for (const key of ['leads', 'runs', 'events']) if (!Array.isArray(state[key])) state[key] = [];
const id = () => crypto.randomUUID();
const save = () => fs.writeFileSync(dbFile, JSON.stringify(state, null, 2));
const clean = (v, max = 5000) => String(v ?? '').trim().slice(0, max);
const json = (res, code, payload) => {
  res.writeHead(code, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
    'access-control-allow-origin': '*'
  });
  res.end(JSON.stringify(payload));
};
const html = fs.readFileSync(path.join(root, 'public/index.html'), 'utf8');

const rate = new Map();
function allowed(req) {
  const ip = req.socket.remoteAddress || 'unknown';
  const now = Date.now();
  const item = rate.get(ip) || { at: now, count: 0 };
  if (now - item.at > 60_000) { item.at = now; item.count = 0; }
  item.count += 1;
  rate.set(ip, item);
  return item.count <= 60;
}

async function body(req) {
  let s = '';
  for await (const chunk of req) {
    s += chunk;
    if (s.length > 100_000) throw new Error('payload too large');
  }
  return s ? JSON.parse(s) : {};
}

function scoreLead(lead) {
  const text = `${lead.name} ${lead.company} ${lead.need}`.toLowerCase();
  const hot = /urgent|today|asap|price|quote|ready|buy|شراء|سعر|عاجل|اليوم|محتاج|أريد|عايز/.test(text);
  const budget = /\$|usd|دولار|ميزانية|budget|عرض سعر/.test(text);
  const contact = Boolean(lead.phone || lead.email);
  const score = Math.min(99, 35 + (hot ? 32 : 0) + (budget ? 18 : 0) + (contact ? 10 : 0) + (lead.company ? 4 : 0));
  const priority = score >= 75 ? 'high' : score >= 55 ? 'medium' : 'normal';
  const next = priority === 'high'
    ? 'اتصل بالعميل خلال 15 دقيقة'
    : priority === 'medium'
      ? 'أرسل عرضاً أولياً خلال ساعة'
      : 'أرسل رسالة تأهيل واسأل عن الموعد والميزانية';
  const reply = `مرحباً ${lead.name}، شكراً لتواصلك. فهمت أنك مهتم بـ ${lead.need || 'الخدمة'}. يمكننا مساعدتك، وسأرتب معك الخطوة التالية الآن. هل يناسبك أن نكمل التفاصيل اليوم؟`;
  const reason = hot ? 'نية شراء أو طلب عاجل' : budget ? 'إشارة تجارية واضحة' : contact ? 'بيانات تواصل متاحة وتحتاج إلى تأهيل' : 'يحتاج إلى تأهيل إضافي';
  return { score, priority, next, reply, reason };
}

function recordEvent(type, data = {}) {
  state.events.push({ id: id(), type, at: new Date().toISOString(), ...data });
  if (state.events.length > 2000) state.events.splice(0, state.events.length - 2000);
}

const server = http.createServer(async (req, res) => {
  try {
    if (!allowed(req)) return json(res, 429, { error: 'rate limit exceeded' });
    const u = new URL(req.url, `http://${req.headers.host || 'localhost'}`);

    if (req.method === 'OPTIONS') {
      res.writeHead(204, { 'access-control-allow-origin': '*', 'access-control-allow-methods': 'GET,POST,OPTIONS', 'access-control-allow-headers': 'content-type' });
      return res.end();
    }
    if (req.method === 'GET' && u.pathname === '/api/health') {
      return json(res, 200, { ok: true, service: 'RevenueFlow', mode: 'live-demo', time: new Date().toISOString() });
    }
    if (req.method === 'GET' && u.pathname === '/api/dashboard') {
      const runs = state.runs;
      const leads = state.leads;
      const avg = runs.length ? Math.round(runs.reduce((a, x) => a + x.score, 0) / runs.length) : 0;
      return json(res, 200, {
        leads: leads.length,
        processed: runs.length,
        hot: runs.filter(x => x.priority === 'high').length,
        conversionSignal: avg,
        today: runs.filter(x => x.createdAt.slice(0, 10) === new Date().toISOString().slice(0, 10)).length,
        recent: runs.slice(-20).reverse()
      });
    }
    if (req.method === 'GET' && u.pathname === '/api/leads') {
      return json(res, 200, { leads: state.leads.slice(-100).reverse() });
    }
    if (req.method === 'GET' && u.pathname === '/api/runs') {
      return json(res, 200, { runs: state.runs.slice(-100).reverse() });
    }
    if (req.method === 'POST' && u.pathname === '/api/leads') {
      const b = await body(req);
      const name = clean(b.name, 120);
      const need = clean(b.need, 3000);
      if (!name || !need) return json(res, 400, { error: 'name and need are required' });
      const lead = {
        id: id(), name, company: clean(b.company, 160), phone: clean(b.phone, 80),
        email: clean(b.email, 160), need, source: clean(b.source, 80) || 'manual',
        createdAt: new Date().toISOString()
      };
      state.leads.push(lead);
      recordEvent('lead_created', { leadId: lead.id, source: lead.source });
      save();
      return json(res, 201, { lead });
    }
    if (req.method === 'POST' && u.pathname.startsWith('/api/leads/') && u.pathname.endsWith('/run')) {
      const leadId = u.pathname.split('/')[3];
      const lead = state.leads.find(x => x.id === leadId);
      if (!lead) return json(res, 404, { error: 'lead not found' });
      const result = scoreLead(lead);
      const run = { id: id(), leadId, leadName: lead.name, ...result, createdAt: new Date().toISOString() };
      state.runs.push(run);
      recordEvent('lead_processed', { leadId, priority: result.priority, score: result.score });
      save();
      return json(res, 200, { run });
    }
    if (req.method === 'GET') {
      res.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-cache' });
      return res.end(html);
    }
    return json(res, 404, { error: 'not found' });
  } catch (e) {
    return json(res, e.message === 'payload too large' ? 413 : 500, { error: e.message === 'payload too large' ? e.message : 'internal error' });
  }
});

const port = Number(process.env.PORT || 3000);
server.listen(port, () => console.log(`RevenueFlow listening on ${port}`));