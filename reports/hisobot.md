# Hisobot: "E'lon topuvchi" MVP

Sana: 2026-11-13. Kod yozilgan muhit: bulutdagi ish maydoni (serveringiz emas) — bu yerda Docker
daemon, real Telegram akkaunt, bot tokeni va Claude API kaliti **yo'q**, Telegram va Anthropic
serverlariga tarmoq yopiq. Shu sababli quyida "sinaldi" va "sinalmadi" qat'iy ajratilgan.

## Qabul mezonlari bo'yicha holat

| # | Mezon | Holat |
|---|---|---|
| 1 | `docker compose up` bilan 3 servis ko'tariladi | ⚠️ Qisman: `docker compose config` to'g'ri; obraz yig'ilmagan va konteynerlar ishga tushirilmagan |
| 2 | 30+ kanal, parser ≥85% (100 namuna) | ❌ Bajarilmagan: 12 ta kanal nomzodi bor, baho o'tkazilmagan (vosita tayyor) |
| 3 | Har qoida uchun ijobiy/salbiy unit test, `pytest` yashil | ✅ |
| 4 | Botda to'liq yo'l ishlaydi | ⚠️ Haqiqiy aiogram Dispatcher orqali, soxta Telegram va soxta Claude bilan o'tdi; jonli Telegram'da sinalmagan |
| 5 | Kunlik AI limit oshsa tahlil to'xtashi test bilan isbotlangan | ✅ |
| 6 | `ruff` va `mypy` xatosiz | ✅ (`mypy --strict`) |
| 7 | Hisobot | ✅ shu fayl |

## Nima qilindi

- **Collector** (Telethon): kanallar ro'yxatini `config/channels.yaml` dan o'qish, birinchi
  ishga tushishda oxirgi 7 kun, keyin har 3 daqiqada yangilari + a'zo bo'lingan kanallardan real
  vaqt; FloodWait'ni kutish; kuniga ≤20 kanalga a'zo bo'lish; topilmagan kanalni o'chirish.
- **Parser** (`claude-haiku-5-5`): bitta majburiy tool orqali JSON; tuman, mo'ljal, xona, narx
  (standart — AQSH dollari), maydon, qavat, mebel, kim uchun, egasi/vositachi, depozit belgilari,
  qisqa o'zbekcha tavsif. Ishonchsiz qiymat `null`. Dublikat: matn o'xshashligi + telefon + narx.
- **Ishonch balli**: 5 ta qoida `src/elon/rules/` da pure funksiya sifatida.
- **Bot** (aiogram 3): `/start` → kontakt → suhbat (`claude-sonnet-5-5`) → filtr tasdig'i → 5 natija
  → 👍/👎 → kuzatuv → bildirishnoma (kuniga ≤10) → sinov tugashi → `/activate`; `/stats`,
  `/stop`, `/delete_me`, `/help`.
- **Xarajat nazorati**: har chaqiruv tokenlari va narxi bazada; kunlik limit; prompt caching;
  bir post bir marta tahlil qilinadi.
- **Docker Compose** (bot + collector + db, tashqariga port ochilmaydi), README, `.env.example`.

Promptdan ataylab chetga chiqilgan joylar:

1. Depozit/zaklad — kichik jarima (10), "ko'rishdan oldin pul" — katta (45). Sabab: depozit
   Toshkentda halol e'lonlarda ham odatiy.
2. "Stok rasm" o'rniga "shu rasm boshqa telefonli e'londa ham bor" tekshiruvi.
3. E'lon egasining telefoni bazada faqat xesh ko'rinishida.
4. Har foydalanuvchiga kunlik 40 ta suhbat xabari limiti qo'shildi.
5. Bozor medianasi faqat ≥5 ta e'lonli segmentda ishlaydi.
6. `.env` ga bitta qo'shimcha nom: `POSTGRES_PASSWORD` (db konteyneri uchun).
7. Uzoq muddatli "xona / sheriklikka" e'lonlari ham yig'iladi, lekin standart qidiruvda faqat
   butun kvartira chiqadi.

## Nima sinaldi (haqiqatan ishga tushirib)

- `uv run pytest`: **139 test o'tdi** — xotiradagi SQLite'da ham, haqiqiy **PostgreSQL 16** da ham
  (asyncpg orqali).
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` (strict, 64 fayl) — xatosiz.
- Qoidalar: har biri uchun ijobiy va salbiy holat, jumladan inkor shakllari ("depozitsiz",
  "без залога") va chegara qiymatlari.
- Kunlik limit: limit oshgach AI chaqirilmasligi, postlar navbatda qolishi, admin'ga bitta xabar,
  ertasi kuni davom etishi.
- Konveyer: bir post bir marta tahlil, bir xil matn AI'siz qayta ishlatilishi, yaqin dublikat,
  telefonning faqat xeshi saqlanishi, xatoda 3 urinish.
- Bot yo'li: haqiqiy aiogram Dispatcher'ga Telegram formatidagi update'lar berildi (Telegram
  serveri va Claude soxta). `/start` dan `/delete_me` gacha, jumladan birovning kontakti rad
  etilishi, muddati tugagach AI chaqirilmasligi, admin bo'lmagan odamga `/activate` va `/stats`
  yopiqligi.
- Collector mantiqi soxta manba bilan: 7 kunlik birinchi yig'ish, faqat yangilarini olish,
  a'zo bo'lish limiti (30 kanaldan birinchi kuni 20 tasi). Telethon'ning haqiqiy xabar obyekti
  `PostData` ga to'g'ri aylanishi.
- `python -m elon.bot.main` va `python -m elon.collector.main` haqiqiy PostgreSQL bilan ishga
  tushirildi: sozlamalar o'qildi, 11 jadval yaratildi, 12 kanal bazaga yozildi, ikkalasi bir
  vaqtda boshlanganda to'qnashuv bo'lmadi. Ikkalasi ham Telegram'ga ulanish bosqichida to'xtadi
  (tarmoq yopiq) — kutilgan holat.
- `docker compose config` — fayl to'g'ri, 3 servis.

Ish davomida testlar topgan va tuzatilgan xatolar: kuzatuv yoqilishidan oldingi e'lonlar ham
yuborilib ketishi; birinchi yig'ishda posti bo'lmagan kanal keyingi safar kanalning eng boshidan
o'qilishi; baza paroli sozlamalar `repr` ida ko'rinishi.

## Nima sinalmadi

- **Docker obrazini yig'ish va `docker compose up`** — bu muhitda Docker daemon yo'q.
  `Dockerfile` dagi `ghcr.io/astral-sh/uv:0.11.32` tegi ham tekshirilmagan.
- **Telethon bilan real ishlash**: akkauntga kirish, kanal o'qish, a'zo bo'lish, real vaqt
  hodisalari, haqiqiy FloodWait. `collector/telegram.py` va `collector/main.py` dagi sikllar
  faqat tip tekshiruvidan o'tgan.
- **Claude API'ga birorta ham haqiqiy so'rov yuborilmagan.** Ya'ni: promptlar sifati, tool
  sxemasini API qabul qilishi, kesh amalda ishlashi (`cache_read` > 0), model nomlari — hammasi
  serverda birinchi ishga tushirishda tekshirilishi kerak. `/stats` dagi "Keshdan o'qilgan prompt
  ulushi" 0% bo'lib qolsa, kesh ishlamayapti.
- **Parser aniqligi (≥85%)** — o'lchanmagan.
- **Jonli Telegram bot**: haqiqiy token, tugmalar ko'rinishi, xabar uzunligi, havola preview'i.
- **Kanallar**: `config/channels.yaml` dagi 12 ta nom veb-qidiruvdan olingan; ularning hozir
  mavjudligi, faolligi va e'lon sifati Telegram orqali tekshirilmagan. 30+ ga yetkazish uchun
  `python -m elon.collector.discover` yozilgan — u ham ishga tushirilmagan.
- `collector.login` va `collector.discover` skriptlari.
- Yuklama ostida ishlash, uzoq muddat (kunlab) barqarorlik.

## Ma'lum cheklovlar

- Migratsiya vositasi yo'q (`create_all`).
- Dollar kursi qo'lda (`USD_UZS_RATE=12700`).
- Kunlik AI limiti jami xarajat bo'yicha hisoblanadi, lekin faqat e'lon tahlilini to'xtatadi.
  Foydalanuvchi ko'paysa suhbat xarajatining o'zi limitni yeb, tahlilni to'xtatishi mumkin
  (pastga qarang).
- Bitta foydalanuvchi ketma-ket juda tez yozsa, ikki xabar parallel ishlanib, biri "javob bera
  olmadim" bilan qaytishi mumkin.
- Tuman faqat e'londa aniq yozilgan yoki taniqli mo'ljal bo'lsa aniqlanadi; aks holda `null`,
  va bunday e'lon tuman bo'yicha qidiruvda chiqmaydi.
- Faqat ochiq kanallar; guruhlar va yopiq kanallar yo'q.
- **Huquqiy**: server joylashuvi README'da to'ldirilmagan. Suhbat va e'lon matnlari Claude
  API'ga (chet eldagi serverlar) yuboriladi — foydalanuvchi telefoni yuborilmaydi. Bu
  ma'lumotlarni mahalliylashtirish talabiga mos kelishini huquqshunos aniqlashi kerak.
- Collector akkaunti bloklanishi mumkin (README, "Telegram akkaunt xavfi").

## 1000 foydalanuvchiga taxminiy oylik AI xarajati

**Taxminan $120–130 / oy** (oraliq: $60–280). Deyarli hammasi suhbatga ketadi.

Bu hisob-kitob, o'lchov emas: token sonlari prompt uzunligidan taxmin qilingan, haqiqiy
chaqiruv bo'lmagan. Narxlar rasmiy sahifadan (2026-11-13): Haiku 5.5 — $0.10 / $0.50, kesh
o'qish $0.01; Sonnet 5.5 — $2 / $10, kesh o'qish $0.10, kesh yozish $2.50 (1 mln token uchun).

| Qism | Faraz | Bir chaqiruv | Oyiga |
|---|---|---:|---:|
| E'lon tahlili (Haiku) | 40 kanal × ~50 post/kun, ~60% i AI'ga boradi ≈ 1200 chaqiruv/kun; ~2300 token kesh + ~350 kirish + ~220 chiqish | ≈ $0.00017 (keshsiz ≈ $0.00038) | **$6–14** |
| Suhbat (Sonnet) | 1000 faol foydalanuvchi × ~35 xabar/oy; ~1330 token kesh + ~350 kirish + ~150 chiqish; keshning 70% i "issiq" | ≈ $0.0033 (kesh bilan $0.0023, keshsiz $0.0055) | **≈ $115** |

- E'lon tahlili foydalanuvchi soniga bog'liq emas — faqat kanallar hajmiga.
- Suhbat chiziqli o'sadi: kam ishlatilsa (15 xabar/oy) ≈ $50, ko'p ishlatilsa (80 xabar/oy) ≈ $265.
  Bir foydalanuvchiga ≈ $0.05–0.27 / oy.
- **Diqqat:** 1000 foydalanuvchida suhbat kuniga ≈ $4 sarflaydi — bu standart
  `DAILY_AI_BUDGET_USD=3` dan ko'p, ya'ni e'lon tahlili har kuni to'xtab qoladi. O'sha bosqichda
  limitni kamida $8–10 ga oshirish yoki suhbat va tahlil uchun alohida limit qilish kerak.
- 20–30 kishilik sinovda: tahlil ≈ $6–14 + suhbat ≈ $3–4 = **oyiga ≈ $10–18**.

## Serverda birinchi navbatda qilinadigan ishlar

1. `.env` ni to'ldirish, `docker compose build`, `collector.login`, `docker compose up -d`.
2. Loglarda birinchi Claude chaqiruvlari xatosiz o'tganini va `/stats` da kesh ulushi 0 dan
   katta ekanini ko'rish.
3. `collector.discover` bilan kanallar ro'yxatini 30+ ga yetkazish va tasdiqlash.
4. 2–3 kun yig'ilgach: 100 namunani belgilab, `eval_parser run` — mezon 2 ni yopish.
5. Botni o'zingiz to'liq yo'l bo'yicha bir marta qo'lda o'tib chiqish — mezon 4 ni yopish.
6. README'da server joylashuvini to'ldirish.
