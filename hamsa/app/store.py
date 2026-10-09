import sqlite3
from datetime import datetime

from .matching import match_offer

class Store:
    def __init__(self, path):
        self.db = path
        with self.conn() as c:
            c.execute("""create table if not exists offers(
                id integer primary key, wa_id text, model text, price real, city text,
                condition text, created text)""")
            c.execute("""create table if not exists requests(
                id integer primary key, wa_id text, model text, budget real, city text,
                condition text, created text)""")
            c.execute("""create table if not exists matches(
                id text primary key, offer_id integer, request_id integer,
                status text, created text)""")
            c.execute("create table if not exists settings(key text primary key,value text)")
            c.execute("insert or ignore into settings values('verify_token','HAMSA_TEST_TOKEN')")
            c.execute("""create table if not exists receipts(
                id integer primary key, wa_id text, reference text, amount real, match_id text,
                status text, created text)""")

    def conn(self):
        return sqlite3.connect(self.db)

    def get_setting(self, k, d=None):
        with self.conn() as c:
            r = c.execute("select value from settings where key=?", (k,)).fetchone()
            return r[0] if r else d

    def add_offer(self, wa_id, d):
        with self.conn() as c:
            cur = c.execute("insert into offers values(null,?,?,?,?,?,?)",
                (wa_id, d["model"], d["price"], d["city"], d.get("condition", ""), datetime.utcnow().isoformat()))
            return cur.lastrowid

    def add_request(self, wa_id, d):
        with self.conn() as c:
            cur = c.execute("insert into requests values(null,?,?,?,?,?,?)",
                (wa_id, d["model"], d["price"], d["city"], d.get("condition", ""), datetime.utcnow().isoformat()))
            return cur.lastrowid

    def find_matches_for_offer(self, oid):
        with self.conn() as c:
            o = c.execute("select * from offers where id=?", (oid,)).fetchone()
            rs = c.execute("select * from requests").fetchall()
        out = []
        for r in rs:
            if match_offer(o, r):
                mid = f"M{o[0]}-{r[0]}"
                with self.conn() as c:
                    c.execute("insert or ignore into matches values(?,?,?,?,?)",
                              (mid, o[0], r[0], "new", datetime.utcnow().isoformat()))
                out.append(mid)
        return out

    def find_matches_for_request(self, rid):
        with self.conn() as c:
            r = c.execute("select * from requests where id=?", (rid,)).fetchone()
            os = c.execute("select * from offers").fetchall()
        out = []
        for o in os:
            if match_offer(o, r):
                mid = f"M{o[0]}-{r[0]}"
                with self.conn() as c:
                    c.execute("insert or ignore into matches values(?,?,?,?,?)",
                              (mid, o[0], r[0], "new", datetime.utcnow().isoformat()))
                out.append(mid)
        return out

    def add_receipt(self, wa_id, d):
        with self.conn() as c:
            cur = c.execute("insert into receipts values(null,?,?,?,?,?,?)",
                (wa_id, d["reference"], d["amount"], d["match_id"], "pending", datetime.utcnow().isoformat()))
            return cur.lastrowid

    def close_match(self, mid):
        with self.conn() as c:
            cur = c.execute("update matches set status='closed' where id=?", (mid,))
            return {"closed": cur.rowcount > 0, "id": mid}

    def stats(self):
        with self.conn() as c:
            return {k: c.execute(f"select count(*) from {k}").fetchone()[0]
                    for k in ("offers", "requests", "matches")}

    def latest(self, table):
        with self.conn() as c:
            return c.execute(f"select * from {table} order by rowid desc limit 10").fetchall()

    def get_match_details(self, mid):
        with self.conn() as c:
            row = c.execute("""select o.wa_id, r.wa_id, o.model, o.city, o.price, r.budget
                from matches m join offers o on o.id=m.offer_id
                join requests r on r.id=m.request_id where m.id=?""", (mid,)).fetchone()
            if not row:
                return None
            return {"seller_wa_id": row[0], "requester_wa_id": row[1], "model": row[2],
                    "city": row[3], "price": row[4], "budget": row[5]}
