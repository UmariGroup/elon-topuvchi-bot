# Parser aniqligi bahosi

**Holati: HALI O'TKAZILMAGAN.**

Qabul mezoni: 100 ta real, qo'lda belgilangan e'lon namunasida parser maydonlarni ≥85% to'g'ri
ajratishi kerak.

Bu baho quyidagilarsiz o'tkazib bo'lmaydi, shuning uchun kod yozilgan muhitda bajarilmadi:

1. collector real Telegram kanallaridan yig'gan postlar (Telegram akkaunt kerak);
2. Claude API kaliti;
3. 100 ta namunani **odam** qo'lda belgilashi (agar modelning o'zi belgilasa, u o'zini o'zi
   tekshirgan bo'ladi va natija ma'nosiz).

Baholash vositasi tayyor va testlangan (`tests/test_eval_parser.py`). O'tkazish tartibi —
README'dagi "Parser aniqligini o'lchash" bo'limida. `run` buyrug'i shu faylni haqiqiy natija
bilan almashtiradi: umumiy aniqlik, har maydon bo'yicha aniqlik va xatolar ro'yxati.
