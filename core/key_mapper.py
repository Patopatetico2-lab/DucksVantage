"""
Mapeador Universal de Teclas e Códigos evdev <-> Atalhos (core/key_mapper.py).
Fonte única de verdade para tradução, sanitização e correspondência de modificadores
entre dispositivos Linux `/dev/input/event*` e rótulos/atalhos Qt.
"""

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

MODIFIER_ORDER: Tuple[str, ...] = ("Ctrl", "Alt", "Meta", "Shift")

MODIFIER_EVDEV_MAP: Dict[int, str] = {
    29: "Ctrl",   # KEY_LEFTCTRL
    97: "Ctrl",   # KEY_RIGHTCTRL
    56: "Alt",    # KEY_LEFTALT
    100: "Alt",   # KEY_RIGHTALT
    42: "Shift",  # KEY_LEFTSHIFT
    54: "Shift",  # KEY_RIGHTSHIFT
    125: "Meta",  # KEY_LEFTMETA
    126: "Meta",  # KEY_RIGHTMETA
}

_MODIFIER_ALIAS_MAP: Dict[str, str] = {
    "ctrl": "Ctrl",
    "control": "Ctrl",
    "lctrl": "Ctrl",
    "rctrl": "Ctrl",
    "alt": "Alt",
    "lalt": "Alt",
    "ralt": "Alt",
    "meta": "Meta",
    "super": "Meta",
    "win": "Meta",
    "cmd": "Meta",
    "shift": "Shift",
    "lshift": "Shift",
    "rshift": "Shift",
}

EVDEV_CODE_TO_NAME: Dict[int, str] = {
    # Dígitos linha superior
    2: "1", 3: "2", 4: "3", 5: "4", 6: "5", 7: "6", 8: "7", 9: "8", 10: "9", 11: "0",
    # Teclas de navegação / edição
    14: "Backspace", 15: "Tab", 28: "Return", 57: "Space",
    70: "ScrollLock", 99: "Print", 102: "Home", 104: "PgUp",
    107: "End", 109: "PgDown", 110: "Insert", 111: "Delete", 119: "Pause",
    # Letras QWERTY (códigos padrão Linux evdev)
    16: "Q", 17: "W", 18: "E", 19: "R", 20: "T", 21: "Y", 22: "U", 23: "I", 24: "O", 25: "P",
    30: "A", 31: "S", 32: "D", 33: "F", 34: "G", 35: "H", 36: "J", 37: "K", 38: "L",
    44: "Z", 45: "X", 46: "C", 47: "V", 48: "B", 49: "N", 50: "M",
    # F1..F12
    59: "F1", 60: "F2", 61: "F3", 62: "F4", 63: "F5",
    64: "F6", 65: "F7", 66: "F8", 67: "F9", 68: "F10",
    87: "F11", 88: "F12",
    # F13..F24
    183: "F13", 184: "F14", 185: "F15", 186: "F16", 187: "F17", 188: "F18",
    189: "F19", 190: "F20", 191: "F21", 192: "F22", 193: "F23", 194: "F24",
    # Teclas especiais Lenovo / ACPI / Ideapad
    148: "Prog1",
    149: "Prog2",
    156: "Bookmarks",
    171: "Config",
    202: "Prog3",
    203: "Prog4",
    248: "MicMute",
    364: "Favorites",
    431: "Fn+R (Display)",
    562: "Fn+R (Refresh)",
    583: "Assistant",
    634: "Screenshot",
}

NAME_TO_EVDEV_CODE: Dict[str, int] = {
    name.lower(): code for code, name in EVDEV_CODE_TO_NAME.items()
}
NAME_TO_EVDEV_CODE.update({
    "enter": 28,
    "del": 111,
    "ins": 110,
    "pageup": 104,
    "pagedown": 109,
    "pgup": 104,
    "pgdown": 109,
    "prtsc": 99,
    "printscreen": 99,
    "xf86assistant": 583,
    "copilot": 193,
    "key_assistant": 583,
    "key_refresh_rate_toggle": 562,
    "key_displaytoggle": 431,
})

_SPECIAL_LABEL_PREFIXES = ("Key_",)


def normalize_modifiers(mods: Optional[Iterable[str]]) -> List[str]:
    """Normaliza nomes de modificadores e os ordena em MODIFIER_ORDER."""
    if not mods:
        return []
    found: Set[str] = set()
    for raw in mods:
        token = str(raw or "").strip().lower()
        canonical = _MODIFIER_ALIAS_MAP.get(token)
        if canonical:
            found.add(canonical)
    return [m for m in MODIFIER_ORDER if m in found]


def format_shortcut(evdev_code: int, modifiers: Optional[Iterable[str]] = ()) -> str:
    """Formata um código evdev + modificadores em texto amigável (ex: 'Meta+Shift+F23')."""
    if not evdev_code or int(evdev_code) <= 0:
        return ""
    code = int(evdev_code)
    key_name = EVDEV_CODE_TO_NAME.get(code, f"Key_{code}")
    norm_mods = normalize_modifiers(modifiers)
    if norm_mods:
        return "+".join([*norm_mods, key_name])
    return key_name


def is_valid_shortcut(shortcut: Optional[str]) -> bool:
    """Rejeita strings vazias, terminadas em '+' (ex: 'Meta+Shift+') ou só modificadores."""
    if not shortcut:
        return False
    s = str(shortcut).strip()
    if not s or s.endswith("+") or s.startswith("+"):
        return False
    lower = s.lower()
    if lower in NAME_TO_EVDEV_CODE:
        return True
    parts = [p.strip() for p in s.split("+")]
    if any(not p for p in parts):
        return False
    # Verifica se há pelo menos uma tecla principal que não seja modificador
    non_mods = [p for p in parts if p.lower() not in _MODIFIER_ALIAS_MAP]
    return len(non_mods) >= 1


def parse_shortcut_to_evdev(shortcut: Optional[str]) -> Tuple[int, List[str]]:
    """Converte string de atalho válida em (evdev_code, normalized_modifiers)."""
    if not is_valid_shortcut(shortcut):
        return 0, []
    s = str(shortcut).strip()
    lower = s.lower()
    if lower in NAME_TO_EVDEV_CODE:
        return NAME_TO_EVDEV_CODE[lower], []

    parts = [p.strip() for p in s.split("+")]
    raw_mods: List[str] = []
    key_token = ""
    for part in parts:
        pl = part.lower()
        if pl in _MODIFIER_ALIAS_MAP:
            raw_mods.append(_MODIFIER_ALIAS_MAP[pl])
        else:
            key_token = part

    if not key_token:
        return 0, []

    kl = key_token.lower()
    code = NAME_TO_EVDEV_CODE.get(kl, 0)
    if code == 0 and key_token.startswith("Key_"):
        try:
            parsed_num = int(key_token[4:])
            if parsed_num > 0:
                code = parsed_num
        except ValueError:
            code = 0

    return code, normalize_modifiers(raw_mods)


def default_extra_codes_for_slot(slot_id: str, qt_shortcut: str, evdev_code: int) -> List[int]:
    """Retorna códigos evdev extras de hardware Lenovo associados ao slot/tecla."""
    code = int(evdev_code or 0)
    qt_low = str(qt_shortcut or "").strip().lower()
    if code == 193:
        return [583]
    if slot_id == "refresh_rate_hotkey" and qt_low in ("alt+r", "fn+r (refresh)", "fn+r (display)"):
        return [562, 431]
    return []


def sanitize_key_mapping_slot(
    slot_id: str,
    cfg: Optional[Dict[str, Any]],
    default_cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Higieniza um slot de mapeamento, reparando strings quebradas (como 'Meta+Shift+')
    e sincronizando `evdev_code`, `evdev_modifiers` e `extra_evdev_codes`.
    """
    base: Dict[str, Any] = dict(default_cfg or {})
    if isinstance(cfg, dict):
        base.update(cfg)

    raw_qt = str(base.get("qt_shortcut", "") or "").strip()
    try:
        raw_code = int(base.get("evdev_code", 0) or 0)
    except (TypeError, ValueError):
        raw_code = 0

    if not is_valid_shortcut(raw_qt):
        if slot_id == "copilot_key" or raw_code == 193:
            base["qt_shortcut"] = "Meta+Shift+F23"
            base["evdev_code"] = 193
            base["evdev_modifiers"] = ["Meta", "Shift"]
            base["extra_evdev_codes"] = [583]
        elif default_cfg:
            base["qt_shortcut"] = str(default_cfg.get("qt_shortcut", ""))
            base["evdev_code"] = int(default_cfg.get("evdev_code", 0) or 0)
            base["evdev_modifiers"] = normalize_modifiers(default_cfg.get("evdev_modifiers", []))
            base["extra_evdev_codes"] = list(default_cfg.get("extra_evdev_codes", []))
        else:
            base["qt_shortcut"] = format_shortcut(raw_code, base.get("evdev_modifiers", [])) if raw_code > 0 else ""
            base["evdev_code"] = raw_code
            base["evdev_modifiers"] = normalize_modifiers(base.get("evdev_modifiers", []))
            base["extra_evdev_codes"] = default_extra_codes_for_slot(slot_id, base["qt_shortcut"], raw_code)
    else:
        parsed_code, parsed_mods = parse_shortcut_to_evdev(raw_qt)
        if parsed_code > 0:
            base["evdev_code"] = parsed_code
            base["evdev_modifiers"] = parsed_mods
        else:
            base["evdev_code"] = raw_code
            base["evdev_modifiers"] = normalize_modifiers(base.get("evdev_modifiers", []))

        existing_extras = base.get("extra_evdev_codes")
        computed_extras = default_extra_codes_for_slot(
            slot_id,
            raw_qt,
            int(base.get("evdev_code", 0) or 0),
        )
        if existing_extras is None or (slot_id == "refresh_rate_hotkey" and existing_extras == [431]):
            base["extra_evdev_codes"] = computed_extras
        else:
            cleaned_extras: List[int] = []
            for item in existing_extras:
                try:
                    val = int(item)
                    if val > 0 and val not in cleaned_extras:
                        cleaned_extras.append(val)
                except (TypeError, ValueError):
                    continue
            if not cleaned_extras and computed_extras:
                cleaned_extras = computed_extras
            base["extra_evdev_codes"] = cleaned_extras

    base["enabled"] = bool(base.get("enabled", True))
    base["action"] = str(base.get("action", (default_cfg or {}).get("action", "cycle_profile")))
    base["custom_command"] = str(base.get("custom_command", "") or "")
    if "label" not in base and default_cfg and "label" in default_cfg:
        base["label"] = default_cfg["label"]
    return base


def matches_evdev_trigger(cfg: Dict[str, Any], ev_code: int, held_mods: Set[str]) -> bool:
    """Verifica se o evento evdev (código + modificadores pressionados) aciona o slot."""
    if not isinstance(cfg, dict) or not cfg.get("enabled", True):
        return False

    code = int(ev_code or 0)
    if code <= 0:
        return False

    try:
        primary_code = int(cfg.get("evdev_code", 0) or 0)
    except (TypeError, ValueError):
        primary_code = 0

    req_mods = set(normalize_modifiers(cfg.get("evdev_modifiers", [])))

    if primary_code > 0 and code == primary_code:
        # KEY_F23 (193) pode chegar como F23 puro ou como Meta+Shift+F23 (tecla Copilot física)
        if primary_code == 193 and req_mods in (set(), {"Meta", "Shift"}):
            return held_mods in (set(), {"Meta", "Shift"})
        return held_mods == req_mods

    extra_codes = cfg.get("extra_evdev_codes") or []
    try:
        extra_set = {int(c) for c in extra_codes if int(c) > 0}
    except (TypeError, ValueError):
        extra_set = set()

    if code in extra_set:
        return held_mods in (set(), {"Meta", "Shift"})

    return False
