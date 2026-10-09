import hashlib
import hmac
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from .matching import normalize
from .store import Store
from .whatsapp import send_text

app = FastAPI(title="Hamsa", version="1.1.0")
DB_PATH = os.getenv("HAMSA_DB_PATH", "hamsa.db")
store = Store(DB_PATH)

class Message(BaseModel):
    wa_id: str = Field(min_length=1)
    text: str = Field(min_length=1)

@app.get("/")
def root():
    return {"service": "hamsa", "status": "online", "webhook": "/webhook", "health": "/health"}

@app.get("/health")
def health():
    return {"ok": True, "service": "hamsa", "whatsapp_configured": bool(os.getenv("WHATSAPP_TOKEN") and os.getenv("WHATSAPP_PHONE_NUMBER_ID"))}

@app.get("/webhook")
def verify_webhook(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    expected = os.getenv("WHATSAPP_VERIFY_TOKEN") or store.get_setting("verify_token", "")
    if hub_mode == "subscribe" and expected and hmac.compare_digest(hub_verify_token or "", expected):
        return Response(content=hub_challenge or "", media_type="text/plain")
    raise HTTPException(status_code=403, detail="Webhook verification failed")

@app.post("/webhook")
async def receive_webhook(request: Request):
    raw = await request.body()
    app_secret = os.getenv("META_APP_SECRET")
    if app_secret:
        signature = request.headers.get("x-hub-signature-256", "")
        expected = "sha256=" + hmac.new(app_secret.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(status_code=401, detail="Invalid Meta webhook signature")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    if isinstance(payload, dict) and "wa_id" in payload and "text" in payload:
        msg = Message.model_validate(payload)
        result = handle_message(msg.wa_id, msg.text, send_reply=False)
        return {"ok": True, "result": result}

    if payload.get("object") != "whatsapp_business_account":
        return {"ok": True, "ignored": True}

    processed = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if change.get("field") != "messages":
                continue
            for message in value.get("messages", []) or []:
                if message.get("type") != "text":
                    continue
                wa_id = message.get("from")
                body = (message.get("text") or {}).get("body", "").strip()
                if wa_id and body:
                    handle_message(wa_id, body, send_reply=True)
                    processed += 1
    return {"ok": True, "processed": processed}

def _format_result(result: Any) -> str:
    if isinstance(result, dict) and result.get("type") == "payment_info":
        return (f"💳 بيانات دفع همسة\nاسم المستفيد: {result['name']}\nالحساب: {result['account_masked']}\n"
                "بعد التحويل أرسل: /إيصال رقم_الإشعار | المبلغ | رقم_المطابقة\n"
                "⚠️ الإيصال يبقى قيد المراجعة حتى التحقق الفعلي من الدفع.")
    if isinstance(result, dict) and result.get("type") == "receipt":
        return f"🧾 تم استلام الإيصال رقم {result['id']} ووضعه قيد المراجعة."
    if isinstance(result, dict) and "help" in result:
        return "مرحباً بك في همسة 👋\nلإضافة إعلان أرسل:\n/بيع الموديل | السعر | المدينة | الحالة\n\nلطلب منتج أرسل:\n/طلب الموديل | الميزانية | المدينة\n\nأوامر أخرى: /العروض /الطلبات /مطابقات /الحالة"
    if isinstance(result, dict) and result.get("type") == "offer":
        matches = result.get("matches") or []
        return f"✅ تم تسجيل عرضك رقم {result['id']}." + (f"\nوجدنا مطابقات: {', '.join(matches)}" if matches else "\nسنبلغك عند العثور على طلب مناسب.")
    if isinstance(result, dict) and result.get("type") == "request":
        matches = result.get("matches") or []
        return f"✅ تم تسجيل طلبك رقم {result['id']}." + (f"\nوجدنا عروضاً مطابقة: {', '.join(matches)}" if matches else "\nسنبلغك عند العثور على عرض مناسب.")
    if isinstance(result, dict) and "offers" in result and "requests" in result:
        return f"📊 حالة همسة\nالعروض: {result['offers']}\nالطلبات: {result['requests']}\nالمطابقات: {result['matches']}"
    if isinstance(result, list):
        if not result:
            return "لا توجد نتائج حتى الآن."
        return "\n".join(str(row) for row in result[:10])
    if isinstance(result, dict) and "closed" in result:
        return "✅ أُغلقت المطابقة." if result["closed"] else "لم أجد المطابقة المطلوبة."
    return str(result)

def handle_message(wa_id: str, text: str, send_reply: bool = True):
    t = normalize(text)
    try:
        if t in ("/الدفع", "/payment"):
            account = os.getenv("HAMSA_PAYMENT_ACCOUNT", "")
            masked = (("*" * max(0, len(account)-4)) + account[-4:]) if account else "غير مهيأ"
            result = {"type": "payment_info", "name": os.getenv("HAMSA_PAYMENT_NAME", "همسة"), "account_masked": masked}
        elif t in ("/الحالة", "/status"):
            result = store.stats()
        elif t in ("/العروض", "/offers"):
            result = store.latest("offers")
            if send_reply:
                result = [f"#{r[0]} | {r[2]} | {r[3]} | {r[4]} | {r[5]}" for r in result]
        elif t in ("/الطلبات", "/requests"):
            result = store.latest("requests")
            if send_reply:
                result = [f"#{r[0]} | {r[2]} | الميزانية {r[3]} | {r[4]}" for r in result]
        elif t in ("/مطابقات", "/matches"):
            result = store.latest("matches")
            if send_reply:
                result = [f"{r[0]} | الحالة: {r[3]}" for r in result]
        elif t.startswith("/إيصال ") or t.startswith("/receipt "):
            data = parse_receipt(text.split(maxsplit=1)[1])
            rid = store.add_receipt(wa_id, data)
            result = {"type": "receipt", "id": rid}
        elif t.startswith("/اغلاق ") or t.startswith("/close "):
            mid = text.split(maxsplit=1)[1].strip()
            result = store.close_match(mid)
        elif t.startswith("/بيع "):
            data = parse_listing(text[5:], request_mode=False)
            oid = store.add_offer(wa_id, data)
            matches = store.find_matches_for_offer(oid)
            result = {"type": "offer", "id": oid, "matches": matches}
            if matches:
                for mid in matches:
                    match = store.get_match_details(mid)
                    if match:
                        send_text(match["requester_wa_id"], f"🔔 وجدنا عرضاً مناسباً لطلبك: {match['model']} في {match['city']} بسعر {match['price']}. رقم المطابقة {mid}.")
        elif t.startswith("/طلب "):
            data = parse_listing(text[5:], request_mode=True)
            rid = store.add_request(wa_id, data)
            matches = store.find_matches_for_request(rid)
            result = {"type": "request", "id": rid, "matches": matches}
            if matches:
                for mid in matches:
                    match = store.get_match_details(mid)
                    if match:
                        send_text(match["seller_wa_id"], f"🔔 وجدنا طلباً مناسباً لعرضك: {match['model']} في {match['city']} بميزانية {match['budget']}. رقم المطابقة {mid}.")
        else:
            result = {"help": ["/بيع الموديل | السعر | المدينة | الحالة", "/طلب الموديل | الميزانية | المدينة", "/العروض", "/الطلبات", "/مطابقات", "/الدفع", "/الحالة", "/اغلاق M1-1"]}
    except (ValueError, IndexError, KeyError) as exc:
        result = {"error": f"صيغة غير صحيحة: {exc}", "help": ["/بيع الموديل | السعر | المدينة | الحالة", "/طلب الموديل | الميزانية | المدينة"]}
    if send_reply:
        send_text(wa_id, _format_result(result))
    return result

def parse_receipt(s: str):
    parts = [x.strip() for x in s.split("|")]
    if len(parts) != 3 or not all(parts):
        raise ValueError("الاستخدام: /إيصال رقم_الإشعار | المبلغ | رقم_المطابقة")
    try:
        amount = float(parts[1].replace(",", ""))
    except ValueError as exc:
        raise ValueError("المبلغ يجب أن يكون رقماً") from exc
    if amount <= 0:
        raise ValueError("المبلغ يجب أن يكون أكبر من صفر")
    return {"reference": parts[0], "amount": amount, "match_id": parts[2]}

def parse_listing(s: str, request_mode: bool = False):
    parts = [x.strip() for x in s.split("|")]
    minimum = 3
    if len(parts) < minimum or not parts[0] or not parts[2]:
        expected = "model | budget | city" if request_mode else "model | price | city | condition"
        raise ValueError(f"الاستخدام: {expected}")
    try:
        amount = float(parts[1].replace(",", ""))
    except ValueError as exc:
        raise ValueError("السعر/الميزانية يجب أن يكون رقماً") from exc
    if amount <= 0:
        raise ValueError("السعر/الميزانية يجب أن يكون أكبر من صفر")
    data = {"model": parts[0], "price": amount, "city": parts[2]}
    if len(parts) > 3:
        data["condition"] = parts[3]
    return data
