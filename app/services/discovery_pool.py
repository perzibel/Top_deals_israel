"""
Search keywords for discovery, grouped by rotation category.

Bestseller searches for broad terms ("usb c hub", "gaming mouse") return the same
generic listings every time, so most of the pool is niche, fun gadgets. Staples
(chargers, power banks) still show up, just less often.
"""
import random

# "Wow" gadgets: the channel's main content.
GADGET_KEYWORDS: dict[str, list[str]] = {
    "gadgets": [
        "mini projector", "transparent power bank", "magnetic power bank", "smart ring",
        "bone conduction headphones", "open ear earbuds", "translator earbuds",
        "mini thermal printer", "pocket photo printer", "label maker",
        "usb microscope", "endoscope camera", "night vision monocular",
        "mini action camera", "360 camera", "gimbal stabilizer", "phone cooler fan",
        "air quality monitor", "co2 monitor", "geiger counter", "weather station",
        "digital photo frame", "translation pen", "ai voice recorder", "mini bluetooth speaker",
        "neck fan", "arc lighter", "edc flashlight", "keychain flashlight", "headlamp rechargeable",
        "solar power bank", "magnetic phone grip",
        "phone camera lens kit", "wireless lavalier microphone", "e-ink",
    ],
    "lighting_vibes": [
        "magnetic levitation lamp", "galaxy projector", "sunset lamp", "moon lamp",
        "pixel display", "rgb light bar",
        "smart led panels", "fiber optic lamp", "plasma ball",
        "music tesla coil", "sound reactive led", "tv backlight sync", "led neon sign",
    ],
    "gaming_pc": [
        "retro handheld game console", "anbernic", "miyoo mini", "retro game stick",
        "arcade joystick", "hall effect controller", "8bitdo", "gamesir", "phone game controller",
        "mobile gaming triggers", "steam deck dock", "switch dock", "mini pc", "macro keypad",
        "hall effect keyboard", "split keyboard", "artisan keycaps", "stream controller",
        "capture card", "4k webcam", "mouse jiggler", "rgb headphone stand", "monitor arm",
        "hdmi kvm switch", "nvme enclosure", "wireless hdmi transmitter",
    ],
    "smart_home": [
        "mmwave presence sensor", "zigbee button", "wifi ir blaster", "switchbot",
        "fingerprint padlock", "solar security camera", "bird feeder camera",
        "water leak sensor", "smart thermostat", "smart curtain robot", "zigbee gateway",
        "fingerprint door lock", "video doorbell", "smart garage door",
    ],
    "car": [
        "car hud", "wireless carplay adapter", "carplay ai box",
        "tire pressure monitor", "obd2 scanner", "car door projector light", "car star roof light",
        "car ambient light", "electric air duster", "dash cam 4k",
        "wireless backup camera", "jump starter power bank",
    ],
    "toys_hobbies": [
        "mini drone", "fpv drone", "rc drift car", "mini rc car", "rc boat", "rc helicopter",
        "rc excavator", "fidget gadget", "desk toy", "puzzle box", "speed cube",
        "stem robot kit", "building blocks technic", "solar robot kit",
    ],
    "tools_diy": [
        "electric precision screwdriver", "mini electric screwdriver", "pinecil", "mini soldering iron",
        "cordless hot glue gun", "heat gun", "3d pen", "mini grinder", "laser distance meter",
        "laser tape measure", "digital caliper", "stud finder", "magnetic wristband",
        "ratchet screwdriver", "multitool", "arduino starter kit", "esp32",
        "diy electronics kit", "cable tester", "smart multimeter",
    ],
}

# Everyday staples: still useful deals, but they get stale fast.
STAPLE_KEYWORDS: dict[str, list[str]] = {
    "phone_accessories": [
        "100w gan charger", "baseus power bank", "ugreen charger", "magsafe charger",
        "3 in 1 wireless charger",
    ],
    "electronics": ["wireless earbuds", "anc earbuds"],
    "car": ["portable tire inflator", "mini car vacuum"],
    "desk_office": ["desk setup gadgets", "monitor light bar"],
}

KEYWORD_CATEGORY: dict[str, str] = {
    keyword: category
    for pool in (GADGET_KEYWORDS, STAPLE_KEYWORDS)
    for category, keywords in pool.items()
    for keyword in keywords
}

GADGET_KEYWORD_SET = {keyword for keywords in GADGET_KEYWORDS.values() for keyword in keywords}


def is_gadget_keyword(keyword: str) -> bool:
    return keyword in GADGET_KEYWORD_SET


# Wow factor (1-10) by where a product came from: the keyword curation is what
# makes a product cool; the model only checks the product really is that thing.
GADGET_WOW = 8
STAPLE_WOW = 4


def keyword_wow(keyword: str) -> int | None:
    if keyword in GADGET_KEYWORD_SET:
        return GADGET_WOW
    if keyword in KEYWORD_CATEGORY:
        return STAPLE_WOW
    return None


def sample_keywords(count: int, staple_share: float, avoid: set[str] | None = None) -> list[str]:
    """
    Random keywords for one discovery run, spread across categories.
    Keywords in `avoid` (recently posted) are used only if nothing else is left.
    """
    avoid = avoid or set()
    staples = [kw for keywords in STAPLE_KEYWORDS.values() for kw in keywords]
    gadgets = list(GADGET_KEYWORD_SET)

    def pick(pool: list[str], n: int) -> list[str]:
        fresh = [kw for kw in pool if kw not in avoid]
        random.shuffle(fresh)
        if len(fresh) < n:
            stale = [kw for kw in pool if kw in avoid]
            random.shuffle(stale)
            fresh.extend(stale)
        return fresh[:n]

    staple_count = round(count * staple_share)
    return pick(gadgets, count - staple_count) + pick(staples, staple_count)
