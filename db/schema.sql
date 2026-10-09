CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS merchants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL, phone text,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('pending','active','suspended')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS products (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), merchant_id uuid REFERENCES merchants(id) ON DELETE SET NULL,
  name text NOT NULL, category text NOT NULL, description text NOT NULL DEFAULT '',
  price numeric(14,2) NOT NULL CHECK (price >= 0), currency char(3) NOT NULL DEFAULT 'SDG',
  outbound_url text, active boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS products_active_category_idx ON products(active, category);
CREATE INDEX IF NOT EXISTS products_name_idx ON products USING gin(to_tsvector('simple', name));

CREATE TABLE IF NOT EXISTS orders (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), merchant_id uuid REFERENCES merchants(id) ON DELETE SET NULL,
  customer_name text NOT NULL, customer_phone text NOT NULL, total numeric(14,2) NOT NULL CHECK (total >= 0),
  currency char(3) NOT NULL DEFAULT 'SDG', status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','awaiting_payment','paid','processing','completed','cancelled')),
  payment_reference text, payment_status text NOT NULL DEFAULT 'unverified'
    CHECK (payment_status IN ('unverified','submitted','verified','rejected')),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_reference text;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_status text NOT NULL DEFAULT 'unverified';
ALTER TABLE orders ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

CREATE TABLE IF NOT EXISTS order_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), order_id uuid NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id uuid REFERENCES products(id) ON DELETE SET NULL, quantity integer NOT NULL CHECK (quantity > 0), unit_price numeric(14,2) NOT NULL CHECK (unit_price >= 0)
);

CREATE TABLE IF NOT EXISTS ledger_entries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), order_id uuid REFERENCES orders(id) ON DELETE SET NULL,
  merchant_id uuid REFERENCES merchants(id) ON DELETE SET NULL,
  kind text NOT NULL CHECK (kind IN ('commission','subscription','advertising','refund','payout')),
  amount numeric(14,2) NOT NULL, currency char(3) NOT NULL DEFAULT 'SDG', created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_log (
  id bigserial PRIMARY KEY, action text NOT NULL, actor text, metadata jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app_settings (
  key text PRIMARY KEY, value text NOT NULL DEFAULT '', updated_at timestamptz NOT NULL DEFAULT now()
);
