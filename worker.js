const { Pool } = require('pg');
const pool = new Pool({ connectionString: process.env.DATABASE_URL, ssl: { rejectUnauthorized: false } });

async function run() {
  await pool.query('SELECT 1');
  console.log('worker ready');
  setInterval(async () => {
    try {
      await pool.query('SELECT 1');
      console.log('worker heartbeat');
    } catch (err) {
      console.error('worker database check failed', err.message);
    }
  }, 30000);
}
run().catch(err => { console.error(err); process.exit(1); });
