"""
Gerenciador de Configurações, Mapeamento de Teclas e Histórico de Bateria do Ducksvantage (core/settings.py)
Salva e recupera as preferências do usuário em ~/.config/ducksvantage/settings.json.
"""

import os
import json
from typing import Any, Dict

CONFIG_DIR = os.path.expanduser("~/.config/ducksvantage")
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")
LEGACY_CONFIG_FILE = os.path.expanduser("~/.config/lenovo-loq-control/settings.json")

DEFAULT_KEY_MAPPINGS: Dict[str, Dict[str, Any]] = {
    "copilot_key": {
        "label": "Tecla Copilot (F23 / Meta+Shift+F23)",
        "qt_shortcut": "F23",
        "evdev_code": 193,
        "action": "cycle_profile",
        "custom_command": "",
        "enabled": True,
    },
    "special_launch": {
        "label": "Tecla Especial / Multimídia (F24)",
        "qt_shortcut": "F24",
        "evdev_code": 194,
        "action": "toggle_max_power",
        "custom_command": "",
        "enabled": True,
    },
    "eco_hotkey": {
        "label": "Atalho Rápido Eco-Mode (Ctrl+Alt+E)",
        "qt_shortcut": "Ctrl+Alt+E",
        "evdev_code": 0,
        "action": "toggle_eco_mode",
        "custom_command": "",
        "enabled": True,
    },
}

DEFAULT_APP_POWER_RULES = [
    {"executable": "blender", "label": "Blender 3D / Cycles Render", "profile": "max-power", "enabled": True},
    {"executable": "resolve", "label": "DaVinci Resolve Studio", "profile": "max-power", "enabled": True},
    {"executable": "kdenlive", "label": "Kdenlive Video Editor", "profile": "performance", "enabled": True},
    {"executable": "obs", "label": "OBS Studio Streaming", "profile": "performance", "enabled": True},
    {"executable": "code", "label": "VS Code / Compilação Pesada", "profile": "balanced", "enabled": False},
    {"executable": "firefox", "label": "Mozilla Firefox (Navegação Leve)", "profile": "low-power", "enabled": False},
]

DEFAULT_FAN_CURVE_POINTS = [
    [35, 0],
    [48, 25],
    [60, 45],
    [72, 70],
    [82, 90],
    [92, 100],
]

DEFAULT_SETTINGS: Dict[str, Any] = {
    "auto_power_transition": True,
    "game_auto_switch": True,
    "game_target_profile": "max-power",
    "eco_travel_mode": False,
    "ac_profile": "performance",
    "battery_profile": "low-power",
    "rapid_charge": False,
    "touchpad_locked": False,
    "osd_enabled": True,
    "minimize_to_tray": True,
    "custom_pl1_w": 45,
    "custom_pl2_w": 70,
    "custom_fan_curve_enabled": False,
    "custom_fan_curve_points": DEFAULT_FAN_CURVE_POINTS,
    "custom_cpu_temp_limit": 94,
    "custom_gpu_temp_limit": 87,
    "undervolt_core_mv": 0,
    "undervolt_cache_mv": 0,
    "gpu_ac_offset_w": 20,
    "app_power_rules": DEFAULT_APP_POWER_RULES,
    "wifi_low_latency_gaming": False,
    "eth_power_saving": True,
    "battery_alerts_enabled": True,
    "battery_temp_alert_c": 42.0,
    "battery_80_alert_enabled": True,
    "key_mappings": DEFAULT_KEY_MAPPINGS,
    "battery_history": []
}


class SettingsManager:
    """Carrega e persiste as configurações do usuário em ~/.config/ducksvantage/settings.json."""

    def __init__(self):
        self._data: Dict[str, Any] = json.loads(json.dumps(DEFAULT_SETTINGS))
        self.load()

    def load(self):
        """Carrega o arquivo JSON do disco se existir (com fallback de migração)."""
        target = CONFIG_FILE if os.path.exists(CONFIG_FILE) else (
            LEGACY_CONFIG_FILE if os.path.exists(LEGACY_CONFIG_FILE) else None
        )
        if target:
            try:
                with open(target, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        self._data.update(loaded)
                km = self._data.get("key_mappings")
                if not isinstance(km, dict) or not km:
                    self._data["key_mappings"] = json.loads(json.dumps(DEFAULT_KEY_MAPPINGS))
                if target == LEGACY_CONFIG_FILE and not os.path.exists(CONFIG_FILE):
                    self.save()
            except Exception as e:
                print(f"[Aviso] Falha ao ler configurações: {e}")

    def save(self):
        """Grava as configurações no disco em formato JSON identado."""
        for target_dir, target_file in (
            (CONFIG_DIR, CONFIG_FILE),
            ("/tmp/ducksvantage", "/tmp/ducksvantage/settings.json"),
        ):
            try:
                os.makedirs(target_dir, exist_ok=True)
                with open(target_file, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, indent=4, ensure_ascii=False)
                return
            except Exception:
                continue

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any):
        self._data[key] = value
        self.save()
