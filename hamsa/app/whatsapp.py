import json
import os
import urllib.request


def send_text(to, text):
    token = os.getenv("WHATSAPP_TOKEN")
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    if not token or not phone_id:
        return {"sent": False, "reason": "missing WHATSAPP_TOKEN or WHATSAPP_PHONE_NUMBER_ID"}
    url = f"https://graph.facebook.com/v23.0/{phone_id}/messages"
    payload = json.dumps({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }).encode()
    req = urllib.request.Request(
        url,
        payload,
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return {"sent": True, "response": json.loads(response.read())}
