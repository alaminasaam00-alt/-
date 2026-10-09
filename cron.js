const { Pool } = require('pg');
const pool = new Pool({ connectionString: process.env.DATABASE_URL, ssl: { rejectUnauthorized: false } });

async function main() {
  await pool.query("INSERT INTO audit_log(action, actor, metadata) VALUES ('scheduled_maintenance', 'system', '{\"ok\":true}')");
  console.log('maintenance complete');
  await pool.end();
}
main().catch(err => { console.error(err); process.exit(1); });
