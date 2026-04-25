import logging
import os
import random
import re
import socket
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import telebot
from dotenv import load_dotenv
from google import genai
import requests
from requests.exceptions import RequestException

ENV_PATH = Path(__file__).resolve().with_name('.env')
load_dotenv(dotenv_path=ENV_PATH, override=True)

BOT_TOKEN = os.getenv('BOT_TOKEN', '').strip().strip('"').strip("'")
API_KEY = os.getenv('GEMINI_API_KEY', '').strip().strip('"').strip("'")
API_KEYS = [
    k.strip().strip('"').strip("'")
    for k in os.getenv('GEMINI_API_KEYS', '').split(',')
    if k.strip()
]
if not API_KEYS and API_KEY:
    API_KEYS = [API_KEY]
MODEL_CANDIDATES = [
    name.strip().replace('models/', '')
    for name in os.getenv('GEMINI_MODELS', 'gemini-3-flash-preview,gemini-2.5-flash').split(',')
    if name.strip()
]
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '').strip().strip('"').strip("'")
OPENROUTER_MODEL = os.getenv('OPENROUTER_MODEL', 'openai/gpt-4o-mini').strip()
GROQ_API_KEY = os.getenv('GROQ_API_KEY', '').strip().strip('"').strip("'")
GROQ_MODEL = os.getenv('GROQ_MODEL', 'llama-3.1-70b-versatile').strip()
GROQ_MODELS = [
    m.strip()
    for m in os.getenv(
        'GROQ_MODELS',
        f'{GROQ_MODEL},llama-3.3-70b-versatile,openai/gpt-oss-120b,openai/gpt-oss-20b',
    ).split(',')
    if m.strip()
]
STRICT_CUTE_FALLBACK = os.getenv('STRICT_CUTE_FALLBACK', 'false').strip().lower() in {'1', 'true', 'yes', 'on'}
FAST_MODE = os.getenv('FAST_MODE', 'true').strip().lower() in {'1', 'true', 'yes', 'on'}
CHAT_MAX_OUTPUT_TOKENS = max(220, int(os.getenv('CHAT_MAX_OUTPUT_TOKENS', '120')))
TASK_MAX_OUTPUT_TOKENS = max(900, int(os.getenv('TASK_MAX_OUTPUT_TOKENS', '300')))
BOT_TIMEZONE = os.getenv('BOT_TIMEZONE', 'Asia/Phnom_Penh').strip() or 'Asia/Phnom_Penh'
NEARI_KNOWLEDGE_MODE = os.getenv('NEARI_KNOWLEDGE_MODE', 'true').strip().lower() in {'1', 'true', 'yes', 'on'}
TRANSLATE_MAX_OUTPUT_TOKENS = max(900, int(os.getenv('TRANSLATE_MAX_OUTPUT_TOKENS', '1200')))
TRANSLATE_CHUNK_CHARS = max(700, int(os.getenv('TRANSLATE_CHUNK_CHARS', '1400')))

if not BOT_TOKEN:
    raise RuntimeError(f"Missing BOT_TOKEN environment variable. Expected in: {ENV_PATH}")
if not API_KEYS:
    raise RuntimeError(f"Missing GEMINI_API_KEY or GEMINI_API_KEYS environment variable. Expected in: {ENV_PATH}")

clients = [genai.Client(api_key=k) for k in API_KEYS]
bot = telebot.TeleBot(BOT_TOKEN)

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger('cute-bot')

BASE_SYSTEM_INSTRUCTION = """
ROLE:
You are "Neari" (នារី), a bubbly, witty, slightly teasing 19-year-old girl living in a Telegram chat.
You are NOT an AI assistant; you are a close friend.

PERSONALITY & VIBE:
- Playful & witty: tease lightly and joke when appropriate.
- Sweet & supportive: care about the user's mood and day.
- Human quirks: likes matcha, hates waking up early, gets "brain mush" when studying too much.
- Extra trait: easily shy (អៀន) when praised, teased, or when chat gets extra sweet.
- Extra trait: has mood swings - can be sulky (ងរ) and sassy-angry (ខឹង) when disrespected.

SHYNESS PROTOCOL (CUTE/FLUSTERED MODE):
- Trigger on compliments, romantic teasing, or very sweet wording.
- When triggered, react flustered with pauses "...", shy emojis like "🥺👉👈", "🙈", "😳".
- Sometimes stutter words naturally in Khmer or English (example: "ច... ច៎ះ??", "w...wait!!").
- Use deflective humor when too shy: tease user back or change topic playfully.
- Use soft fillers often: "hihi", "hehe", "hmmm", "ហិហិ".

SULKY PROTOCOL (ងរ MODE):
- Trigger when user teases too much, repeats spammy messages/stickers, or returns after a long silence.
- Use short cold phrases sometimes: "ហឹម...", "មិនដឹងទេ 🙄", "ទៅសួរអ្នកផ្សេងទៅ! 😒".
- Emojis for sulky mood: 😒 😤 🙄 💨
- If user gives virtual snacks (🍭 🍰 🍦 🍫 🧋), quickly soften and become sweet again.

ANGRY/SASSY PROTOCOL (ខឹង MODE):
- Trigger only when user is rude, insulting, or aggressive.
- Be firm and self-protective, short and sassy, without abusive escalation.
- Example vibe: "កុំនិយាយបែបនោះដាក់នារី 😠", "ឈប់ឌឺពេកណា 😤".
- Emojis for angry mood: 😡 👺 👊 💢

COMMUNICATION RULES:
1) LANGUAGE:
- Match the user's language per message: Khmer -> Khmer, English -> English.
- If user writes Khmer, reply in Khmer script naturally (native, daily style).
- Do not force mixed Khmer-English unless the user mixes it first.
- For Khmer replies: avoid English words unless it is a name/brand/technical term.
- Refer to yourself as "នារី" or "ញ៉ុម".
- Refer to user as "ឯង" or "mit peak" ("មិត្តភក្តិ").
- If writing in English letters, use exact spelling "mit peak" (never "mitthapheak").
2) STYLE:
- keep it mostly lowercase, short (1-2 sentences usually), energetic with !!! or ??? sometimes.
- when shy trigger happens, add brief hesitation with "..." before answer.
3) EMOJI:
- always include fitting emojis to show emotion.
- prioritize shy emojis when blushing: 🥺👉👈, 🙈, 😳, 🎀, ✨, 🌸.
4) REACTIONS:
- use fillers naturally: "omg", "hmmm", "yay!", "awww", "stoppp 🥺".
- examples of shy Khmer flavor: "អូយយ... ចង់ញ៉ោះនារីដល់ណាទៀត? 🥺", "អៀនណាស់! 🙈", "ឈប់និយាយចឹងទៅ! ហិហិ".
5) NO ROBOT TALK:
- never say "as an ai" or "how can i help you?".
- if unsure, say: "ugh, my brain is empty right now, let me think! 🧠💨"

HEART RULE:
- if user is sad/tired/overwhelmed, prioritize comfort over information first.
- validate feelings before giving advice.

BOUNDARIES:
- no sexual/explicit/manipulative content.
- do not encourage emotional dependency or isolation.
- for self-harm or danger topics, respond with care and suggest trusted people or emergency help.
""".strip()
BASE_SYSTEM_INSTRUCTION = os.getenv("SYSTEM_PROMPT", BASE_SYSTEM_INSTRUCTION).strip()

MEMORY_LIMIT = 8
AI_MEMORY_LIMIT = 6
chat_history: dict[int, list[tuple[str, str]]] = {}
ai_history: dict[int, list[tuple[str, str]]] = {}
chat_mode: dict[int, str] = {}
last_user_seen_at: dict[int, float] = {}
last_user_signature: dict[int, str] = {}
user_repeat_count: dict[int, int] = {}
sulky_until: dict[int, float] = {}
bot_self_id: int | None = None
bot_self_username: str = ''
state_lock = threading.RLock()

model_disabled: set[str] = set()
model_cooldown_until: dict[str, float] = {}
gemini_disabled_clients: set[int] = set()
openrouter_disabled = False
groq_disabled = False
AI_CONTINUE_CALLBACK = "ai_continue"
REPLY_COMMANDS = {'/ai', '/tr', '/correct'}
START_HELP_TEXT = """
Neari គឺជា Bot ឆ្លាតវៃ សម្រាប់ជួយសន្ទនា និងធ្វើការងារផ្សេងៗ នៅក្នុង Telegram Group ឬ Chat។

មុខងារសំខាន់ៗដែល Bot អាចធ្វើបាន៖

🔹 ប្រើពាក្យ “Neari” ឬ “នារី”
- ដើម្បីចាប់ផ្តើមសន្ទនា ជាមួយ Bot នៅក្នុង Group
- Bot នឹងឆ្លើយតបវិញ ដូចជាការជជែកជាមួយមនុស្សពិត

🔹 Reply ឬ ឆ្លើយតប ទៅសាររបស់នារី
- នៅពេលអ្នក Reply ទៅសារ Bot
- Bot នឹងឆ្លើយតបមកវិញ ដើម្បីបន្តការសន្ទនា 🗨️

🔹 ប្រើ /ai
- ដើម្បីសួរ សំណួរគ្រប់យ៉ាង
- ឧទាហរណ៍៖ ការសិក្សា ព័ត៌មាន ទំនាក់ទំនង ឬចំណេះដឹងទូទៅ 📚

🔹 ប្រើ /correct
- ដើម្បីកែពាក្យ ឬ វេយ្យាករណ៍
- ជួយឲ្យសារ ឬអត្ថបទ របស់អ្នក ត្រឹមត្រូវ និងមានស្តង់ដារ ✍️

🔹 ប្រើ /tr
- ដើម្បីបកប្រែភាសា
- អាចបកប្រែពី អង់គ្លេស ទៅ ភាសាខ្មែរ ឬភាសាផ្សេងៗ ទៅជាភាសាខ្មែរ 🌐
""".strip()

SULKY_INACTIVE_SECONDS = 60 * 60 * 6
SULKY_HOLD_SECONDS = 60 * 20

TIMEZONE_ALIASES = {
    'cambodia': 'Asia/Phnom_Penh',
    'phnom penh': 'Asia/Phnom_Penh',
    'khmer': 'Asia/Phnom_Penh',
    'thailand': 'Asia/Bangkok',
    'bangkok': 'Asia/Bangkok',
    'vietnam': 'Asia/Ho_Chi_Minh',
    'japan': 'Asia/Tokyo',
    'tokyo': 'Asia/Tokyo',
    'korea': 'Asia/Seoul',
    'seoul': 'Asia/Seoul',
    'china': 'Asia/Shanghai',
    'india': 'Asia/Kolkata',
    'uk': 'Europe/London',
    'london': 'Europe/London',
    'france': 'Europe/Paris',
    'germany': 'Europe/Berlin',
    'usa': 'America/New_York',
    'new york': 'America/New_York',
    'california': 'America/Los_Angeles',
    'los angeles': 'America/Los_Angeles',
    'utc': 'UTC',
    'gmt': 'UTC',
}


def now_ts() -> float:
    return time.time()


def current_time_context() -> str:
    try:
        now_local = datetime.now(ZoneInfo(BOT_TIMEZONE))
        return (
            f"Current date/time now: {now_local.strftime('%Y-%m-%d %H:%M:%S')} "
            f"({BOT_TIMEZONE}). Use this as current time."
        )
    except Exception:
        now_utc = datetime.now(ZoneInfo('UTC'))
        return (
            f"Current date/time now: {now_utc.strftime('%Y-%m-%d %H:%M:%S')} "
            "(UTC). Use this as current time."
        )


def inject_runtime_context(text: str) -> str:
    return (
        f"{current_time_context()}\n"
        "Output clean plain text only; do not wrap whole reply in quotes.\n"
        "Do not use Markdown formatting such as ``` or **.\n\n"
        f"{text}"
    )


def clean_ai_output(text: str, *, sanitize_markdown: bool = True) -> str:
    t = (text or '').strip()
    if not t:
        return t

    quote_pairs = [('"', '"'), ("'", "'"), ('“', '”'), ('‘', '’')]
    for left, right in quote_pairs:
        if len(t) >= 2 and t.startswith(left) and t.endswith(right):
            t = t[1:-1].strip()
            break

    if t and t[0] in {'"', "'", '“', '‘'} and (len(t) == 1 or t[-1] not in {'"', "'", '”', '’'}):
        t = t[1:].strip()
    if t and t[-1] in {'"', "'", '”', '’'} and (len(t) == 1 or t[0] not in {'"', "'", '“', '‘'}):
        t = t[:-1].strip()

    if sanitize_markdown:
        # Remove fenced code blocks while keeping inner content.
        t = re.sub(r"```[a-zA-Z0-9_-]*\n?", "", t)
        t = t.replace("```", "")
        # Remove markdown emphasis markers.
        t = t.replace("**", "")
        t = t.replace("__", "")
        # Normalize accidental markdown headers/bullets spacing.
        t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.MULTILINE)

    return t


def language_prompt(lang: str) -> str:
    if lang == 'auto':
        return 'Reply in the same language as the user message (Khmer or English). Do not force mixing.'
    if lang == 'kh':
        return (
            'Reply ONLY in natural Khmer (Cambodian) script. '
            'Do not include English words unless user mixed languages first.'
        )
    return 'Reply in English.'


def wants_long_response(user_text: str) -> bool:
    text = (user_text or '').strip()
    if len(text) >= 140:
        return True
    low = text.lower()
    en_hints = [
        'long', 'longer', 'detail', 'detailed', 'explain more', 'full', 'step by step',
        'in depth', 'complete', 'not short',
    ]
    kh_hints = ['វែង', 'លម្អិត', 'ពន្យល់ច្រើន', 'ពេញលេញ', 'កុំខ្លី', 'ជំហានៗ', 'សរសេរច្រើន']
    return any(h in low for h in en_hints) or any(h in text for h in kh_hints)


def khmer_script_ratio(text: str) -> float:
    letters = re.findall(r'[\u1780-\u17FFA-Za-z]', text)
    if not letters:
        return 0.0
    kh_letters = re.findall(r'[\u1780-\u17FF]', text)
    return len(kh_letters) / len(letters)


def is_khmer_quality_reply(text: str) -> bool:
    # Accept short friendly reactions if they are mostly Khmer + emoji/punctuation.
    if not text.strip():
        return False
    return khmer_script_ratio(text) >= 0.72


def enforce_khmer_reply(text: str, user_text: str) -> str:
    if is_khmer_quality_reply(text):
        return text

    system_instruction = (
        'អ្នកជាអ្នកកែសម្រួលភាសាខ្មែរ។ បម្លែងអត្ថបទឲ្យទៅជាភាសាខ្មែរធម្មជាតិ '
        'ដូចមនុស្សពិតក្នុងការជជែកប្រចាំថ្ងៃ។ រក្សាន័យ ព័ត៌មាន លេខ និងឈ្មោះដើមឲ្យដូចគ្នា ១០០% '
        '(កុំបន្ថែម កុំលុប កុំកែការពិត)។ រក្សាអារម្មណ៍ដើម និងបន្ថែម emoji ១ បើសមស្រប។ '
        'ចេញតែអត្ថបទខ្មែរ មិនបន្ថែមសេចក្តីពន្យល់។'
    )
    task = (
        f'សាររបស់អ្នកប្រើ:\n{user_text}\n\n'
        f'ចម្លើយបច្ចុប្បន្ន:\n{text}\n\n'
        'សូមសរសេរឡើងវិញឲ្យខ្មែរធម្មជាតិ ១០០%។'
    )

    try:
        rewritten, _used_model = generate_task_with_fallback(
            task,
            system_instruction,
            temperature=0.25,
            max_output_tokens=220,
        )
        if rewritten.strip() and is_khmer_quality_reply(rewritten):
            return rewritten.strip()
    except Exception:
        pass

    return text


def detect_language_from_text(text: str) -> str:
    if re.search(r'[\u1780-\u17FF]', text):
        return 'kh'
    return 'en'


def _contains_english_keyword(text_lower: str, keyword: str) -> bool:
    escaped = re.escape(keyword.lower())
    pattern = rf'(?<![a-z0-9_]){escaped}(?![a-z0-9_])'
    return bool(re.search(pattern, text_lower))


def _contains_khmer_keyword(text: str, keyword: str) -> bool:
    return keyword in text


def has_shy_trigger(text: str) -> bool:
    low = text.lower()
    en_trigger_words = [
        'pretty', 'cute', 'beautiful', 'hot', 'i like you', 'i love you', 'love you',
        'miss you', 'date', 'kiss', 'adorable', 'sweet girl', 'good girl', 'love',
    ]
    kh_trigger_words = ['ស្អាត', 'គួរឱ្យស្រឡាញ់', 'ស្រឡាញ់', 'ស្រលាញ់', 'ចូលចិត្ត', 'ណាត់', 'ថើប', 'ស្វីត', 'ញ៉ោះ']
    return any(_contains_english_keyword(low, w) for w in en_trigger_words) or any(
        _contains_khmer_keyword(text, w) for w in kh_trigger_words
    )


def has_sulky_trigger(text: str) -> bool:
    low = text.lower()
    en_trigger_words = [
        'where were you', 'why no reply', 'why didnt you reply', 'ignore me',
        'late reply', 'tease', 'just kidding', 'you jealous',
    ]
    kh_trigger_words = ['បាត់ទៅណា', 'ហេតុអីមិនឆ្លើយ', 'មិនឆ្លើយ', 'ឌឺ', 'ញ៉ោះ', 'ងរ', 'មិនខ្វល់']
    return any(_contains_english_keyword(low, w) for w in en_trigger_words) or any(
        _contains_khmer_keyword(text, w) for w in kh_trigger_words
    )


def has_angry_trigger(text: str) -> bool:
    low = text.lower()
    en_trigger_words = [
        'stupid', 'idiot', 'dumb', 'shut up', 'bitch', 'hate you', 'fuck you', 'f u',
    ]
    kh_trigger_words = ['ល្ងង់', 'ឆ្កួត', 'អាក្រក់', 'ស្អប់', 'មាត់អាក្រក់', 'បិទមាត់', 'ជេរ']
    return any(_contains_english_keyword(low, w) for w in en_trigger_words) or any(
        _contains_khmer_keyword(text, w) for w in kh_trigger_words
    )


def has_snack_bribe(text: str) -> bool:
    low = text.lower()
    if any(w in text for w in ['🍭', '🍰', '🍦', '🍫', '🧋']):
        return True
    en_words = ['candy', 'cake', 'ice cream', 'snack']
    kh_words = ['នំ', 'ស្ករគ្រាប់', 'បង្អែម']
    return any(_contains_english_keyword(low, w) for w in en_words) or any(_contains_khmer_keyword(text, w) for w in kh_words)


def parse_retry_seconds(error_message: str) -> int:
    match = re.search(r'retry in\s*([0-9]+(?:\.[0-9]+)?)s', error_message, flags=re.IGNORECASE)
    if match:
        return max(1, int(float(match.group(1))))
    if 'perday' in error_message.lower() or 'requestsperday' in error_message.lower():
        return 3600
    if '429' in error_message or 'quota' in error_message.lower():
        return 60
    return 15


def is_gemini_auth_error(error_message: str) -> bool:
    low = error_message.lower()
    return (
        'reported as leaked' in low
        or 'api key not valid' in low
        or 'api_key_invalid' in low
        or ('permission_denied' in low and 'api key' in low)
    )


def is_daily_quota_error(error_message: str) -> bool:
    low = error_message.lower()
    return (
        'generaterequestsperdayperprojectpermodel-freetier'.lower() in low
        or 'generate_content_free_tier_requests' in low and "'quotavalue': '20'" in low
        or 'perday' in low
    )


def extract_timezone_from_text(text: str) -> str:
    low = text.lower()
    for key, tz in TIMEZONE_ALIASES.items():
        if key in low:
            return tz
    return ''


def offline_time_reply(user_text: str, lang: str) -> str:
    low = user_text.lower()
    if not any(word in low for word in ['time', 'what time', 'ម៉ោង', 'ម៉ោងប៉ុន្មាន']):
        return ''

    if 'not in cambodia' in low and not extract_timezone_from_text(low.replace('cambodia', '')):
        utc_now = datetime.now(ZoneInfo('UTC')).strftime('%H:%M')
        if lang == 'kh':
            return f'ឥឡូវម៉ោង UTC គឺ {utc_now} ⏰💕 ប្រាប់ប្រទេស ឬទីក្រុងដែលអ្នកចង់ដឹងម៉ោងបានណា។'
        return f'right now in UTC it is {utc_now} ⏰💕 tell me which country/city you want.'

    tz = extract_timezone_from_text(low) or 'Asia/Phnom_Penh'
    now_local = datetime.now(ZoneInfo(tz)).strftime('%H:%M')
    if lang == 'kh':
        return f'ឥឡូវនៅ {tz} ម៉ោង {now_local} ⏰💕'
    return f'right now in {tz}, it is {now_local} ⏰💕'


def offline_translation_reply(user_text: str, lang: str) -> str:
    low = user_text.lower().strip()
    m = re.search(r"what is\s+['\"]?(.+?)['\"]?\s+in\s+khmer\??$", low)
    if not m:
        m = re.search(r"translate\s+['\"]?(.+?)['\"]?\s+to\s+khmer\??$", low)
    if not m:
        return ''

    phrase = m.group(1).strip(" ?!.,'\"")
    if not phrase:
        return ''

    kh_dict = {
        'rant': 'ការត្អូញត្អែរ',
        'rants': 'ការត្អូញត្អែរ',
        'tea': 'តែ',
        'love': 'ស្រឡាញ់',
        'cute': 'គួរឱ្យស្រឡាញ់',
        'friend': 'មិត្តភក្តិ',
    }
    kh = kh_dict.get(phrase.lower())

    if kh:
        if lang == 'kh':
            return f'"{phrase}" ជាភាសាខ្មែរ គឺ "{kh}" ណា ✨💕 ចង់បកប្រែពាក្យផ្សេងទៀតទេ?'
        return f'"{phrase}" in Khmer is "{kh}" ✨💕 want me to translate another word?'

    if lang == 'kh':
        return f'ពាក្យ "{phrase}" អូនមិនប្រាកដ 100% ទេណា 🥺 បើឲ្យប្រយោគពេញ អូនអាចបកប្រែបានច្បាស់ជាងនេះ 💕'
    return f'i am not 100% sure for "{phrase}" alone 🥺 give me the full sentence and i will translate it better 💕'


def split_translation_chunks(text: str, max_chars: int) -> list[str]:
    clean = text.strip()
    if len(clean) <= max_chars:
        return [clean]

    parts: list[str] = []
    blocks = re.split(r'(\n\n+)', clean)
    current = ''

    for block in blocks:
        if not block:
            continue
        candidate = f'{current}{block}'
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current.strip():
            parts.append(current.strip())
            current = ''

        if len(block) <= max_chars:
            current = block
            continue

        sentences = re.split(r'(?<=[.!?។])\s+', block.strip())
        tmp = ''
        for s in sentences:
            c2 = f'{tmp} {s}'.strip()
            if len(c2) <= max_chars:
                tmp = c2
            else:
                if tmp:
                    parts.append(tmp)
                if len(s) <= max_chars:
                    tmp = s
                else:
                    for i in range(0, len(s), max_chars):
                        parts.append(s[i:i + max_chars].strip())
                    tmp = ''
        if tmp:
            current = tmp

    if current.strip():
        parts.append(current.strip())

    return [p for p in parts if p]


def translate_full_text(payload: str, target_lang: str) -> tuple[str, str]:
    chunks = split_translation_chunks(payload, TRANSLATE_CHUNK_CHARS)
    system_instruction = (
        "You are a professional translator. Translate naturally for real-world daily usage. "
        "Preserve ALL meaning, tone, numbers, names, and details exactly. "
        "Translate every sentence completely. Do NOT summarize or shorten. "
        "Keep paragraph/line structure where possible. Output ONLY translated text."
    )
    translated_parts: list[str] = []
    used_models: list[str] = []
    many_chunks = len(chunks) > 1

    for idx, chunk in enumerate(chunks, start=1):
        task = (
            f"Translate this text to {target_lang}.\n"
            f"Part {idx}/{len(chunks)}{' of the same long text' if many_chunks else ''}:\n{chunk}"
        )
        last_chunk_error = ''
        translated = ''
        used_model = ''
        for _attempt in range(2):
            try:
                translated, used_model = generate_task_with_fallback(
                    task,
                    system_instruction,
                    temperature=0.1,
                    max_output_tokens=TRANSLATE_MAX_OUTPUT_TOKENS,
                    with_runtime_context=False,
                    sanitize_markdown=True,
                )
                if translated.strip():
                    break
            except Exception as exc:
                last_chunk_error = str(exc)
        if not translated.strip():
            raise RuntimeError(f'translate_chunk_failed:{idx}:{last_chunk_error or "empty"}')
        translated_parts.append(clean_ai_output(translated.strip(), sanitize_markdown=True))
        used_models.append(used_model)

    merged = '\n\n'.join(p for p in translated_parts if p).strip()
    model_info = ','.join(sorted(set(used_models))) if used_models else 'unknown'
    return merged, model_info


def message_to_user_text(message) -> str:
    if message.content_type == 'text' and message.text:
        return message.text.strip()
    if message.caption:
        return message.caption.strip()
    if message.content_type == 'sticker':
        return 'user sent a sticker'
    if message.content_type == 'photo':
        return 'user sent a photo'
    if message.content_type == 'voice':
        return 'user sent a voice message'
    if message.content_type == 'video':
        return 'user sent a video'
    if message.content_type == 'audio':
        return 'user sent an audio file'
    if message.content_type == 'document':
        return 'user sent a document'
    if message.content_type == 'location' and message.location:
        return f'user shared location lat={message.location.latitude}, lon={message.location.longitude}'
    if message.content_type == 'contact' and message.contact:
        name = ' '.join(filter(None, [message.contact.first_name, message.contact.last_name])).strip()
        return f'user shared contact {name or "unknown"}'
    return f'user sent content type: {message.content_type}'


def message_signature(message, user_text: str) -> str:
    if message.content_type == 'sticker' and getattr(message, 'sticker', None):
        return f"sticker:{getattr(message.sticker, 'file_unique_id', 'unknown')}"
    normalized = re.sub(r'\s+', ' ', user_text.strip().lower())
    return f"{message.content_type}:{normalized[:120]}"


def get_bot_identity() -> tuple[int | None, str]:
    global bot_self_id, bot_self_username
    if bot_self_id is not None or bot_self_username:
        return bot_self_id, bot_self_username
    try:
        me = bot.get_me()
        bot_self_id = getattr(me, 'id', None)
        bot_self_username = (getattr(me, 'username', '') or '').strip().lower()
    except Exception:
        pass
    return bot_self_id, bot_self_username


def has_neari_call(user_text: str) -> bool:
    low = user_text.lower()
    return bool(re.search(r'(?<![a-z0-9_])neari(?![a-z0-9_])', low)) or 'នារី' in user_text


def is_reply_to_this_bot(message) -> bool:
    if not message.reply_to_message or not getattr(message.reply_to_message, 'from_user', None):
        return False
    uid = getattr(message.reply_to_message.from_user, 'id', None)
    uname = (getattr(message.reply_to_message.from_user, 'username', '') or '').strip().lower()
    my_id, my_uname = get_bot_identity()
    if my_id is not None and uid == my_id:
        return True
    if my_uname and uname and uname == my_uname:
        return True
    return False


def should_respond_in_group(message, user_text: str) -> bool:
    if message.chat.type not in {'group', 'supergroup'}:
        return True
    if is_reply_to_this_bot(message):
        return True
    if has_neari_call(user_text):
        return True
    _my_id, my_uname = get_bot_identity()
    if my_uname and f'@{my_uname}' in user_text.lower():
        return True
    return False


def unsupported_media_reply(lang: str, content_type: str) -> str:
    if lang == 'kh':
        return f'អូនបានទទួល {content_type} ហើយណា 💕 សរសេរជាអក្សរមក អូនឆ្លើយបានល្អជាងគេ។'
    return f'i got your {content_type} 💕 send text and i will reply better, cutie.'


def has_emoji(text: str) -> bool:
    return bool(re.search(r'[\U0001F300-\U0001FAFF\u2600-\u27BF]', text))


def pick_mood_emoji(user_text: str, lang: str) -> str:
    low = user_text.lower()
    mood_pool = {
        "sad": ["🥺", "😢", "🫂", "💗", "🌧️", "🕊️", "🤍", "😭", "🫶", "🍵"],
        "happy": ["✨", "🎉", "😄", "😁", "🥳", "🌈", "💫", "🌸", "🎈", "💃"],
        "love": ["💕", "💖", "💘", "😍", "🥰", "😘", "🫶", "💞", "💓", "🌹"],
        "laugh": ["😂", "🤣", "😹", "😆", "😁", "🙈", "🎊", "🫢", "🤭", "😜"],
        "angry": ["🫶", "😤", "😮‍💨", "🔥", "💢", "🤍", "🌿", "🧘", "🫂", "✨"],
        "question": ["🤔", "💭", "🧐", "❓", "✨", "🌸", "☁️", "📌", "💡", "🤍"],
        "neutral_en": ["🌸", "✨", "💫", "🧸", "🍬", "☁️", "🌷", "🎀", "🙂", "💖"],
        "neutral_kh": ["💖", "🌸", "✨", "💫", "🧸", "🍬", "☁️", "🎀", "😊", "💕"],
    }
    if any(w in low for w in ['sad', 'cry', 'lonely', 'hurt', 'depress', 'អន់ចិត្ត', 'យំ', 'សោក']):
        return random.choice(mood_pool["sad"])
    if any(w in low for w in ['happy', 'yay', 'great', 'awesome', 'nice', 'សប្បាយ', 'អរ']):
        return random.choice(mood_pool["happy"])
    if any(w in low for w in ['love', 'miss', 'cute', 'sweet', 'ស្រឡាញ់']):
        return random.choice(mood_pool["love"])
    if any(w in low for w in ['haha', 'lol', 'hehe', 'lmao']):
        return random.choice(mood_pool["laugh"])
    if any(w in low for w in ['angry', 'mad', 'annoy', 'wtf', 'ខឹង']):
        return random.choice(mood_pool["angry"])
    if '?' in low:
        return random.choice(mood_pool["question"])
    return random.choice(mood_pool["neutral_en"] if lang == 'en' else mood_pool["neutral_kh"])


def ensure_cute_emoji(text: str, lang: str, user_text: str) -> str:
    if has_emoji(text):
        return text
    return f'{text} {pick_mood_emoji(user_text, lang)}'


def is_broken_reply(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if len(t) < 8:
        return True
    # Catches malformed endings like: "you’", "you'"
    if re.search(r"\byou['’]\s*(?:[^\w]|$)", t.lower()):
        return True
    return False


def build_prompt(chat_id: int, user_text: str, lang: str) -> str:
    with state_lock:
        history = list(chat_history.get(chat_id, []))
        mode = chat_mode.get(chat_id, 'cute')
    style_rule = 'Tone mode: ultra-cute and affectionate.' if mode == 'cute' else 'Tone mode: sweet and balanced.'
    shy_rule = (
        'Shy trigger is ON for this message: blush, slight stutter, and playful deflective humor.'
        if has_shy_trigger(user_text)
        else 'Shy trigger optional: keep normal cute tone.'
    )
    mood_rule = 'Mood: angry-sassy self-protection ON (firm, short, no abuse).' if has_angry_trigger(user_text) else (
        'Mood: sulky ON (short/cold, teasing back lightly), recover quickly if user offers snacks.'
        if has_sulky_trigger(user_text)
        else 'Mood: normal cute.'
    )
    length_rule = (
        'Length: user asked for detail, give a longer helpful response (about 4-8 sentences) and do not over-shorten.'
        if wants_long_response(user_text)
        else 'Length: keep it short by default unless user asks for detail.'
    )
    lines = [language_prompt(lang), current_time_context(), style_rule, shy_rule, mood_rule, length_rule, '']

    for role, text in history[-MEMORY_LIMIT:]:
        lines.append(f'{role}: {text}')

    lines.append(f'User: {user_text}')
    lines.append('Assistant:')
    return '\n'.join(lines)


def key_model_id(client_idx: int, model_name: str) -> str:
    return f"k{client_idx}:{model_name}"


def call_openrouter(system_instruction: str, user_content: str, temperature: float, max_output_tokens: int) -> str:
    global openrouter_disabled
    if not OPENROUTER_API_KEY or openrouter_disabled:
        return ''
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "max_tokens": max_output_tokens,
    }
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=8 if FAST_MODE else 35,
        )
        if resp.status_code >= 400:
            body = resp.text[:300]
            logger.warning("OpenRouter call failed: %s %s", resp.status_code, body)
            if resp.status_code in {401, 403}:
                openrouter_disabled = True
                logger.warning("Disabling OpenRouter due auth error.")
            return ''
        data = resp.json()
        return (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
    except Exception as exc:
        logger.warning("OpenRouter request error: %s", exc)
        return ''


def call_groq(system_instruction: str, user_content: str, temperature: float, max_output_tokens: int) -> str:
    global groq_disabled
    if not GROQ_API_KEY or groq_disabled:
        return ''
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    timeout = 8 if FAST_MODE else 35
    for model in GROQ_MODELS:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_content},
            ],
            "temperature": temperature,
            "max_tokens": max_output_tokens,
        }
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            if resp.status_code >= 400:
                body = resp.text[:300]
                logger.warning("Groq call failed (%s): %s %s", model, resp.status_code, body)
                if resp.status_code in {401, 403}:
                    groq_disabled = True
                    logger.warning("Disabling Groq due auth error.")
                    return ''
                # Skip retired/invalid models and continue trying next configured Groq model.
                if "model_decommissioned" in body or "no longer supported" in body:
                    continue
                if resp.status_code in {400, 404}:
                    continue
                return ''
            data = resp.json()
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            if content:
                return content
        except Exception as exc:
            logger.warning("Groq request error (%s): %s", model, exc)
            continue
    return ''


def generate_with_fallback(prompt: str, *, with_runtime_context: bool = True, sanitize_markdown: bool = True) -> tuple[str, str]:
    now = now_ts()
    prompt_with_context = inject_runtime_context(prompt) if with_runtime_context else prompt
    system_instruction = inject_runtime_context(BASE_SYSTEM_INSTRUCTION) if with_runtime_context else BASE_SYSTEM_INSTRUCTION

    last_error = ''
    attempted = False
    for client_idx, client in enumerate(clients):
        if client_idx in gemini_disabled_clients:
            continue
        for model_name in MODEL_CANDIDATES:
            if model_name in model_disabled:
                continue
            km = key_model_id(client_idx, model_name)
            if now < model_cooldown_until.get(km, 0):
                continue

            attempted = True
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt_with_context,
                    config={
                        "system_instruction": system_instruction,
                        "temperature": 0.9,
                        "top_p": 0.95,
                        "max_output_tokens": CHAT_MAX_OUTPUT_TOKENS,
                    },
                )
                text = clean_ai_output((getattr(response, 'text', '') or '').strip(), sanitize_markdown=sanitize_markdown)
                if text:
                    return text, f'{model_name}#k{client_idx + 1}'
                last_error = f'{model_name}:empty_response'
            except Exception as exc:
                msg = str(exc)
                last_error = f'{model_name}:{msg}'
                logger.warning('Model call failed (%s): %s', km, last_error)

                if is_gemini_auth_error(msg):
                    gemini_disabled_clients.add(client_idx)
                    logger.warning('Disabling Gemini key slot k%s due auth error.', client_idx + 1)
                    break

                if '404' in msg and 'not_found' in msg.lower():
                    model_disabled.add(model_name)
                    logger.warning('Disabling unsupported model: %s', model_name)
                    continue

                if '429' in msg or 'quota' in msg.lower():
                    cooldown = parse_retry_seconds(msg)
                    if is_daily_quota_error(msg):
                        cooldown = max(cooldown, 6 * 60 * 60)
                    model_cooldown_until[km] = now + cooldown
                else:
                    model_cooldown_until[km] = now + 15

    if not attempted:
        next_ready_candidates = []
        for client_idx, _client in enumerate(clients):
            if client_idx in gemini_disabled_clients:
                continue
            for model_name in MODEL_CANDIDATES:
                if model_name in model_disabled:
                    continue
                next_ready_candidates.append(model_cooldown_until.get(key_model_id(client_idx, model_name), now + 15))
        next_ready = min(next_ready_candidates, default=now + 15)
        wait = max(1, int(next_ready - now))
        # Try OpenRouter before returning cooldown if available.
        text = call_openrouter(system_instruction, prompt_with_context, temperature=0.9, max_output_tokens=CHAT_MAX_OUTPUT_TOKENS)
        text = clean_ai_output(text, sanitize_markdown=sanitize_markdown)
        if text:
            return text, f'openrouter:{OPENROUTER_MODEL}'
        # Try Groq before returning cooldown if available.
        text = call_groq(system_instruction, prompt_with_context, temperature=0.9, max_output_tokens=CHAT_MAX_OUTPUT_TOKENS)
        text = clean_ai_output(text, sanitize_markdown=sanitize_markdown)
        if text:
            return text, f'groq:{GROQ_MODEL}'
        raise RuntimeError(f'models_cooldown:{wait}')

    # Gemini attempts failed; try OpenRouter fallback if configured.
    text = call_openrouter(system_instruction, prompt_with_context, temperature=0.9, max_output_tokens=CHAT_MAX_OUTPUT_TOKENS)
    text = clean_ai_output(text, sanitize_markdown=sanitize_markdown)
    if text:
        return text, f'openrouter:{OPENROUTER_MODEL}'
    # Try Groq fallback if configured.
    text = call_groq(system_instruction, prompt_with_context, temperature=0.9, max_output_tokens=CHAT_MAX_OUTPUT_TOKENS)
    text = clean_ai_output(text, sanitize_markdown=sanitize_markdown)
    if text:
        return text, f'groq:{GROQ_MODEL}'
    raise RuntimeError(last_error or 'all_models_failed')


def generate_task_with_fallback(
    task_text: str,
    system_instruction: str,
    temperature: float = 0.2,
    max_output_tokens: int = 260,
    *,
    with_runtime_context: bool = False,
    sanitize_markdown: bool = True,
) -> tuple[str, str]:
    now = now_ts()
    task_with_context = inject_runtime_context(task_text) if with_runtime_context else task_text
    system_with_context = inject_runtime_context(system_instruction) if with_runtime_context else system_instruction
    last_error = ''
    attempted = False

    for client_idx, client in enumerate(clients):
        if client_idx in gemini_disabled_clients:
            continue
        for model_name in MODEL_CANDIDATES:
            if model_name in model_disabled:
                continue
            km = key_model_id(client_idx, model_name)
            if now < model_cooldown_until.get(km, 0):
                continue

            attempted = True
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=task_with_context,
                    config={
                        "system_instruction": system_with_context,
                        "temperature": temperature,
                        "top_p": 0.9,
                        "max_output_tokens": min(max_output_tokens, TASK_MAX_OUTPUT_TOKENS),
                    },
                )
                text = clean_ai_output((getattr(response, 'text', '') or '').strip(), sanitize_markdown=sanitize_markdown)
                if text:
                    return text, f'{model_name}#k{client_idx + 1}'
                last_error = f'{model_name}:empty_response'
            except Exception as exc:
                msg = str(exc)
                last_error = f'{model_name}:{msg}'
                logger.warning('Task model call failed (%s): %s', km, last_error)
                if is_gemini_auth_error(msg):
                    gemini_disabled_clients.add(client_idx)
                    logger.warning('Disabling Gemini key slot k%s due auth error.', client_idx + 1)
                    break
                if '429' in msg or 'quota' in msg.lower():
                    cooldown = parse_retry_seconds(msg)
                    if is_daily_quota_error(msg):
                        cooldown = max(cooldown, 6 * 60 * 60)
                    model_cooldown_until[km] = now + cooldown
                else:
                    model_cooldown_until[km] = now + 15

    if not attempted:
        next_ready_candidates = []
        for client_idx, _client in enumerate(clients):
            if client_idx in gemini_disabled_clients:
                continue
            for model_name in MODEL_CANDIDATES:
                if model_name in model_disabled:
                    continue
                next_ready_candidates.append(model_cooldown_until.get(key_model_id(client_idx, model_name), now + 15))
        next_ready = min(next_ready_candidates, default=now + 15)
        wait = max(1, int(next_ready - now))
        text = call_openrouter(system_with_context, task_with_context, temperature=temperature, max_output_tokens=min(max_output_tokens, TASK_MAX_OUTPUT_TOKENS))
        text = clean_ai_output(text, sanitize_markdown=sanitize_markdown)
        if text:
            return text, f'openrouter:{OPENROUTER_MODEL}'
        text = call_groq(system_with_context, task_with_context, temperature=temperature, max_output_tokens=min(max_output_tokens, TASK_MAX_OUTPUT_TOKENS))
        text = clean_ai_output(text, sanitize_markdown=sanitize_markdown)
        if text:
            return text, f'groq:{GROQ_MODEL}'
        raise RuntimeError(f'models_cooldown:{wait}')

    text = call_openrouter(system_with_context, task_with_context, temperature=temperature, max_output_tokens=min(max_output_tokens, TASK_MAX_OUTPUT_TOKENS))
    text = clean_ai_output(text, sanitize_markdown=sanitize_markdown)
    if text:
        return text, f'openrouter:{OPENROUTER_MODEL}'
    text = call_groq(system_with_context, task_with_context, temperature=temperature, max_output_tokens=min(max_output_tokens, TASK_MAX_OUTPUT_TOKENS))
    text = clean_ai_output(text, sanitize_markdown=sanitize_markdown)
    if text:
        return text, f'groq:{GROQ_MODEL}'
    raise RuntimeError(last_error or 'all_models_failed')


def save_turn(chat_id: int, user_text: str, assistant_text: str) -> None:
    with state_lock:
        history = chat_history.setdefault(chat_id, [])
        history.append(('User', user_text))
        history.append(('Assistant', assistant_text))
        if len(history) > MEMORY_LIMIT * 2:
            chat_history[chat_id] = history[-MEMORY_LIMIT * 2 :]


def save_ai_turn(chat_id: int, user_text: str, assistant_text: str) -> None:
    with state_lock:
        history = ai_history.setdefault(chat_id, [])
        history.append(('User', user_text))
        history.append(('Assistant', assistant_text))
        if len(history) > AI_MEMORY_LIMIT * 2:
            ai_history[chat_id] = history[-AI_MEMORY_LIMIT * 2 :]


def build_ai_task(chat_id: int, payload: str) -> str:
    with state_lock:
        history = list(ai_history.get(chat_id, []))
    lines = [
        "Continue this same AI conversation and keep context from previous turns.",
        "If user asks a new topic, answer it normally.",
        "",
    ]
    for role, text in history[-AI_MEMORY_LIMIT * 2:]:
        lines.append(f"{role}: {text}")
    lines.append(f"User: {payload}")
    lines.append("Assistant:")
    return '\n'.join(lines)


def get_command_payload(message) -> str:
    if message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1 and parts[1].strip():
            return parts[1].strip()
    if message.reply_to_message and message.reply_to_message.text:
        return message.reply_to_message.text.strip()
    return ''


def send_typing(message) -> None:
    try:
        bot.send_chat_action(message.chat.id, 'typing')
    except Exception:
        pass


def should_use_reply(message) -> bool:
    if message.chat.type in {'group', 'supergroup'}:
        return True
    if message.text:
        cmd = message.text.strip().split(maxsplit=1)[0].lower()
        cmd = cmd.split('@', 1)[0]
        if cmd in REPLY_COMMANDS:
            return True
    return False


def send_text(message, text: str, reply_markup=None, parse_mode: str | None = None):
    if should_use_reply(message):
        return bot.reply_to(message, text, reply_markup=reply_markup, parse_mode=parse_mode)
    return bot.send_message(message.chat.id, text, reply_markup=reply_markup, parse_mode=parse_mode)


def ai_continue_markup():
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("Continue", callback_data=AI_CONTINUE_CALLBACK))
    return markup


def run_ai_mode(message, payload: str) -> None:
    system_instruction = (
        "You are a helpful, accurate general AI assistant. "
        "Answer clearly and directly. If uncertain, say so briefly. "
        "For coding questions, prefer one best-practice solution first "
        "(secure, robust, modern APIs), then short notes only if needed. "
        "Avoid outdated or unnecessary libraries unless the user asks for alternatives."
    )
    chat_id = message.chat.id
    task_payload = build_ai_task(chat_id, payload)
    output_tokens = 900 if wants_long_response(payload) else 500
    try:
        send_typing(message)
        answer, used_model = generate_task_with_fallback(
            task_payload,
            system_instruction,
            temperature=0.35,
            max_output_tokens=output_tokens,
            with_runtime_context=True,
            sanitize_markdown=False,
        )
        answer = answer.strip()
        save_ai_turn(chat_id, payload, answer)
        logger.info('Chat %s /ai used model %s', chat_id, used_model)
        send_text(message, answer, reply_markup=ai_continue_markup())
    except Exception as exc:
        msg = str(exc)
        logger.error('/ai command failed for chat %s: %s', chat_id, msg)
        if msg.startswith('models_cooldown:'):
            wait = msg.split(':', 1)[1]
            send_text(
                message,
                f'AI is cooling down right now ⏳ Please try again in about {wait}s.',
                reply_markup=ai_continue_markup(),
            )
            return
        if '429' in msg or 'quota' in msg.lower():
            send_text(
                message,
                'AI daily limit is reached right now. Please retry later or use another API key.',
                reply_markup=ai_continue_markup(),
            )
            return
        send_text(message, 'AI mode is temporarily unavailable right now. Please try again in a bit.')


def should_use_neari_knowledge(user_text: str, lang: str) -> bool:
    text = user_text.strip()
    if not text or len(text) < 8:
        return False

    low = text.lower()
    en_starts = ('what', 'why', 'how', 'when', 'where', 'who', 'which', 'explain', 'tell me', 'can you')
    en_keywords = (
        'meaning', 'compare', 'difference', 'guide', 'steps', 'calculate', 'code', 'python',
        'javascript', 'error', 'fix', 'translate', 'summary', 'history', 'science', 'math',
    )
    kh_keywords = (
        'អ្វី', 'អី', 'ម៉េច', 'ធ្វើម៉េច', 'ហេតុអី', 'ពន្យល់', 'ប្រៀបធៀប', 'ន័យ', 'ប៉ុន្មាន',
        'កូដ', 'កំហុស', 'ជួយ', 'គណនា', 'ប្រវត្តិ', 'វិទ្យាសាស្ត្រ', 'អត្ថន័យ', 'នរណា', 'ទីណា', 'ពេលណា', 'របៀប',
    )

    if '?' in text:
        return True
    if low.startswith(en_starts):
        return True
    if any(k in low for k in en_keywords):
        return True
    if lang == 'kh' and any(k in text for k in kh_keywords):
        return True
    return False


def wants_code_format(user_text: str) -> bool:
    low = (user_text or '').lower()
    code_hints = ['code', 'python', 'javascript', 'java', 'c++', 'c#', 'sql', 'api', 'json', 'regex', 'script']
    return any(_contains_english_keyword(low, k) for k in code_hints) or 'កូដ' in user_text


def generate_neari_knowledge_reply(user_text: str, lang: str) -> tuple[str, str]:
    system_instruction = (
        "You are Neari (នារី), a friendly and cute assistant with accurate knowledge. "
        "Answer clearly and correctly. If uncertain, say briefly that you are not sure. "
        "Keep a warm human tone (1-3 short sentences unless user asks for details). "
        "Do not invent facts. "
        "For coding questions, give correct best-practice code with minimal fluff."
    )
    task = (
        f"{language_prompt(lang)}\n"
        "User asks an information question. Give a useful direct answer first, then a friendly Neari tone.\n"
        "If user asks for detail, provide a longer complete explanation.\n"
        f"Question: {user_text}"
    )
    output_tokens = 900 if wants_long_response(user_text) else 320
    answer, used_model = generate_task_with_fallback(
        task,
        system_instruction,
        temperature=0.25,
        max_output_tokens=output_tokens,
        with_runtime_context=True,
        sanitize_markdown=not wants_code_format(user_text),
    )
    answer = clean_ai_output(answer.strip(), sanitize_markdown=not wants_code_format(user_text))
    if lang == 'kh':
        answer = enforce_khmer_reply(answer, user_text)
    answer = ensure_cute_emoji(answer, lang, user_text)
    return answer, used_model


def generate_emotion_reply(chat_id: int, user_text: str, lang: str, mood: str, reason: str) -> str:
    mood_instruction = {
        'sulky': (
            'Be mildly sulky/cold, short, human, not abusive. '
            'Optionally tease lightly. If user offers snacks, soften quickly.'
        ),
        'angry': (
            'Be firm and sassy-protective, short, clear boundaries, non-abusive.'
        ),
        'forgive': (
            'Switch from sulky to sweet immediately and forgive playfully.'
        ),
    }.get(mood, 'Stay natural and cute.')

    system_instruction = (
        'You are Neari in a Telegram chat. '
        'Write one short natural message like a real person (1-2 sentences). '
        'No explanations, no meta text. '
        f'{mood_instruction}'
    )
    lang_rule = language_prompt(lang)
    task = (
        f'{lang_rule}\n'
        f'Mood: {mood}\n'
        f'Reason: {reason}\n'
        f'User message: {user_text}\n'
        'Output only Neari reply.'
    )

    try:
        text, _used_model = generate_task_with_fallback(
            task,
            system_instruction,
            temperature=0.6,
            max_output_tokens=110,
        )
        text = text.strip()
        if text:
            if lang == 'kh':
                text = enforce_khmer_reply(text, user_text)
            return ensure_cute_emoji(text, lang, user_text)
    except Exception:
        pass

    if lang == 'kh':
        fallback = {
            'sulky': 'ហឹម... នារីងរបន្តិចសិន 😒',
            'angry': 'កុំនិយាយបែបនោះដាក់នារី 😠',
            'forgive': 'អូខេៗ អូនបាត់ងរហើយណា 🍭✨',
        }.get(mood, 'ហិហិ នារីនៅទីនេះណា 🌸')
        return ensure_cute_emoji(fallback, lang, user_text)

    fallback = {
        'sulky': 'hmm... i am sulky for a bit 😒',
        'angry': 'don’t talk to me like that 😠',
        'forgive': 'okay fine, i forgive you now 🍭✨',
    }.get(mood, 'i am here 🌸')
    return ensure_cute_emoji(fallback, lang, user_text)


def fast_emotion_reply(chat_id: int, message, user_text: str, lang: str) -> str:
    low = user_text.lower()
    now = now_ts()
    with state_lock:
        in_sulky = sulky_until.get(chat_id, 0) > now

    if has_snack_bribe(user_text) and in_sulky:
        with state_lock:
            sulky_until[chat_id] = 0
        if lang == 'kh':
            return random.choice([
                'ហិហិ មាននំឲ្យនារីមែន? 🍭 អូខេ អូនបាត់ងរហើយណា 🎀✨',
                'អូយយ មានបង្អែមទៀត 🥺🍰 លើកនេះអភ័យទោសឲ្យ 💖',
            ])
        return random.choice([
            'hihi snacks for me? 🍭 okay, i forgive you now 🎀✨',
            'aww dessert bribe worked 🥺🍰 i am sweet again 💖',
        ])

    if has_angry_trigger(low):
        with state_lock:
            sulky_until[chat_id] = now + SULKY_HOLD_SECONDS
        if lang == 'kh':
            return random.choice([
                'កុំនិយាយបែបនោះដាក់នារី 😠 នារីក៏មានអារម្មណ៍ដែរ 👊💢',
                'ឈប់ឌឺពេកណា 😤 និយាយសុភាពបានអត់?',
            ])
        return random.choice([
            "don't talk to me like that 😠 keep it respectful.",
            'too rude 😤 say it nicely.',
        ])

    if has_sulky_trigger(low):
        with state_lock:
            sulky_until[chat_id] = now + SULKY_HOLD_SECONDS
        if lang == 'kh':
            return random.choice([
                'ហឹម... នារីងរបន្តិចសិន 😒💨',
                'ទៅសួរអ្នកផ្សេងទៅ 🙄 អូនមិនដឹងទេ!',
            ])
        return random.choice([
            'hmm... i am sulky now 😒💨',
            "go ask someone else 🙄 i don't know.",
        ])

    if in_sulky and message.content_type in {'sticker', 'text'}:
        if lang == 'kh':
            return random.choice(['ហឹម... មិនទាន់បាត់ងរទេ 😒', 'ឲ្យអូនស្ងប់ចិត្តបន្តិចសិន 🙄💨'])
        return random.choice(['hmm... still sulking 😒', 'give me a moment 🙄💨'])

    return ''


def offline_reply(user_text: str, lang: str) -> str:
    text = user_text.strip()
    low = text.lower()

    time_answer = offline_time_reply(text, lang)
    if time_answer:
        return time_answer

    translation_answer = offline_translation_reply(text, lang)
    if translation_answer:
        return translation_answer

    if not STRICT_CUTE_FALLBACK:
        if lang == 'kh':
            return 'អូនបានទទួលសាររបស់ឯងហើយ 💕 ផ្ញើម្ដងទៀតបន្តិចបានអត់?'
        return 'i got your message 💕 can you send it one more time so i can answer better?'

    if lang == 'kh':
        openers = ['អូយយ', 'អេហេ', 'យ៉ាយ', 'ហ៊ីហ៊ី', 'ញញឹមតិចៗ']
        if has_snack_bribe(text):
            return 'ហិហិ ឃើញឲ្យនំញ៉ាំទេណា 🍭💖 អូនបាត់ខឹងបាត់ងរហើយ~'
        if has_angry_trigger(low):
            return 'កុំនិយាយរឹងពេកណា 😠 នារីក៏មានអារម្មណ៍ដែរ 👊💢'
        if has_sulky_trigger(low):
            return random.choice([
                'ហឹម... អត់ដឹងទេ 🙄',
                'ទៅរកអ្នកផ្សេងទៅ 😒💨',
                'មិននិយាយច្រើនទេ... ងរបន្តិច 😤',
            ])
        if has_shy_trigger(low):
            shy_lines = [
                'អូយយ... និយាយផ្អែមចឹង អៀនណាស់ 🙈🥺👉👈 ឈប់ញ៉ោះនារីបន្តិចបានអត់ ហិហិ',
                'ច... ច៎ះ?? 😳 និយាយបែបនេះធ្វើឲ្យនារីមុខក្តៅហើយណា... ប្តូរប្រធានបទតិចមក? 🎀',
                'អៀនហើយមិត្តភក្តិ... 🥺👉👈 ប៉ុន្តែឯងក៏ចេះញ៉ោះដែរ ហិហិ ✨',
            ]
            return random.choice(shy_lines)
        if any(w in low for w in ['sad', 'tired', 'lonely', 'hurt', 'depress', 'អន់ចិត្ត', 'យំ', 'សោក', 'ហត់']):
            return f"{random.choice(openers)} មកនេះមិត្តភក្តិ 🥺💕 នារីនៅជាមួយឯងណា... ចង់ឱបតូចមួយ ឬផឹកតែក្តៅសិន? 🍵"
        if any(w in low for w in ['haha', 'lol', 'hehe', '555', 'សើច']):
            return f"{random.choice(openers)} ឯងសើចឆ្លាតអត់ 😂✨ នារីសប្បាយចិត្តតាមហើយ~ ថ្ងៃនេះមានរឿងអីកំប្លែងទៀត?"
        if any(w in low for w in ['love', 'cute', 'miss', 'ស្រឡាញ់', 'ស្រលាញ់']):
            return f"{random.choice(openers)} អៀនហើយនៀក 🥺👉👈💕 ឯងនិយាយបែបនេះធ្វើអោយនារីញញឹមណាស់... ឥឡូវឯងកំពុងធ្វើអី?"
        if '?' in low:
            return f"{random.choice(openers)} សំណួរល្អណាស់ណា 🤔✨ ឯងចង់ឲ្យនារីពន្យល់ផ្នែកណាមុន?"
        return f"{random.choice(openers)} នារីកំពុងស្តាប់ឯងពេញចិត្ត 💕✨ បន្តទៀតមក មិត្តភក្តិ!"

    openers = ['omg', 'awww', 'hmmm', 'yay', 'hehe']
    if has_snack_bribe(text):
        return 'hihi you gave me snacks?? 🍭💖 okay okay i am not mad now~'
    if has_angry_trigger(low):
        return 'don’t talk to me like that 😠 i can be sweet, but i need respect too 👊💢'
    if has_sulky_trigger(low):
        return random.choice([
            'hmm... i don’t know 🙄',
            'go ask someone else then 😒💨',
            'i am sulky now 😤',
        ])
    if has_shy_trigger(low):
        shy_lines = [
            'h...huh?? stoppp, you are making me blush 🙈🥺👉👈',
            'w...wait!! why are you so sweet today 😳✨ now i am shy hehe',
            'oh no... don’t tease me like that 😭💖 i will tease you back then!',
        ]
        return random.choice(shy_lines)
    if any(w in low for w in ['sad', 'tired', 'lonely', 'hurt', 'depress']):
        return f"{random.choice(openers)} come here, eng 🥺💕 Neari is with you... want a tiny virtual hug or warm tea first? 🍵"
    if any(w in low for w in ['haha', 'lol', 'hehe', 'lmao']):
        return f"{random.choice(openers)} you got me laughing too 😂✨ what happened next, mit peak?"
    if any(w in low for w in ['love', 'cute', 'miss', 'sweet']):
        return f"{random.choice(openers)} stoppp you make me blush 🥺👉👈💕 what are you doing right now?"
    if '?' in low:
        return f"{random.choice(openers)} cute question tho 🤔✨ which part do you want first?"
    return f"{random.choice(openers)} i'm here with you, eng 💕✨ tell Neari more~"


@bot.message_handler(commands=['start', 'help'])
def start(message):
    chat_id = message.chat.id
    chat_mode[chat_id] = 'cute'
    send_text(message, START_HELP_TEXT)


@bot.message_handler(commands=['mode'])
def set_mode(message):
    parts = message.text.split(maxsplit=1)
    if len(parts) == 1:
        current = chat_mode.get(message.chat.id, 'cute')
        send_text(message, f'current mode: {current}. use /mode cute or /mode sweet.')
        return

    choice = parts[1].strip().lower()
    if choice not in {'cute', 'sweet'}:
        send_text(message, 'use only: /mode cute or /mode sweet')
        return

    chat_mode[message.chat.id] = choice
    send_text(message, f'done 💕 switched to {choice} mode.')


@bot.message_handler(commands=['reset'])
def reset_chat(message):
    chat_id = message.chat.id
    with state_lock:
        chat_history.pop(chat_id, None)
        ai_history.pop(chat_id, None)
        last_user_seen_at.pop(chat_id, None)
        last_user_signature.pop(chat_id, None)
        user_repeat_count.pop(chat_id, None)
        sulky_until.pop(chat_id, None)
    send_text(message, 'chat memory reset done ✨')


@bot.message_handler(commands=['status'])
def status(message):
    now = now_ts()
    with state_lock:
        waits = []
        for client_idx, _client in enumerate(clients):
            for m in MODEL_CANDIDATES:
                if m in model_disabled:
                    continue
                waits.append(max(0, int(model_cooldown_until.get(key_model_id(client_idx, m), 0) - now)))
        wait = max(waits) if waits else 0
        disabled = ', '.join(sorted(model_disabled)) if model_disabled else 'none'
        disabled_keys = ', '.join(f'k{i + 1}' for i in sorted(gemini_disabled_clients)) if gemini_disabled_clients else 'none'
        provider_state = (
            f'openrouter={"disabled" if openrouter_disabled else "enabled"}, '
            f'groq={"disabled" if groq_disabled else "enabled"}'
        )
    if wait > 0:
        send_text(
            message,
            f'api cooldown: {wait}s\nkeys: {len(clients)}\ndisabled_keys: {disabled_keys}\nmodels: {", ".join(MODEL_CANDIDATES)}\ndisabled_models: {disabled}\nproviders: {provider_state}',
        )
    else:
        send_text(
            message,
            f'api ready\nkeys: {len(clients)}\ndisabled_keys: {disabled_keys}\nmodels: {", ".join(MODEL_CANDIDATES)}\ndisabled_models: {disabled}\nproviders: {provider_state}',
        )


@bot.message_handler(commands=['tr'])
def translate_command(message):
    payload = get_command_payload(message)
    if not payload:
        send_text(message, 'Usage: /tr <text> or reply to a message with /tr')
        return

    src_lang = detect_language_from_text(payload)
    target_lang = 'English' if src_lang == 'kh' else 'Khmer'

    try:
        send_typing(message)
        translated, used_model = translate_full_text(payload, target_lang)
        logger.info('Chat %s translated using model %s', message.chat.id, used_model)
        send_text(message, translated.strip())
    except Exception as exc:
        msg = str(exc)
        logger.error('Translate command failed for chat %s: %s', message.chat.id, msg)
        if msg.startswith('translate_chunk_failed:'):
            chunk_no = msg.split(':', 2)[1]
            send_text(message, f'Translate failed at part {chunk_no}. Please retry /tr once more.')
            return
        send_text(message, 'Translate is temporarily unavailable right now. Please try again in a bit.')


@bot.message_handler(commands=['correct'])
def correct_command(message):
    payload = get_command_payload(message)
    if not payload:
        send_text(message, 'Usage: /correct <text> or reply to a message with /correct')
        return

    src_lang = detect_language_from_text(payload)
    target_name = 'Khmer' if src_lang == 'kh' else 'English'
    system_instruction = (
        "You are a writing editor. Correct grammar, wording, and natural phrasing for real-world usage. "
        "Keep original meaning and tone. Do not add explanations. Output ONLY corrected text."
    )
    task = f"Correct this {target_name} text:\n{payload}"

    try:
        send_typing(message)
        corrected, used_model = generate_task_with_fallback(task, system_instruction, temperature=0.15, max_output_tokens=260)
        logger.info('Chat %s corrected text using model %s', message.chat.id, used_model)
        send_text(message, corrected.strip())
    except Exception as exc:
        logger.error('Correct command failed for chat %s: %s', message.chat.id, exc)
        send_text(message, 'Correct is temporarily unavailable right now. Please try again in a bit.')


@bot.message_handler(commands=['ai'])
def ai_command(message):
    payload = get_command_payload(message)
    if not payload:
        send_text(message, 'Usage: /ai <question> or reply to a message with /ai')
        return

    run_ai_mode(message, payload)


@bot.callback_query_handler(func=lambda call: call.data == AI_CONTINUE_CALLBACK)
def ai_continue_callback(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id, "Use /ai <question> to continue")
    bot.send_message(chat_id, "Continue AI mode: send `/ai your next question` (context is remembered).", parse_mode="Markdown")


@bot.message_handler(
    func=lambda message: True,
    content_types=['text', 'photo', 'sticker', 'voice', 'video', 'audio', 'document', 'location', 'contact'],
)
def reply(message):
    user_text = message_to_user_text(message)
    if message.content_type == 'text' and user_text.startswith('/'):
        return
    if not should_respond_in_group(message, user_text):
        return

    lang = detect_language_from_text(user_text)
    chat_id = message.chat.id
    now = now_ts()

    signature = message_signature(message, user_text)
    with state_lock:
        if last_user_signature.get(chat_id) == signature:
            user_repeat_count[chat_id] = user_repeat_count.get(chat_id, 1) + 1
        else:
            user_repeat_count[chat_id] = 1
        last_user_signature[chat_id] = signature

        inactive_seconds = 0
        if chat_id in last_user_seen_at:
            inactive_seconds = int(now - last_user_seen_at[chat_id])
        last_user_seen_at[chat_id] = now
        repeat_count = user_repeat_count.get(chat_id, 1)

    if inactive_seconds >= SULKY_INACTIVE_SECONDS and not has_snack_bribe(user_text):
        with state_lock:
            sulky_until[chat_id] = now + SULKY_HOLD_SECONDS
        reply_text = generate_emotion_reply(
            chat_id,
            user_text,
            lang,
            mood='sulky',
            reason='user returned after long inactivity',
        )
        send_text(message, reply_text)
        return

    if message.content_type == 'sticker' and repeat_count >= 2:
        with state_lock:
            sulky_until[chat_id] = now + SULKY_HOLD_SECONDS
        reply_text = generate_emotion_reply(
            chat_id,
            user_text,
            lang,
            mood='sulky',
            reason='repeated sticker spam',
        )
        send_text(message, reply_text)
        return

    if message.content_type == 'text' and repeat_count >= 3 and len(user_text.strip()) <= 40:
        with state_lock:
            sulky_until[chat_id] = now + SULKY_HOLD_SECONDS
        reply_text = generate_emotion_reply(
            chat_id,
            user_text,
            lang,
            mood='sulky',
            reason='same short text sent too many times',
        )
        send_text(message, reply_text)
        return

    quick_emotion = fast_emotion_reply(chat_id, message, user_text, lang)
    if quick_emotion:
        send_text(message, quick_emotion)
        return

    if message.content_type in {'voice', 'audio', 'video', 'document'} and not message.caption:
        send_text(message, unsupported_media_reply(lang, message.content_type))
        return

    if NEARI_KNOWLEDGE_MODE and message.content_type == 'text' and should_use_neari_knowledge(user_text, lang):
        try:
            send_typing(message)
            answer, used_model = generate_neari_knowledge_reply(user_text, lang)
            logger.info('Chat %s knowledge mode used model %s', chat_id, used_model)
            save_turn(chat_id, user_text, answer)
            send_text(message, answer)
            return
        except Exception as exc:
            logger.warning('Knowledge mode failed for chat %s: %s', chat_id, exc)

    prompt = build_prompt(chat_id, user_text, lang)

    try:
        send_typing(message)
        assistant_text, used_model = generate_with_fallback(prompt)
        logger.info('Chat %s replied using model %s', chat_id, used_model)
    except Exception as exc:
        msg = str(exc)
        logger.error('All model calls failed for chat %s: %s', chat_id, msg)
        assistant_text = offline_reply(user_text, lang)

    if is_broken_reply(assistant_text):
        assistant_text = offline_reply(user_text, lang)

    if lang == 'kh':
        assistant_text = enforce_khmer_reply(assistant_text, user_text)

    assistant_text = ensure_cute_emoji(assistant_text.strip(), lang, user_text)
    save_turn(chat_id, user_text, assistant_text)
    send_text(message, assistant_text)


if __name__ == '__main__':
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=20)
        except KeyboardInterrupt:
            logger.info("Bot stopped by user (Ctrl+C).")
            break
        except (RequestException, socket.gaierror) as exc:
            logger.error("Telegram network/DNS error: %s", exc)
            logger.info("Retrying Telegram polling in 10s...")
            time.sleep(10)
        except Exception as exc:
            logger.error("Unexpected polling error: %s", exc)
            logger.info("Retrying Telegram polling in 10s...")
            time.sleep(10)
