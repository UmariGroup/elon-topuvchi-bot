"""Botning barcha matnlari (o'zbek tili, lotin)."""

from __future__ import annotations

from datetime import datetime

from elon.timeutil import TASHKENT

ASK_CONTACT = (
    "Assalomu alaykum! Men Toshkentdagi kvartira ijarasi e'lonlarini Telegram kanallaridan "
    "yig'ib, sizga eng mos va xavfsizlarini topib beraman.\n\n"
    "Boshlash uchun pastdagi tugma orqali telefon raqamingizni ulashing."
)
CONTACT_BUTTON = "📱 Kontaktni ulashish"
OWN_CONTACT_ONLY = "Iltimos, pastdagi tugma orqali o'zingizning raqamingizni ulashing."
NEED_REGISTRATION = "Avval ro'yxatdan o'ting: /start"

PAYMENT = (
    "Bepul sinov muddati tugadi.\n\n"
    "Davom etish uchun to'lov qilish kerak. Adminimiz siz bilan bog'lanadi — "
    "to'lovdan keyin bot yana ishlaydi."
)
DAILY_LIMIT = "Bugungi xabarlar limiti tugadi. Ertaga davom etamiz."
AI_ERROR = "Hozir javob bera olmadim. Birozdan keyin qayta yozib ko'ring."
UNKNOWN_COMMAND = "Bunday buyruq yo'q. Yordam: /help"
NO_FILTER = "Avval qanday kvartira kerakligini yozing."

CONFIRM_HEADER = "Filtringiz:"
CONFIRM_QUESTION = "Shu bo'yicha qidiraymi?"
BTN_CONFIRM = "✅ Ha, qidir"
BTN_EDIT = "✏️ O'zgartirish"
EDIT_PROMPT = "Nimani o'zgartiramiz? Yozib yuboring."

SEARCHING = "Qidiryapman..."
NO_RESULTS = (
    "Hozircha bu filtr bo'yicha mos e'lon topilmadi. "
    "Filtrni kengaytirib ko'rishingiz yoki kuzatuvni yoqishingiz mumkin."
)
RESULTS_FOOTER = (
    "Ishonch balli — avtomatik baho, kafolat emas. Pulni faqat uyni ko'rib, "
    "hujjatlarni tekshirgach bering."
)
WATCH_QUESTION = "Yangi mos e'lon chiqsa xabar beraymi?"
BTN_WATCH_YES = "🔔 Ha"
BTN_WATCH_NO = "Yo'q"
WATCH_ON = (
    "Kuzatuv yoqildi. Mos e'lon chiqishi bilan yuboraman (kuniga ko'pi bilan {limit} ta).\n"
    "O'chirish: /stop"
)
WATCH_OFF = "Kuzatuv o'chirildi."
WATCH_DECLINED = "Mayli. Filtrni o'zgartirmoqchi bo'lsangiz, shunchaki yozing."
WATCH_NOT_ACTIVE = "Faol kuzatuv yo'q."
FEEDBACK_THANKS = "Rahmat, bahoyingiz qabul qilindi."

DELETE_QUESTION = (
    "Barcha ma'lumotingiz (telefon raqam, suhbat, kuzatuv, baholar) o'chiriladi. "
    "Bu amalni qaytarib bo'lmaydi. O'chiraymi?"
)
BTN_DELETE_YES = "Ha, o'chir"
BTN_DELETE_NO = "Yo'q"
DELETED = "Ma'lumotingiz o'chirildi. Qaytadan boshlash uchun: /start"
DELETE_CANCELLED = "Bekor qilindi."

ADMIN_ACTIVATE_USAGE = "Foydalanish: /activate <user_id> <kun>\nMasalan: /activate 123456789 7"
ADMIN_USER_NOT_FOUND = "Bunday ID bilan foydalanuvchi topilmadi."

HELP = (
    "Men Toshkentda uzoq muddatli kvartira ijarasi e'lonlarini topib beraman.\n\n"
    "Qanday ishlaydi:\n"
    "1. Qanday kvartira kerakligini erkin yozing. Masalan: "
    "«Chilonzorda 2 xonali, 400$ gacha, oilaga».\n"
    "2. Men bir-ikki savol berib, filtrni aniqlayman.\n"
    "3. Eng mos 5 ta e'lonni ishonch balli va manba havolasi bilan yuboraman.\n"
    "4. Xohlasangiz, yangi mos e'lon chiqqanda xabar beraman.\n\n"
    "Buyruqlar:\n"
    "/start — boshlash\n"
    "/stop — kuzatuvni o'chirish\n"
    "/delete_me — barcha ma'lumotimni o'chirish\n"
    "/help — yordam\n\n"
    "Dastlabki {trial_days} kun bepul. Telefon raqamingiz va suhbatlaringiz faqat xizmat "
    "serverida saqlanadi va hech kimga berilmaydi."
)


def _date(moment: datetime) -> str:
    return moment.astimezone(TASHKENT).strftime("%d.%m.%Y")


def registered(trial_days: int, trial_ends_at: datetime) -> str:
    return (
        f"Ro'yxatdan o'tdingiz. {trial_days} kunlik bepul sinov {_date(trial_ends_at)} gacha amal "
        "qiladi.\n\n"
        "Endi qanday kvartira qidirayotganingizni yozing. Masalan: "
        "«Chilonzorda 2 xonali, 400$ gacha, oilaga»."
    )


def welcome_back(until: datetime | None) -> str:
    if until is None:
        return PAYMENT
    return (
        f"Qaytganingizdan xursandman. Xizmat {_date(until)} gacha faol.\n"
        "Qanday kvartira qidirayotganingizni yozing."
    )


def confirm(filter_description: str) -> str:
    return f"{CONFIRM_HEADER}\n{filter_description}\n\n{CONFIRM_QUESTION}"


def activated_user(days: int, until: datetime) -> str:
    return f"Obunangiz {days} kunga faollashtirildi. {_date(until)} gacha amal qiladi."


def activated_admin(tg_id: int, days: int, until: datetime) -> str:
    return f"✅ {tg_id}: {days} kun qo'shildi, {_date(until)} gacha faol."
