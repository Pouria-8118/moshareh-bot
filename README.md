# 🎭 Persian Poetry Battle Bot (Moshareh)

A Telegram bot implementing **Moshareh**, a traditional Persian poetry game where players take turns reciting verses starting with the last letter of the previous verse.

The bot leverages Persian NLP (via [Hazm](https://github.com/sobhe/hazm)) for advanced text normalization and [RapidFuzz](https://github.com/maxbachmann/RapidFuzz) for fuzzy matching algorithms to validate user inputs against a database of 666,000+ Persian couplets extracted from [Ganjoor](https://ganjoor.net).

**Tech Stack:** Python, python-telegram-bot, SQLite, Hazm (Persian NLP), RapidFuzz (Fuzzy String Matching)

---

## ✨ ویژگی‌ها

- 🎯 **حالت تک‌نفره (Solo):** رقابت با ربات همراه با ثبت رکورد شخصی و سیستم سختی پویا (Dynamic Difficulty Adjustment)
- ⚔️ **حالت دو نفره (PVP):** مشاعره رقابتی بین دو کاربر در گروه‌ها با داوری ربات
- 🏆 **جدول امتیازات گروه:** نمایش برترین رکوردها و بیشترین بردهای کاربران در هر گروه
- 🔄 **سیستم تطبیق هوشمند بیت:** پشتیبانی از تطبیق دقیق (Exact Match) و تطبیق تقریبی (Fuzzy Match)
- 🛡️ **جلوگیری از تکرار:** عدم پذیرش بیت‌های تکراری در طول یک بازی
- ⏱️ **تایمر هوشمند:** مدیریت زمان پاسخ‌گویی با JobQueue

## 📚 منابع

پایگاه داده اشعار این ربات از پروژه متن‌باز و ارزشمند **[گنجور (Ganjoor)](https://github.com/ganjoor)** استخراج و پردازش شده است. بدون وجود این گنجینه عظیم ادبیات فارسی، ساخت چنین پروژه‌ای ممکن نبود. صمیمانه از تیم گنجور و تمام مشارکت‌کنندگان آن تشکر می‌کنیم.

## 📜 لایسنس

این پروژه صرفاً با هدف **آموزشی (Educational Purpose)** منتشر شده است.

- ✅ مجاز به مطالعه، یادگیری و الهام گرفتن از ساختار و منطق کد هستید.
- ❌ استفاده تجاری، کلون کردن کامل و اجرای عمومی ربات با توکن و هویت مشابه ممنوع است.
- ❌ انتشار مجدد کد به صورت دست‌نخورده (verbatim) بدون اجازه نویسنده مجاز نیست.

در صورت تمایل به استفاده از این پروژه در پروژه‌های خود، لطفاً به این ریپازیتوری به عنوان مرجع ارجاع دهید.

## ⭐ حمایت از پروژه

اگر این پروژه برایتان مفید بود، با زدن **⭐ Star** در بالای صفحه از آن حمایت کنید. این کار باعث دیده‌شدن بیشتر پروژه و انگیزه برای توسعه ویژگی‌های جدید می‌شود.

---

ساخته شده با ❤️ برای عاشقان شعر و ادبیات فارسی