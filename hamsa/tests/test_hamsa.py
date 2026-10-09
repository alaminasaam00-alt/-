from app.store import Store
from app.main import parse_listing


def test_full_flow(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    oid = s.add_offer("seller", parse_listing("iPhone 13 | 280 | الخرطوم | جيد"))
    rid = s.add_request("buyer", parse_listing("iPhone 13 | 300 | الخرطوم"))
    assert s.find_matches_for_offer(oid) == [f"M{oid}-{rid}"]
    assert s.stats()["matches"] == 1
    assert s.close_match(f"M{oid}-{rid}")["closed"] is True


def test_no_bad_price_match(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    oid = s.add_offer("seller", parse_listing("iPhone 13 | 350 | الخرطوم"))
    rid = s.add_request("buyer", parse_listing("iPhone 13 | 300 | الخرطوم"))
    assert s.find_matches_for_offer(oid) == []
