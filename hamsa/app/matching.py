import re
from difflib import SequenceMatcher

def normalize(s):
    s=str(s or "").strip().lower()
    return re.sub(r"\s+"," ",s)

def similar(a,b):
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()

def match_offer(o,r):
    # offers: id, wa_id, model, price, city, condition, created
    # requests: id, wa_id, model, budget, city, condition, created
    if normalize(o[4]) != normalize(r[4]): return False
    if similar(o[2],r[2]) < .72: return False
    if o[3] > r[3] * 1.10: return False
    return True
