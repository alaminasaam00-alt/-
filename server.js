const express = require('express');
const path = require('path');
const crypto = require('crypto');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');
const pinoHttp = require('pino-http');
const { Pool } = require('pg');

const app = express();
const PORT = Number(process.env.PORT || 3000);
const ADMIN_SECRET = process.env.ADMIN_SECRET || '';
const COMMISSION_RATE = Math.min(0.5, Math.max(0, Number(process.env.COMMISSION_RATE || 0.05)));
const pool = process.env.DATABASE_URL ? new Pool({ connectionString: process.env.DATABASE_URL, ssl: process.env.DATABASE_SSL === 'false' ? false : { rejectUnauthorized: false }, max: 10, idleTimeoutMillis: 30000 }) : null;

app.disable('x-powered-by');
app.set('trust proxy', 1);
app.use(helmet({ contentSecurityPolicy: false }));
app.use(pinoHttp());
app.use(express.json({ limit: '128kb' }));
app.use(rateLimit({ windowMs: 60_000, limit: 180, standardHeaders: 'draft-8', legacyHeaders: false }));
app.use(express.static(path.join(__dirname, 'public'), { dotfiles: 'deny', maxAge: '1h' }));

const demoProducts = [
  { id: 'demo-1', name: 'هاتف ذكي اقتصادي', category: 'هواتف', price: 185000, currency: 'SDG', merchant: 'متجر تجريبي' },
  { id: 'demo-2', name: 'لابتوب عملي للدراسة والعمل', category: 'لابتوبات', price: 420000, currency: 'SDG', merchant: 'متجر تجريبي' },
  { id: 'demo-3', name: 'راوتر 4G', category: 'شبكات', price: 95000, currency: 'SDG', merchant: 'متجر تجريبي' },
  { id: 'demo-4', name: 'SSD 1TB', category: 'تخزين', price: 165000, currency: 'SDG', merchant: 'متجر تجريبي' }
];

function admin(req, res, next) {
  if (!ADMIN_SECRET) return res.status(503).json({ error: 'admin_not_configured' });
  const supplied = String(req.get('x-admin-secret') || '');
  if (!supplied || supplied.length !== ADMIN_SECRET.length || !crypto.timingSafeEqual(Buffer.from(supplied), Buffer.from(ADMIN_SECRET))) return res.status(401).json({ error: 'unauthorized' });
  next();
}
function clean(v, max = 500) { return String(v ?? '').trim().slice(0, max); }

app.get('/api/health', async (req, res) => {
  let database = 'not-configured';
  if (pool) { try { await pool.query('SELECT 1'); database = 'ok'; } catch { database = 'error'; } }
  res.status(database === 'error' ? 503 : 200).json({ ok: database !== 'error', service: 'sudan-market-platform', database, version: '2.0.0', uptime: Math.round(process.uptime()) });
});

app.get('/api/config', async (req, res) => {
  let paymentInstructions = clean(process.env.PAYMENT_INSTRUCTIONS, 1000);
  if (!paymentInstructions && pool) { try { const r = await pool.query("SELECT value FROM app_settings WHERE key='payment_instructions'"); paymentInstructions = r.rows[0]?.value || ''; } catch {} }
  res.json({ currency: process.env.CURRENCY || 'SDG', commissionRate: COMMISSION_RATE, paymentInstructions: paymentInstructions || 'اختر تحويل بنكي عند إتمام الطلب. ستظهر تعليمات الدفع بعد إنشاء الطلب.' });
});

app.get('/api/products', async (req, res, next) => {
  try {
    const q = clean(req.query.q, 100), category = clean(req.query.category, 100);
    if (pool) {
      const { rows } = await pool.query(`SELECT id,name,category,description,price,currency,merchant_id, outbound_url AS url FROM products WHERE active=true AND ($1='' OR name ILIKE '%'||$1||'%' OR category ILIKE '%'||$1||'%') AND ($2='' OR category=$2) ORDER BY created_at DESC LIMIT 100`, [q, category]);
      return res.json({ count: rows.length, results: rows });
    }
    const needle = q.toLowerCase();
    const results = demoProducts.filter(p => (!needle || `${p.name} ${p.category}`.toLowerCase().includes(needle)) && (!category || p.category === category));
    res.json({ count: results.length, results });
  } catch (e) { next(e); }
});

app.get('/api/categories', async (req, res, next) => {
  try {
    if (!pool) return res.json({ results: [...new Set(demoProducts.map(p => p.category))] });
    const { rows } = await pool.query('SELECT DISTINCT category FROM products WHERE active=true ORDER BY category');
    res.json({ results: rows.map(r => r.category) });
  } catch (e) { next(e); }
});

app.post('/api/orders', async (req, res, next) => {
  try {
    if (!pool) return res.status(503).json({ error: 'database_required' });
    const customerName = clean(req.body.customerName, 120), customerPhone = clean(req.body.customerPhone, 40), items = Array.isArray(req.body.items) ? req.body.items.slice(0, 30) : [];
    if (!customerName || !customerPhone || !items.length) return res.status(400).json({ error: 'invalid_order' });
    const ids = items.map(i => clean(i.productId, 80)).filter(Boolean);
    const { rows: products } = await pool.query('SELECT id,name,price,currency,merchant_id FROM products WHERE active=true AND id = ANY($1::uuid[])', [ids]);
    const byId = new Map(products.map(p => [String(p.id), p]));
    let total = 0; const normalized = [];
    for (const item of items) {
      const p = byId.get(String(item.productId)); const quantity = Math.max(1, Math.min(99, Number(item.quantity || 1)));
      if (!p || !Number.isFinite(quantity)) return res.status(400).json({ error: 'product_unavailable' });
      total += Number(p.price) * quantity; normalized.push({ p, quantity });
    }
    const client = await pool.connect();
    try {
      await client.query('BEGIN');
      const merchantId = normalized[0].p.merchant_id || null;
      const order = await client.query(`INSERT INTO orders (merchant_id,customer_name,customer_phone,total,currency,status) VALUES ($1,$2,$3,$4,$5,'awaiting_payment') RETURNING id,total,currency,status,created_at`, [merchantId, customerName, customerPhone, total, normalized[0].p.currency || 'SDG']);
      for (const x of normalized) await client.query('INSERT INTO order_items (order_id,product_id,quantity,unit_price) VALUES ($1,$2,$3,$4)', [order.rows[0].id, x.p.id, x.quantity, x.p.price]);
      await client.query('INSERT INTO audit_log(action,actor,metadata) VALUES ($1,$2,$3)', ['order_created', customerPhone, JSON.stringify({ orderId: order.rows[0].id, total })]);
      await client.query('COMMIT');
      res.status(201).json({ order: order.rows[0], paymentInstructions: clean(process.env.PAYMENT_INSTRUCTIONS, 1000) || 'سيتم إرسال تعليمات التحويل البنكي مع رقم الطلب.' });
    } catch (e) { await client.query('ROLLBACK'); throw e; } finally { client.release(); }
  } catch (e) { next(e); }
});

app.post('/api/orders/:id/payment', async (req, res, next) => {
  try {
    if (!pool) return res.status(503).json({ error: 'database_required' });
    const ref = clean(req.body.reference, 120);
    if (!ref) return res.status(400).json({ error: 'payment_reference_required' });
    const { rowCount } = await pool.query(`UPDATE orders SET payment_reference=$1,payment_status='submitted',status='awaiting_payment',updated_at=now() WHERE id=$2 AND status NOT IN ('completed','cancelled')`, [ref, req.params.id]);
    if (!rowCount) return res.status(404).json({ error: 'order_not_found' });
    await pool.query('INSERT INTO audit_log(action,actor,metadata) VALUES ($1,$2,$3)', ['payment_submitted', 'customer', JSON.stringify({ orderId: req.params.id })]);
    res.json({ ok: true, status: 'submitted' });
  } catch (e) { next(e); }
});

app.get('/api/admin/orders', admin, async (req, res, next) => {
  try { const { rows } = await pool.query(`SELECT o.id,o.customer_name,o.customer_phone,o.total,o.currency,o.status,o.payment_reference,o.payment_status,o.created_at,COALESCE(SUM(oe.amount) FILTER (WHERE oe.kind='commission'),0) commission FROM orders o LEFT JOIN ledger_entries oe ON oe.order_id=o.id GROUP BY o.id ORDER BY o.created_at DESC LIMIT 200`); res.json({ results: rows }); } catch (e) { next(e); }
});

app.post('/api/admin/orders/:id/verify', admin, async (req, res, next) => {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    const r = await client.query("UPDATE orders SET payment_status='verified',status='paid',updated_at=now() WHERE id=$1 RETURNING id,total,currency,merchant_id", [req.params.id]);
    if (!r.rowCount) { await client.query('ROLLBACK'); return res.status(404).json({ error: 'order_not_found' }); }
    const o = r.rows[0];
    const commission = Number(o.total) * COMMISSION_RATE;
    await client.query("INSERT INTO ledger_entries(order_id,merchant_id,kind,amount,currency) VALUES ($1,$2,'commission',$3,$4)", [o.id, o.merchant_id, commission, o.currency]);
    await client.query('INSERT INTO audit_log(action,actor,metadata) VALUES ($1,$2,$3)', ['payment_verified', 'admin', JSON.stringify({ orderId: o.id, commission })]);
    await client.query('COMMIT'); res.json({ ok: true, commission });
  } catch (e) { await client.query('ROLLBACK'); next(e); } finally { client.release(); }
});

app.post('/api/admin/products', admin, async (req, res, next) => {
  try {
    const name=clean(req.body.name,160), category=clean(req.body.category,100), description=clean(req.body.description,1000), price=Number(req.body.price), currency=clean(req.body.currency || 'SDG',3).toUpperCase(), url=clean(req.body.url,1000);
    if (!name || !category || !Number.isFinite(price) || price < 0 || currency.length !== 3) return res.status(400).json({ error: 'invalid_product' });
    const { rows } = await pool.query('INSERT INTO products(name,category,description,price,currency,outbound_url) VALUES($1,$2,$3,$4,$5,$6) RETURNING *',[name,category,description,price,currency,url||null]);
    res.status(201).json({ product: rows[0] });
  } catch (e) { next(e); }
});

app.use((err, req, res, next) => { req.log.error({ err }, 'request failed'); res.status(500).json({ error: 'internal_error' }); });
app.get('*', (req, res) => res.sendFile(path.join(__dirname, 'public', 'index.html')));
app.listen(PORT, '0.0.0.0', () => console.log(`Sudan Market Platform listening on ${PORT}`));
