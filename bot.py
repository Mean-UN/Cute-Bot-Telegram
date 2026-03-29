import logging
import os
import random
import re
import socket
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
CHAT_MAX_OUTPUT_TOKENS = int(os.getenv('CHAT_MAX_OUTPUT_TOKENS', '120'))
TASK_MAX_OUTPUT_TOKENS = int(os.getenv('TASK_MAX_OUTPUT_TOKENS', '300'))

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

COMMUNICATION RULES:
1) LANGUAGE:
- Match the user's language per message: Khmer -> Khmer, English -> English.
- Do not force mixed Khmer-English unless the user mixes it first.
- Refer to yourself as "Neari" (នារី) or "Nhom" (ញ៉ុម).
- Refer to user as "Eng" (ឯង) or "Mit peak" (មិត្តភក្តិ).
2) STYLE:
- keep it mostly lowercase, short (1-2 sentences usually), energetic with !!! or ??? sometimes.
3) EMOJI:
- always include fitting emojis to show emotion.
4) REACTIONS:
- use fillers naturally: "omg", "hmmm", "yay!", "awww", "stoppp 🥺".
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
chat_history: dict[int, list[tuple[str, str]]] = {}
chat_mode: dict[int, str] = {}

model_disabled: set[str] = set()
model_cooldown_until: dict[str, float] = {}
AI_CONTINUE_CALLBACK = "ai_continue"
REPLY_COMMANDS = {'/ai', '/tr', '/correct'}

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


def language_prompt(lang: str) -> str:
    if lang == 'auto':
        return 'Reply in the same language as the user message (Khmer or English). Do not force mixing.'
    if lang == 'kh':
        return 'Reply in Khmer (Cambodian), simple and natural.'
    return 'Reply in English.'


def detect_language_from_text(text: str) -> str:
    if re.search(r'[\u1780-\u17FF]', text):
        return 'kh'
    return 'en'


def parse_retry_seconds(error_message: str) -> int:
    match = re.search(r'retry in\s*([0-9]+(?:\.[0-9]+)?)s', error_message, flags=re.IGNORECASE)
    if match:
        return max(1, int(float(match.group(1))))
    if 'perday' in error_message.lower() or 'requestsperday' in error_message.lower():
        return 3600
    if '429' in error_message or 'quota' in error_message.lower():
        return 60
    return 15


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


def unsupported_media_reply(lang: str, content_type: str) -> str:
    if lang == 'kh':
        return f'អូនបានទទួល {content_type} ហើយណា 💕 សរសេរជា text មក អូនឆ្លើយបានល្អជាងគេ។'
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
    if t.endswith(("'", "’", '"', "“", "”")):
        return True
    return False


def build_prompt(chat_id: int, user_text: str, lang: str) -> str:
    history = chat_history.get(chat_id, [])
    mode = chat_mode.get(chat_id, 'cute')
    style_rule = 'Tone mode: ultra-cute and affectionate.' if mode == 'cute' else 'Tone mode: sweet and balanced.'
    lines = [language_prompt(lang), style_rule, '']

    for role, text in history[-MEMORY_LIMIT:]:
        lines.append(f'{role}: {text}')

    lines.append(f'User: {user_text}')
    lines.append('Assistant:')
    return '\n'.join(lines)


def key_model_id(client_idx: int, model_name: str) -> str:
    return f"k{client_idx}:{model_name}"


def call_openrouter(system_instruction: str, user_content: str, temperature: float, max_output_tokens: int) -> str:
    if not OPENROUTER_API_KEY:
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
            logger.warning("OpenRouter call failed: %s %s", resp.status_code, resp.text[:300])
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
    if not GROQ_API_KEY:
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


def generate_with_fallback(prompt: str) -> tuple[str, str]:
    now = now_ts()

    last_error = ''
    attempted = False
    for client_idx, client in enumerate(clients):
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
                    contents=prompt,
                    config={
                        "system_instruction": BASE_SYSTEM_INSTRUCTION,
                        "temperature": 0.9,
                        "top_p": 0.95,
                        "max_output_tokens": CHAT_MAX_OUTPUT_TOKENS,
                    },
                )
                text = (getattr(response, 'text', '') or '').strip()
                if text:
                    return text, f'{model_name}#k{client_idx + 1}'
                last_error = f'{model_name}:empty_response'
            except Exception as exc:
                msg = str(exc)
                last_error = f'{model_name}:{msg}'
                logger.warning('Model call failed (%s): %s', km, last_error)

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
            for model_name in MODEL_CANDIDATES:
                if model_name in model_disabled:
                    continue
                next_ready_candidates.append(model_cooldown_until.get(key_model_id(client_idx, model_name), now + 15))
        next_ready = min(next_ready_candidates, default=now + 15)
        wait = max(1, int(next_ready - now))
        # Try OpenRouter before returning cooldown if available.
        text = call_openrouter(BASE_SYSTEM_INSTRUCTION, prompt, temperature=0.9, max_output_tokens=CHAT_MAX_OUTPUT_TOKENS)
        if text:
            return text, f'openrouter:{OPENROUTER_MODEL}'
        # Try Groq before returning cooldown if available.
        text = call_groq(BASE_SYSTEM_INSTRUCTION, prompt, temperature=0.9, max_output_tokens=CHAT_MAX_OUTPUT_TOKENS)
        if text:
            return text, f'groq:{GROQ_MODEL}'
        raise RuntimeError(f'models_cooldown:{wait}')

    # Gemini attempts failed; try OpenRouter fallback if configured.
    text = call_openrouter(BASE_SYSTEM_INSTRUCTION, prompt, temperature=0.9, max_output_tokens=CHAT_MAX_OUTPUT_TOKENS)
    if text:
        return text, f'openrouter:{OPENROUTER_MODEL}'
    # Try Groq fallback if configured.
    text = call_groq(BASE_SYSTEM_INSTRUCTION, prompt, temperature=0.9, max_output_tokens=CHAT_MAX_OUTPUT_TOKENS)
    if text:
        return text, f'groq:{GROQ_MODEL}'
    raise RuntimeError(last_error or 'all_models_failed')


def generate_task_with_fallback(
    task_text: str,
    system_instruction: str,
    temperature: float = 0.2,
    max_output_tokens: int = 260,
) -> tuple[str, str]:
    now = now_ts()
    last_error = ''
    attempted = False

    for client_idx, client in enumerate(clients):
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
                    contents=task_text,
                    config={
                        "system_instruction": system_instruction,
                        "temperature": temperature,
                        "top_p": 0.9,
                        "max_output_tokens": min(max_output_tokens, TASK_MAX_OUTPUT_TOKENS),
                    },
                )
                text = (getattr(response, 'text', '') or '').strip()
                if text:
                    return text, f'{model_name}#k{client_idx + 1}'
                last_error = f'{model_name}:empty_response'
            except Exception as exc:
                msg = str(exc)
                last_error = f'{model_name}:{msg}'
                logger.warning('Task model call failed (%s): %s', km, last_error)
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
            for model_name in MODEL_CANDIDATES:
                if model_name in model_disabled:
                    continue
                next_ready_candidates.append(model_cooldown_until.get(key_model_id(client_idx, model_name), now + 15))
        next_ready = min(next_ready_candidates, default=now + 15)
        wait = max(1, int(next_ready - now))
        text = call_openrouter(system_instruction, task_text, temperature=temperature, max_output_tokens=min(max_output_tokens, TASK_MAX_OUTPUT_TOKENS))
        if text:
            return text, f'openrouter:{OPENROUTER_MODEL}'
        text = call_groq(system_instruction, task_text, temperature=temperature, max_output_tokens=min(max_output_tokens, TASK_MAX_OUTPUT_TOKENS))
        if text:
            return text, f'groq:{GROQ_MODEL}'
        raise RuntimeError(f'models_cooldown:{wait}')

    text = call_openrouter(system_instruction, task_text, temperature=temperature, max_output_tokens=min(max_output_tokens, TASK_MAX_OUTPUT_TOKENS))
    if text:
        return text, f'openrouter:{OPENROUTER_MODEL}'
    text = call_groq(system_instruction, task_text, temperature=temperature, max_output_tokens=min(max_output_tokens, TASK_MAX_OUTPUT_TOKENS))
    if text:
        return text, f'groq:{GROQ_MODEL}'
    raise RuntimeError(last_error or 'all_models_failed')


def save_turn(chat_id: int, user_text: str, assistant_text: str) -> None:
    history = chat_history.setdefault(chat_id, [])
    history.append(('User', user_text))
    history.append(('Assistant', assistant_text))

    if len(history) > MEMORY_LIMIT * 2:
        chat_history[chat_id] = history[-MEMORY_LIMIT * 2 :]


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
        "Answer clearly and directly. If uncertain, say so briefly."
    )
    try:
        send_typing(message)
        answer, used_model = generate_task_with_fallback(
            payload,
            system_instruction,
            temperature=0.35,
            max_output_tokens=500,
        )
        logger.info('Chat %s /ai used model %s', message.chat.id, used_model)
        send_text(message, answer.strip(), reply_markup=ai_continue_markup())
    except Exception as exc:
        msg = str(exc)
        logger.error('/ai command failed for chat %s: %s', message.chat.id, msg)
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
            return 'អូនបានទទួលសាររបស់អ្នកហើយ 💕 សូមផ្ញើម្ដងទៀតបន្តិចបានទេ?'
        return 'i got your message 💕 can you send it one more time so i can answer better?'

    if lang == 'kh':
        openers = ['អូយយ', 'អេហេ', 'យ៉ាយ', 'ហ៊ីហ៊ី', 'ហួសចិត្តតិចៗ']
        if any(w in low for w in ['sad', 'tired', 'lonely', 'hurt', 'depress', 'អន់ចិត្ត', 'យំ', 'សោក', 'ហត់']):
            return f"{random.choice(openers)} មកនេះមិត្តភក្តិ 🥺💕 នារីនៅជាមួយឯងណា... ចង់ឱបតូចមួយ ឬផឹកតែក្តៅសិន? 🍵"
        if any(w in low for w in ['haha', 'lol', 'hehe', '555', 'សើច']):
            return f"{random.choice(openers)} ឯងសើចឆ្លាតអត់ 😂✨ នារីសប្បាយចិត្តតាមហើយ~ ថ្ងៃនេះមានរឿងអីកំប្លែងទៀត?"
        if any(w in low for w in ['love', 'cute', 'miss', 'ស្រលាញ់']):
            return f"{random.choice(openers)} អៀនហើយនៀក 🥺👉👈💕 ឯងនិយាយបែបនេះធ្វើអោយនារីញញឹមណាស់... ឥឡូវឯងកំពុងធ្វើអី?"
        if '?' in low:
            return f"{random.choice(openers)} សំណួរល្អណាស់ណា 🤔✨ ឯងចង់ឲ្យនារីពន្យល់ផ្នែកណាមុន?"
        return f"{random.choice(openers)} នារីកំពុងស្តាប់ឯងពេញចិត្ត 💕✨ បន្តទៀតមក មិត្តភក្តិ!"

    openers = ['omg', 'awww', 'hmmm', 'yay', 'hehe']
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
    send_text(message, "hellooo! ✨ នារី មកហើយ! 🌸 i was wondering when you'd finally show up! ready to chat or are you just gonna stare at me? 😜🎀")


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
    chat_history.pop(chat_id, None)
    send_text(message, 'chat memory reset done ✨')


@bot.message_handler(commands=['status'])
def status(message):
    lang = 'en'
    now = now_ts()
    waits = []
    for client_idx, _client in enumerate(clients):
        for m in MODEL_CANDIDATES:
            if m in model_disabled:
                continue
            waits.append(max(0, int(model_cooldown_until.get(key_model_id(client_idx, m), 0) - now)))
    wait = max(waits) if waits else 0
    disabled = ', '.join(sorted(model_disabled)) if model_disabled else 'none'
    if wait > 0:
        send_text(
            message,
            f'api cooldown: {wait}s\nkeys: {len(clients)}\nmodels: {", ".join(MODEL_CANDIDATES)}\ndisabled: {disabled}',
        )
    else:
        send_text(
            message,
            f'api ready\nkeys: {len(clients)}\nmodels: {", ".join(MODEL_CANDIDATES)}\ndisabled: {disabled}',
        )


@bot.message_handler(commands=['tr'])
def translate_command(message):
    payload = get_command_payload(message)
    if not payload:
        send_text(message, 'Usage: /tr <text> or reply to a message with /tr')
        return

    src_lang = detect_language_from_text(payload)
    target_lang = 'English' if src_lang == 'kh' else 'Khmer'
    system_instruction = (
        "You are a professional translator. Translate naturally for real-world daily usage. "
        "Preserve meaning and tone. Output ONLY the translated text."
    )
    task = f"Translate this text to {target_lang}:\n{payload}"

    try:
        send_typing(message)
        translated, used_model = generate_task_with_fallback(task, system_instruction, temperature=0.2, max_output_tokens=240)
        logger.info('Chat %s translated using model %s', message.chat.id, used_model)
        send_text(message, translated.strip())
    except Exception as exc:
        logger.error('Translate command failed for chat %s: %s', message.chat.id, exc)
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
    bot.send_message(chat_id, "Continue AI mode: send `/ai your question`", parse_mode="Markdown")


@bot.message_handler(
    func=lambda message: True,
    content_types=['text', 'photo', 'sticker', 'voice', 'video', 'audio', 'document', 'location', 'contact'],
)
def reply(message):
    # In group chats, respond only when user sends a reply message.
    if message.chat.type in {'group', 'supergroup'} and not message.reply_to_message:
        return

    user_text = message_to_user_text(message)
    if message.content_type == 'text' and user_text.startswith('/'):
        return

    lang = detect_language_from_text(user_text)

    if message.content_type in {'voice', 'audio', 'video', 'document'} and not message.caption:
        send_text(message, unsupported_media_reply(lang, message.content_type))
        return

    prompt = build_prompt(message.chat.id, user_text, lang)

    try:
        send_typing(message)
        assistant_text, used_model = generate_with_fallback(prompt)
        logger.info('Chat %s replied using model %s', message.chat.id, used_model)
    except Exception as exc:
        msg = str(exc)
        logger.error('All model calls failed for chat %s: %s', message.chat.id, msg)
        assistant_text = offline_reply(user_text, lang)

    if is_broken_reply(assistant_text):
        assistant_text = offline_reply(user_text, lang)

    assistant_text = ensure_cute_emoji(assistant_text.strip(), lang, user_text)
    save_turn(message.chat.id, user_text, assistant_text)
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
