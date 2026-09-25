const express = require('express');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 3000;

const products = [
  { id: 1, name: 'Lenovo ThinkPad E570', category: 'Laptops', price: 220, currency: 'USD', merchant: 'Demo Merchant A', url: '#', tags: ['laptop', 'security', 'student'] },
  { id: 2, name: 'USB Wi-Fi Adapter', category: 'Cybersecurity', price: 18, currency: 'USD', merchant: 'Demo Merchant B', url: '#', tags: ['wifi', 'adapter', 'security'] },
  { id: 3, name: 'Mechanical Keyboard', category: 'Accessories', price: 32, currency: 'USD', merchant: 'Demo Merchant C', url: '#', tags: ['keyboard', 'computer'] },
  { id: 4, name: 'Portable SSD 1TB', category: 'Storage', price: 68, currency: 'USD', merchant: 'Demo Merchant A', url: '#', tags: ['ssd', 'storage', 'backup'] }
];

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

app.get('/api/health', (req, res) => {
  res.json({ ok: true, service: 'dealradar-ai', environment: process.env.NODE_ENV || 'development' });
});

app.get('/api/products', (req, res) => {
  const q = String(req.query.q || '').trim().toLowerCase();
  const category = String(req.query.category || '').trim().toLowerCase();
  const results = products.filter((product) => {
    const haystack = [product.name, product.category, ...product.tags].join(' ').toLowerCase();
    const matchesQuery = !q || haystack.includes(q);
    const matchesCategory = !category || product.category.toLowerCase() === category;
    return matchesQuery && matchesCategory;
  });
  res.json({ count: results.length, results });
});

app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

app.listen(PORT, () => {
  console.log(`DealRadar AI running on port ${PORT}`);
});
