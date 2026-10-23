"""فهرست سلسله‌مراتبی دسته کانال و موضوع کسب‌وکار/ممنوعه."""
from __future__ import annotations

CHANNEL_CATEGORIES: list[tuple[str, str]] = [
    ('economic', 'اقتصادی و مالی'),
    ('education_art', 'آموزشی و هنری'),
    ('news_politics', 'خبری و سیاسی'),
    ('health', 'سلامت و پزشکی'),
    ('lifestyle', 'سبک زندگی و خانواده'),
    ('entertainment', 'سرگرمی و طنز'),
    ('science_tech', 'علمی و فناوری'),
    ('shop', 'فروشگاهی'),
    ('religious', 'مذهبی و فرهنگی'),
    ('sports', 'ورزشی'),
    ('services', 'کاربردی و خدماتی'),
    ('travel', 'گردشگری و طبیعت'),
    ('other', 'سایر'),
]

# ساختار سلسله‌مراتبی: (کد اصلی, برچسب, [(کد فرعی, برچسب), ...])
AD_TOPIC_TREE: list[tuple[str, str, list[tuple[str, str]]]] = [
    ('fashion', 'پوشاک و مد', [
        ('fashion_clothes', 'لباس'), ('fashion_shoes', 'کفش'), ('fashion_accessories', 'اکسسوری'),
    ]),
    ('beauty', 'زیبایی و آرایشی', [
        ('beauty_cosmetic', 'آرایشی'), ('beauty_skin', 'مراقبت پوست'), ('beauty_hair', 'مو'),
    ]),
    ('food', 'خوراکی و رستوران', [
        ('food_restaurant', 'رستوران'), ('food_cafe', 'کافه'), ('food_product', 'محصول غذایی'),
    ]),
    ('digital', 'کالای دیجیتال', [
        ('digital_phone', 'موبایل'), ('digital_pc', 'کامپیوتر'), ('digital_accessory', 'لوازم جانبی'),
    ]),
    ('home', 'خانه و آشپزخانه', [
        ('home_furniture', 'مبلمان'), ('home_appliance', 'لوازم خانگی'), ('home_decor', 'دکوراسیون'),
    ]),
    ('education', 'آموزش و دوره', [
        ('edu_course', 'دوره آنلاین'), ('edu_school', 'آموزشگاه'), ('edu_book', 'کتاب'),
    ]),
    ('health', 'سلامت و درمان', [
        ('health_clinic', 'خدمات درمانی'), ('health_herb', 'داروهای گیاهی'), ('health_equip', 'تجهیزات پزشکی'),
    ]),
    ('finance', 'مالی و سرمایه‌گذاری', [
        ('finance_invest', 'سرمایه‌گذاری'), ('finance_insurance', 'بیمه'), ('finance_loan', 'وام و اعتبار'),
    ]),
    ('realestate', 'ملک و املاک', [
        ('re_sale', 'خرید و فروش'), ('re_rent', 'اجاره'), ('re_agency', 'مشاوره املاک'),
    ]),
    ('auto', 'خودرو و موتور', [
        ('auto_car', 'خودرو'), ('auto_motor', 'موتور'), ('auto_parts', 'قطعات'),
    ]),
    ('travel', 'سفر و گردشگری', [
        ('travel_tour', 'تور'), ('travel_hotel', 'اقامت'), ('travel_ticket', 'بلیط'),
    ]),
    ('entertainment', 'سرگرمی و رسانه', [
        ('ent_media', 'رسانه'), ('ent_game', 'بازی'), ('ent_event', 'رویداد'),
    ]),
    ('kids', 'کودک و نوزاد', [
        ('kids_product', 'محصول کودک'), ('kids_edu', 'آموزش کودک'),
    ]),
    ('services', 'خدمات شهری و محلی', [
        ('svc_repair', 'تعمیرات'), ('svc_cleaning', 'نظافت'), ('svc_other', 'سایر خدمات'),
    ]),
    ('jobs', 'استخدام و کاریابی', [
        ('jobs_hire', 'استخدام'), ('jobs_freelance', 'فریلنس'),
    ]),
    ('religious', 'مذهبی و فرهنگی', [
        ('rel_content', 'محتوای مذهبی'), ('rel_event', 'مراسم'),
    ]),
    ('other', 'سایر', [
        ('other_misc', 'متفرقه'),
    ]),
]

# سازگاری عقب‌رو: فهرست تخت
AD_TOPICS: list[tuple[str, str]] = []
for code, label, subs in AD_TOPIC_TREE:
    AD_TOPICS.append((code, label))
    for sc, sl in subs:
        AD_TOPICS.append((sc, sl))

FORBIDDEN_TOPIC_CODES = {c for c, _ in AD_TOPICS}


def topic_label(code: str) -> str:
    for c, l in AD_TOPICS:
        if c == code:
            return l
    return code


def flatten_selected(primary: list[str] | str, secondary: list[str] | None = None) -> set[str]:
    """فقط کدهای انتخاب‌شدهٔ مشتری (بدون بسط خودکار زیر‌دسته)."""
    out: set[str] = set()
    if isinstance(primary, str) and primary:
        out.add(primary)
    elif isinstance(primary, (list, tuple)):
        out.update(str(x) for x in primary if x)
    if secondary:
        out.update(str(x) for x in secondary if x)
    return out
