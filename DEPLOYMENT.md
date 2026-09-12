# Deployment checklist

1. Rotate every credential that was stored in the old local credential snippet:
   Vertex service-account key, Telegram token, Supabase secret key, and speech-provider keys.
2. In Supabase SQL Editor, run the complete [`database/supabase_schema.sql`](database/supabase_schema.sql) file. It adds weight columns and the `custom_products` table used by package-photo recognition.
3. In Vercel Project Settings → Environment Variables, add the values from `.env.example` with fresh secrets. For Vertex, `GOOGLE_APPLICATION_CREDENTIALS_JSON` must be the entire service-account JSON on one line; set `GOOGLE_CLOUD_LOCATION=global` unless your selected model explicitly supports a regional endpoint. Set a long random `TELEGRAM_WEBHOOK_SECRET` too.
4. Deploy. Then use the Vercel function logs to run the equivalent of `python test_vertex.py` once from an environment that can reach Google OAuth.
5. Register the webhook after deployment:

   `https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://fatcaunter.vercel.app/api/telegram_webhook&secret_token=<TELEGRAM_WEBHOOK_SECRET>`

The webhook permits only `TELEGRAM_USER_ID` when that variable is configured. Its short-lived interaction mode is held in the Vercel function instance; a cold start simply falls back to automatic intent detection.
