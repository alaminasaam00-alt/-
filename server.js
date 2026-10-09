const express = require('express');
const path = require('path');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');
const pinoHttp = require('pino-http');
const { Pool } = require('pg');

const app = express();
const PORT = Number(process.env.PORT || 3000);
const pool = process.env.DATABASE_URL ? new Pool({ connectionString: process.env.DATABASE_URL, ssl: process.env.DATABASE_SSL === 'false' ? false : { rejectUnauthorized: false }, max: 10 }) : null;

app.disable('x-powered-by');
app.set('trust proxy', 1);
app.use(helmet({ contentSecurityPolicy: false }));
app.use(pinoHttp());
app.use(express.json({ limit: '64kb' }));
app.use(rateLimit({ windowMs: 60_000, limit: 120, standardHeaders: 'draft-8', legacyHeaders: false }));
app.use(express.static(path.join(__dirname, 'public'), { dotfiles: 'deny', maxAge: '1h' }));

const demoProducts = [
  { id: 'demo-1', name: 'Lenovo ThinkPad E570', category: 'لابتوبات', price: 220, currency: 'USD', merchant: 'تاجر تجريبي' },
  { id: 'demo-2', name: 'USB Wi-Fi Adapter', category: 'شبكات', price: 18, currency: 'USD', merchant: 'تاجر تجريبي' },
  { id: 'demo-3', name: 'Mechanical Keyboard', category: 'ملحقات', price: 32, currency: 'USD', merchant: 'تاجر تجريبي' },
  { id: 'demo-4', name: 'Portable SSD 1TB', category: 'تخزين', price: 68, currency: 'USD', merchant: 'تاجر تجريبي' }
];

app.get('/api/health', async (req, res) => {
  let database = 'not-configured';
  if (pool) {
    try { await pool.query('SELECT 1'); database = 'ok'; } catch { database = 'error'; }
  }
  res.json({ ok: database !== 'error', service: 'sudan-market-platform', database, version: '1.0.0' });
});

app.get('/api/products', async (req, res) => {
  const q = String(req.query.q || '').trim();
  const category = String(req.query.category || '').trim();
  if (pool) {
    const { rows } = await pool.query(
      `SELECT id, name, category, price, currency, merchant_name AS merchant, outbound_url AS url
       FROM products WHERE active = true
       AND ($1 = '' OR name ILIKE '%' || $1 || '%' OR category ILIKE '%' || $1 || '%')
       AND ($2 = '' OR category = $2) ORDER BY created_at DESC LIMIT 100`, [q, category]
    );
    return res.json({ count: rows.length, results: rows });
  }
  const needle = q.toLowerCase();
  const results = demoProducts.filter(p => (!needle || `${p.name} ${p.category}`.toLowerCase().includes(needle)) && (!category || p.category === category));
  res.json({ count: results.length, results });
});

app.get('/api/categories', async (req, res) => {
  if (!pool) return res.json({ results: [...new Set(demoProducts.map(p => p.category))] });
  const { rows } = await pool.query('SELECT DISTINCT category FROM products WHERE active=true ORDER BY category');
  res.json({ results: rows.map(r => r.category) });
});

app.use((err, req, res, next) => {
  req.log.error({ err }, 'request failed');
  res.status(500).json({ error: 'internal_error' });
});

app.get('*', (req, res) => res.sendFile(path.join(__dirname, 'public', 'index.html')));

app.listen(PORT, '0.0.0.0', () => console.log(`Sudan Market Platform listening on ${PORT}`));
