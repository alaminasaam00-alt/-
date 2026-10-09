# همسة | Hamsa

Arabic-first brokerage matching service for Sudan.

## Current capabilities
- FastAPI webhook with Meta WhatsApp webhook payload parsing.
- Arabic text commands to register offers and purchase requests.
- SQLite matching by model, city, and price/budget.
- Submission of payment receipt references with pending-review status.
- Health endpoint for deployment checks.

## Safety and deployment
- Never commit bank login credentials, API tokens, or payment secrets.
- Add deployment variables in the hosting dashboard, not in this repository.
- WhatsApp Cloud API requires a configured Meta Business Portfolio, WhatsApp Business Account, phone number ID, access token, and webhook setup.
- Payment receipts remain pending until manually verified or supported by an official bank/merchant integration.

## Local development
```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Health: `/health`. Webhook: `/webhook`.

## Commands
- `/بيع الموديل | السعر | المدينة | الحالة`
- `/طلب الموديل | الميزانية | المدينة`
- `/العروض`, `/الطلبات`, `/مطابقات`, `/الحالة`
- `/الدفع`
- `/إيصال رقم_الإشعار | المبلغ | رقم_المطابقة`

This is an MVP. It does not automatically acquire customers or confirm bank transfers.
