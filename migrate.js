const fs = require('fs');
const path = require('path');
const { Pool } = require('pg');

if (!process.env.DATABASE_URL) {
  console.log('DATABASE_URL not configured; skipping migration');
  process.exit(0);
}

const pool = new Pool({ connectionString: process.env.DATABASE_URL, ssl: process.env.DATABASE_SSL === 'false' ? false : { rejectUnauthorized: false } });
(async () => {
  const sql = fs.readFileSync(path.join(__dirname, 'db', 'schema.sql'), 'utf8');
  await pool.query(sql);
  console.log('database schema ready');
  await pool.end();
})().catch(async err => { console.error('migration failed', err); await pool.end(); process.exit(1); });
