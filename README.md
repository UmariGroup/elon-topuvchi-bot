# E'lon topuvchi — Telegram bot (MVP)

Toshkentdagi **uzoq muddatli kvartira ijarasi** e'lonlarini Telegram kanallaridan yig'adi, Claude
bilan tahlil qiladi, har biriga 0–100 "ishonch balli" qo'yadi va foydalanuvchiga suhbat orqali eng
mos 5 tasini manba havolasi bilan topib beradi.

Bu 2 haftalik sinov versiyasi: 20–30 foydalanuvchida "odamlar bunga pul to'laydimi?" degan savolga
javob olish uchun. To'lov tizimi, veb-panel, OLX/Birbir parsingi **yo'q** (ataylab).

> **Holati.** Kod, testlar (`pytest`), `ruff` va `mypy` — bajarilgan va haqiqatan ishga tushirilgan.
> Real Telegram akkaunt, bot tokeni va Claude kaliti bilan sinov **o'tkazilmagan** — batafsil:
> [`reports/hisobot.md`](reports/hisobot.md).

## Qanday ishlaydi

```
Telegram kanallar ──Telethon──► collector ──► raw_posts ──► parser (Claude Haiku)
                                                               │
                                              dublikat + ishonch balli (rules/)
                                                               ▼
foydalanuvchi ◄──aiogram──► bot ◄── suhbat (Claude Sonnet) ◄── listings
                             └── kuzatuv bildirishnomalari, sinov muddati, admin
```

Uchta servis (`docker compose`): **db** (PostgreSQL 16), **collector** (kanallarni o'qish + tahlil),
**bot** (foydalanuvchi bilan muloqot + fon ishlari).

| Papka | Vazifasi |
|---|---|
| `src/elon/collector/` | Kanallarni o'qish. `service.py` — mantiq (testlangan), `telegram.py` — Telethon adapteri |
| `src/elon/pipeline/` | Xom post → AI → e'lon → dublikat → ball. Toifadan mustaqil |
| `src/elon/categories/` | Toifa interfeysi (`base.py`) va yagona toifa — `rent/` (promptlar, filtr, tumanlar) |
| `src/elon/rules/` | Xavfsizlik qoidalari — bazaga tegmaydigan pure funksiyalar |
| `src/elon/llm/` | Claude chaqiruvi, narx jadvali, xarajat hisobi va kunlik limit |
| `src/elon/services/` | Foydalanuvchi, suhbat, qidiruv, kuzatuv, statistika |
| `src/elon/bot/` | aiogram handlerlari, matnlar, fon ishlari |
| `src/elon/tools/eval_parser.py` | Parser aniqligini qo'lda belgilangan namunada o'lchash |
| `config/channels.yaml` | Kanallar ro'yxati |

## Tez yo'l: `./deploy.sh`

Serverda (Docker o'rnatilgan bo'lsa):

```bash
git clone https://github.com/UmariGroup/elon-topuvchi-bot.git && cd elon-topuvchi-bot
./deploy.sh        # 1-marta .env yaratadi -> nano .env bilan to'ldiring
./deploy.sh        # 2-marta: build, Telegram'ga kirish (kod so'raladi), ishga tushirish
```

Keyingi yangilanishlar: `./deploy.sh` (git pull + qayta ko'tarish). Quyida — xuddi shu qadamlar qo'lda.

## O'rnatish (toza server)

Kerak: Docker + Docker Compose, **alohida** Telegram akkaunt (shaxsiy raqamingiz emas — pastdagi
"Telegram akkaunt xavfi" bo'limiga qarang).

1. **Kodni oling va `.env` yarating**

   ```bash
   git clone <repo> elon-topuvchi && cd elon-topuvchi
   cp .env.example .env && chmod 600 .env
   ```

   `.env` ni to'ldiring (kalitlar faqat shu faylda, serverda turadi):

   | O'zgaruvchi | Qayerdan olinadi |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | @BotFather → `/newbot` |
   | `TG_API_ID`, `TG_API_HASH` | https://my.telegram.org → API development tools (collector akkaunti bilan) |
   | `TG_SESSION_PATH` | o'zgartirmang: `/data/collector.session` |
   | `ANTHROPIC_API_KEY` | Claude Console |
   | `POSTGRES_PASSWORD` | o'zingiz o'ylab topgan uzun parol |
   | `DATABASE_URL` | `postgresql://elon:<POSTGRES_PASSWORD>@db:5432/elon` |
   | `ADMIN_IDS` | admin Telegram ID'lari, vergul bilan: `111,222` |
   | `TRIAL_DAYS` | bepul sinov kunlari (standart 7) |
   | `DAILY_AI_BUDGET_USD` | kunlik AI limiti, dollarda (standart 3) |

2. **Kanallar ro'yxatini ko'rib chiqing** — `config/channels.yaml`. Hozir u yerda vebdan topilgan
   12 ta nomzod bor (tasdiqlanmagan). 30–50 taga yetkazish — 5-qadam.

3. **Obrazni yig'ing va Telegram akkauntga bir marta kiring**

   ```bash
   docker compose build
   docker compose run --rm collector python -m elon.collector.login
   ```

   Telefon raqam va Telegram yuborgan kod so'raladi. Session fayl `tgsession` volume'ida saqlanadi.

4. **Ishga tushiring**

   ```bash
   docker compose up -d
   docker compose logs -f collector bot
   ```

   Birinchi ishga tushishda collector har kanaldan oxirgi 7 kunni oladi, keyin har 3 daqiqada
   yangilarini tekshiradi; a'zo bo'lingan kanallardan postlar real vaqtda keladi. Kanallarga
   a'zo bo'lish sekin: kuniga ko'pi bilan 20 ta, orada 3–8 daqiqa.

5. **Kanallar ro'yxatini kengaytirish** (ixtiyoriy, lekin 30+ kanal uchun kerak)

   ```bash
   docker compose stop collector
   docker compose run --rm collector python -m elon.collector.discover
   docker compose start collector
   ```

   Telegram qidiruvi natijalari `- username: ...  # a'zolar | nomi` ko'rinishida chiqadi. Mos
   kelganlarini `config/channels.yaml` ga qo'shib, `docker compose restart collector` qiling.

**Portlar.** Hech qaysi servis tashqariga port ochmaydi (bot long-polling ishlatadi, baza faqat
ichki tarmoqda). Shuning uchun serverdagi n8n (5678) yoki boshqa PostgreSQL bilan to'qnashuv yo'q.

## Bot

Foydalanuvchi: `/start` → "Kontaktni ulashish" → erkin yozadi («Chilonzorda 2 xonali, 400$ gacha,
oilaga») → bot bir-ikki savol beradi → filtrni tasdiqlaydi → eng yaxshi 5 e'lon (tavsif, narx,
ishonch balli va sabablari, **manba postiga havola** — e'lon egasining telefoni ko'rsatilmaydi) →
har natija ostida 👍/👎 → "Yangi mos e'lon chiqsa xabar beraymi?".

| Buyruq | Kim | Nima qiladi |
|---|---|---|
| `/start`, `/help` | hamma | boshlash, yordam |
| `/stop` | hamma | kuzatuvni o'chirish |
| `/delete_me` | hamma | barcha shaxsiy ma'lumotni o'chirish (tasdiq so'raydi) |
| `/stats` | admin | ro'yxatdan o'tganlar, faol, sinovi tugaganlar, so'rovlar, 👍/👎, AI xarajati |
| `/activate <user_id> <kun>` | admin | obunani qo'lda faollashtirish (amaldagi muddat ustiga qo'shiladi) |

Sinov tugaganda foydalanuvchiga "Davom etish uchun to'lov" xabari, admin'ga esa foydalanuvchi
ID'si va tayyor `/activate` buyrug'i yuboriladi.

## Ishonch balli

100 dan boshlanadi, har belgi uchun jarima ayriladi. Qoidalar: `src/elon/rules/`.

| Belgi | Jarima |
|---|---:|
| Narx shu tuman + xona soni medianasidan ≥35% past (≥50% past) | 35 (50) |
| Uyni ko'rishdan oldin pul o'tkazish so'ralgan | 45 |
| Depozit / zaklad / oldindan to'lov so'ralgan | 10 |
| Shu telefon yana ≥3 (≥8) boshqa e'londa | 15 (25) |
| Rasm yo'q | 15 |
| Aynan shu rasm boshqa telefonli e'londa ham bor | 30 |
| E'lon ≥14 (≥30) kun oldin joylangan | 15 (35) |

Mediana kamida 5 ta e'lon bo'lgan segmentdagina hisoblanadi (oxirgi 30 kun). Claude faqat
matndagi belgilarni (depozit, oldindan to'lov) topadi; ballni kod hisoblaydi.

## AI xarajati

- E'lon tahlili: `claude-haiku-5-5`, suhbat: `claude-sonnet-5-5`. Tizim promptlari keshlanadi.
- Har chaqiruvning tokenlari va narxi `ai_calls` jadvaliga yoziladi (`/stats` da ko'rinadi).
- Kunlik jami xarajat `DAILY_AI_BUDGET_USD` dan oshsa, **yangi e'lonlarni tahlil qilish ertangi
  kungacha to'xtaydi** va admin'ga xabar ketadi. Suhbat to'xtamaydi, lekin har foydalanuvchi
  kuniga ko'pi bilan 40 ta xabar yubora oladi (`USER_DAILY_MESSAGE_LIMIT`).
- Bir post faqat bir marta tahlil qilinadi; aynan bir xil matn boshqa kanalda chiqsa, AI qayta
  chaqirilmaydi.
- Narxlar `src/elon/llm/pricing.py` da (2026-11-13 holatiga). Narx o'zgarsa shu faylni yangilang.

## Shaxsiy ma'lumotlar

- Foydalanuvchi telefoni va suhbatlari faqat shu serverdagi PostgreSQL'da (`pgdata` volume).
- Loglarga telefon yozilmaydi (qo'shimcha himoya: log filtri telefonga o'xshash raqamni yashiradi).
- `/delete_me` foydalanuvchining telefon, suhbat, filtr, kuzatuv, baho va so'rovlarini o'chiradi.
- E'lon egalarining telefoni bazada **saqlanmaydi** — faqat qaytarib bo'lmaydigan xeshi
  (dublikat va "bitta raqam ko'p e'londa" qoidasi uchun). E'lonning xom matni (ichida telefon
  bo'lishi mumkin) `raw_posts` jadvalida turadi.

### ⚠️ Server joylashuvi — TEKSHIRILISHI KERAK

O'zbekiston qonunchiligiga ko'ra fuqarolarning shaxsiy ma'lumotlari O'zbekiston hududidagi
serverda saqlanishi kerak.

- **Server joylashuvi: ______________________ (to'ldirilmagan — loyiha egasi tekshiradi)**
- **Claude API haqida.** Foydalanuvchi suhbatda yozgan matn va e'lon matnlari tahlil uchun
  Anthropic API'ga (O'zbekistondan tashqaridagi serverlar) yuboriladi. Foydalanuvchining telefon
  raqami va Telegram ID'si API'ga **yuborilmaydi**. Bu qonun talabiga mos kelish-kelmasligini
  huquqshunos bilan aniqlash kerak — kod buni hal qilmaydi.

## Telegram akkaunt xavfi

Collector oddiy foydalanuvchi akkaunti (MTProto) orqali ishlaydi. Telegram avtomatlashtirilgan
akkauntlarni cheklashi yoki bloklashi mumkin.

- **Shaxsiy raqamingizni ishlatmang** — alohida SIM-karta oling. Akkaunt bloklansa, undagi hamma
  narsa yo'qoladi.
- Yangi akkauntni darhol ulamang: bir necha kun oddiy ishlatib, keyin ulang.
- Himoya choralari kodda bor: FloodWait'da Telegram so'ragan vaqt + tasodifiy qo'shimcha
  kutiladi; kanallar orasida 2–5 soniya pauza; kuniga ≤20 kanalga a'zo bo'lish.
- Session fayl akkauntga to'liq kirish beradi — uni hech kimga bermang, repoga qo'shmang.
- Kanal egalari kontentdan foydalanishga e'tiroz bildirishi mumkin. Bot e'lon matnini ko'chirmaydi:
  qisqa tavsif va asl postga havola beradi.

## Parser aniqligini o'lchash (qabul mezoni: ≥85%)

Bu bosqich real yig'ilgan e'lonlar va **odam qo'li bilan belgilash**ni talab qiladi:

```bash
# 1. Bazadan tasodifiy 100 ta post -> reports/data/samples.csv (repoga qo'shilmaydi)
docker compose run --rm -u root -v ./reports:/app/reports collector \
    python -m elon.tools.eval_parser export --n 100
# 2. CSV'ni Excel/Google Sheets'da ochib, har qatorni qo'lda belgilang
#    (ustunlar tavsifi: src/elon/tools/eval_parser.py boshida)
# 3. Baholash -> reports/parser_eval.md
docker compose run --rm -u root -v ./reports:/app/reports collector \
    python -m elon.tools.eval_parser run
```

## Ishlab chiqish

```bash
uv sync
uv run pytest                 # xotiradagi SQLite'da
TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/test_db uv run pytest   # haqiqiy PostgreSQL'da
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Qoidalar: `main` ga to'g'ridan-to'g'ri push qilinmaydi — alohida branch va PR.

## Qo'shimcha sozlamalar (ixtiyoriy)

`.env` ga qo'shish mumkin; berilmasa standart qiymat ishlaydi.

| O'zgaruvchi | Standart | Ma'nosi |
|---|---|---|
| `USD_UZS_RATE` | 12700 | so'mdagi narxni dollarga o'tkazish kursi |
| `USER_DAILY_MESSAGE_LIMIT` | 40 | foydalanuvchining kunlik suhbat xabarlari |
| `MAX_NOTIFICATIONS_PER_DAY` | 10 | kuzatuv bo'yicha kunlik xabarlar |
| `MAX_JOINS_PER_DAY` | 20 | kuniga nechta kanalga a'zo bo'lish |
| `BACKFILL_DAYS` | 7 | birinchi ishga tushishda necha kun orqaga |
| `POLL_INTERVAL_SECONDS` | 180 | kanallarni tekshirish oralig'i |
| `SEARCH_MAX_AGE_DAYS` | 14 | qidiruvda necha kunlik e'lonlar ko'rsatiladi |
| `MIN_NOTIFY_SCORE` | 40 | bundan past balli e'lon kuzatuvga yuborilmaydi |
| `PARSER_MODEL`, `CHAT_MODEL` | `claude-haiku-5-5`, `claude-sonnet-5-5` | modellar |
| `PHONE_HASH_SALT` | `TG_API_HASH` | e'lon egasi telefonini xeshlash kaliti |

## Ma'lum cheklovlar

- Baza sxemasi `create_all` bilan yaratiladi, migratsiya vositasi (Alembic) yo'q. Jadval
  tuzilishi o'zgarsa qo'lda `ALTER TABLE` kerak bo'ladi.
- Haqiqiy "stok rasm" aniqlash yo'q — faqat "rasm yo'q" va "shu rasm boshqa telefonli e'londa ham
  bor" (Telegram miniatyurasi bo'yicha, taxminiy).
- Dollar kursi qo'lda (`USD_UZS_RATE`), avtomatik yangilanmaydi.
- Bitta foydalanuvchida bitta kuzatuv (oxirgi tasdiqlangan filtr).
- Kunlik AI limiti jami xarajat bo'yicha: foydalanuvchi ko'paysa suhbat xarajati limitni yeb,
  e'lon tahlilini to'xtatib qo'yishi mumkin — limitni o'shanda oshirish kerak.
- Faqat ochiq (username'li) kanallar. Yopiq kanal va guruhlar o'qilmaydi.
- Ovozli xabar, to'lov, boshqa toifalar — yo'q.

## Keyingi bosqich uchun qoldirilgan joy

- **Yangi toifa** (texnika, avto, kiyim, ish e'lonlari): `elon.categories.base.Category` ni amalga
  oshirib, `REGISTRY` ga qo'shiladi; `channels.yaml` da kanalga `category:` beriladi. Collector va
  parser konveyeri o'zgarmaydi — shu sababli ularni Ishkun24 uchun qayta ishlatish mumkin.
- **Yangi manba** (OLX/Birbir — rasmiy ruxsatdan keyin): `collector.service.PostSource` protokolini
  amalga oshiradi.
- **To'lov** (Click/Payme): `services.users.activate()` tayyor — to'lov tasdig'i shu funksiyani
  chaqiradi.
