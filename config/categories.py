"""فهرست استاندارد دسته‌بندی کانال و موضوع تبلیغ."""
from __future__ import annotations

# دسته‌بندی خود کانال (یک انتخاب)
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

# موضوع تبلیغ مشتری (اصلی + فرعی از همین فهرست جزئی‌تر)
AD_TOPICS: list[tuple[str, str]] = [
    ('clothing', 'پوشاک و مد'),
    ('beauty', 'زیبایی و آرایشی'),
    ('food', 'خوراکی و رستوران'),
    ('digital', 'کالای دیجیتال'),
    ('home', 'خانه و آشپزخانه'),
    ('education', 'آموزش و دوره'),
    ('health', 'سلامت و درمان'),
    ('finance', 'مالی و سرمایه‌گذاری'),
    ('realestate', 'ملک و املاک'),
    ('auto', 'خودرو و موتور'),
    ('travel', 'سفر و گردشگری'),
    ('entertainment', 'سرگرمی و رسانه'),
    ('kids', 'کودک و نوزاد'),
    ('pets', 'حیوانات خانگی'),
    ('services', 'خدمات شهری و محلی'),
    ('jobs', 'استخدام و کاریابی'),
    ('religious', 'مذهبی و فرهنگی'),
    ('ngo', 'خیریه و اجتماعی'),
    ('politics', 'سیاسی و خبری'),
    ('other', 'سایر'),
]


def channel_category_labels() -> dict[str, str]:
    return dict(CHANNEL_CATEGORIES)


def ad_topic_labels() -> dict[str, str]:
    return dict(AD_TOPICS)


def valid_channel_category(code: str) -> bool:
    return code in channel_category_labels()


def valid_ad_topic(code: str) -> bool:
    return code in ad_topic_labels()


def topics_blocked(channel_forbidden: list | None, primary: str, secondary: list | None) -> bool:
    """اگر موضوع اصلی یا فرعی تبلیغ در ممنوعه کانال باشد True."""
    banned = set(channel_forbidden or [])
    if not banned:
        return False
    if primary and primary in banned:
        return True
    for t in secondary or []:
        if t in banned:
            return True
    return False
