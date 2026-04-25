import re


def contains_english_keyword(text_lower: str, keyword: str) -> bool:
    escaped = re.escape(keyword.lower())
    pattern = rf"(?<![a-z0-9_]){escaped}(?![a-z0-9_])"
    return bool(re.search(pattern, text_lower))


def contains_khmer_keyword(text: str, keyword: str) -> bool:
    return keyword in text


def has_shy_trigger(text: str) -> bool:
    low = text.lower()
    en_trigger_words = [
        "pretty",
        "cute",
        "beautiful",
        "hot",
        "i like you",
        "i love you",
        "love you",
        "miss you",
        "date",
        "kiss",
        "adorable",
        "sweet girl",
        "good girl",
        "love",
    ]
    kh_trigger_words = ["ស្អាត", "គួរឱ្យស្រឡាញ់", "ស្រឡាញ់", "ស្រលាញ់", "ចូលចិត្ត", "ណាត់", "ថើប", "ស្វីត", "ញ៉ោះ"]
    return any(contains_english_keyword(low, w) for w in en_trigger_words) or any(
        contains_khmer_keyword(text, w) for w in kh_trigger_words
    )


def has_sulky_trigger(text: str) -> bool:
    low = text.lower()
    en_trigger_words = [
        "where were you",
        "why no reply",
        "why didnt you reply",
        "ignore me",
        "late reply",
        "tease",
        "just kidding",
        "you jealous",
    ]
    kh_trigger_words = ["បាត់ទៅណា", "ហេតុអីមិនឆ្លើយ", "មិនឆ្លើយ", "ឌឺ", "ញ៉ោះ", "ងរ", "មិនខ្វល់"]
    return any(contains_english_keyword(low, w) for w in en_trigger_words) or any(
        contains_khmer_keyword(text, w) for w in kh_trigger_words
    )


def has_angry_trigger(text: str) -> bool:
    low = text.lower()
    en_trigger_words = ["stupid", "idiot", "dumb", "shut up", "bitch", "hate you", "fuck you", "f u"]
    kh_trigger_words = ["ល្ងង់", "ឆ្កួត", "អាក្រក់", "ស្អប់", "មាត់អាក្រក់", "បិទមាត់", "ជេរ"]
    return any(contains_english_keyword(low, w) for w in en_trigger_words) or any(
        contains_khmer_keyword(text, w) for w in kh_trigger_words
    )


def has_snack_bribe(text: str) -> bool:
    low = text.lower()
    if any(w in text for w in ["🍭", "🍰", "🍦", "🍫", "🧋"]):
        return True
    en_words = ["candy", "cake", "ice cream", "snack"]
    kh_words = ["នំ", "ស្ករគ្រាប់", "បង្អែម"]
    return any(contains_english_keyword(low, w) for w in en_words) or any(contains_khmer_keyword(text, w) for w in kh_words)


def has_neari_call(user_text: str) -> bool:
    low = user_text.lower()
    return bool(re.search(r"(?<![a-z0-9_])neari(?![a-z0-9_])", low)) or "នារី" in user_text

