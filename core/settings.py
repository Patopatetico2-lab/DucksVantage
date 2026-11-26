"""
Gerenciador de Configurações, Mapeamento de Teclas e Histórico de Bateria do Ducksvantage (core/settings.py)
Salva e recupera as preferências do usuário em ~/.config/ducksvantage/settings.json.
"""

import os
import json
import tempfile
from typing import Any, Dict, Tuple
from core.key_mapper import sanitize_key_mapping_slot

CONFIG_DIR = os.path.expanduser("~/.config/ducksvantage")
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")
LEGACY_CONFIG_FILE = os.path.expanduser("~/.config/lenovo-loq-control/settings.json")

DEFAULT_KEY_MAPPINGS: Dict[str, Dict[str, Any]] = {
    "copilot_key": {
        "label": "Tecla Copilot (F8 / Meta+Shift+F23)",
        "qt_shortcut": "Meta+Shift+F23",
        "evdev_code": 193,
        "evdev_modifiers": ["Meta", "Shift"],
        "extra_evdev_codes": [583],  # KEY_ASSISTANT
        "action": "cycle_profile",
        "custom_command": "",
        "enabled": True,
    },
    "special_launch": {
        "label": "Tecla Especial / Extra (F24)",
        "qt_shortcut": "F24",
        "evdev_code": 194,
        "evdev_modifiers": [],
        "extra_evdev_codes": [],
        "action": "toggle_max_power",
        "custom_command": "",
        "enabled": True,
    },
    "eco_hotkey": {
        "label": "Atalho Rápido Eco-Mode (Ctrl+Alt+E)",
        "qt_shortcut": "Ctrl+Alt+E",
        "evdev_code": 18,  # KEY_E
        "evdev_modifiers": ["Ctrl", "Alt"],
        "extra_evdev_codes": [],
        "action": "toggle_eco_mode",
        "custom_command": "",
        "enabled": True,
    },
    "refresh_rate_hotkey": {
        "label": "Taxa de Atualização de Tela (Fn+R / Alt+R)",
        "qt_shortcut": "Alt+R",
        "evdev_code": 19,  # KEY_R
        "evdev_modifiers": ["Alt"],
        "extra_evdev_codes": [562, 431],  # KEY_REFRESH_RATE_TOGGLE / KEY_DISPLAYTOGGLE (Fn+R)
        "action": "cycle_refresh_rate",
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
    "game_target_preset_id": "",
    "game_ignore_list": [],
    "game_auto_refresh_max": False,
    "game_auto_lock_touchpad": False,
    "game_auto_wifi_low_latency": False,
    "game_vrr_policy": "keep",
    "game_session_history": [],
    "dock_mode_enabled": False,
    "dock_target_profile": "performance",
    "dock_keep_max_hz": True,
    "dock_inhibit_lid_sleep": False,
    "usb_wakeup_blocked": False,
    "one_time_full_charge_active": False,
    "one_time_full_charge_mode": "until_full",
    "one_time_full_charge_until_ts": 0.0,
    "eco_dim_brightness_enabled": True,
    "eco_brightness_pct": 40,
    "pre_eco_brightness_pct": 75,
    "eco_action_profile": True,
    "eco_action_conservation": True,
    "eco_action_turbo_off": True,
    "eco_action_tdp_limit": True,
    "eco_action_gpu_d3cold": True,
    "eco_action_kbd_off": True,
    "eco_action_refresh_min": False,
    "eco_action_wifi_save": False,
    "eco_applied_actions": [],
    "pre_eco_conservation": False,
    "pre_eco_tdp": [],
    "pre_eco_refresh_hz": 0,
    "pre_eco_wifi_power_save": True,
    "nvme_temp_alert_c": 68.0,
    "eco_travel_mode": False,
    "ac_profile": "performance",
    "battery_profile": "low-power",
    "rapid_charge": False,
    "touchpad_locked": False,
    "osd_enabled": True,
    "osd_position": "bottom-center",
    "osd_duration_ms": 1800,
    "minimize_to_tray": True,
    "ui_mode": "basic",
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
    "battery_alerts_enabled": True,
    "battery_temp_alert_c": 42.0,
    "battery_80_alert_enabled": True,
    "battery_temp_alert_enabled": True,
    "gpu_mux_mode": "hybrid",
    "auto_refresh_rate_transition": True,
    "last_refresh_rate": 60,
    "key_mappings": DEFAULT_KEY_MAPPINGS,
    "user_presets": [],
    "rgb_mode": "static",
    "rgb_brightness": 2,
    "rgb_speed": 2,
    "rgb_zones": ["#00d2ff", "#00d2ff", "#00d2ff", "#00d2ff"],
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
                repaired = False
                if not isinstance(km, dict) or not km:
                    self._data["key_mappings"] = json.loads(json.dumps(DEFAULT_KEY_MAPPINGS))
                    repaired = True
                else:
                    for slot_id in list(km.keys()):
                        sanitized = sanitize_key_mapping_slot(
                            slot_id, km.get(slot_id), DEFAULT_KEY_MAPPINGS.get(slot_id)
                        )
                        if sanitized != km.get(slot_id):
                            km[slot_id] = sanitized
                            repaired = True
                    for def_k, def_v in DEFAULT_KEY_MAPPINGS.items():
                        if def_k not in km:
                            km[def_k] = json.loads(json.dumps(def_v))
                            repaired = True
                if (target == LEGACY_CONFIG_FILE and not os.path.exists(CONFIG_FILE)) or repaired:
                    self.save()
            except Exception as e:
                print(f"[Aviso] Falha ao ler configurações: {e}")

    def save(self):
        """Grava as configurações no disco em formato JSON de forma atômica e segura."""
        for target_dir, target_file in (
            (CONFIG_DIR, CONFIG_FILE),
            ("/tmp/ducksvantage", "/tmp/ducksvantage/settings.json"),
        ):
            try:
                os.makedirs(target_dir, exist_ok=True)
                tmp_fd, tmp_path = tempfile.mkstemp(
                    dir=target_dir,
                    prefix=".settings_",
                    suffix=".tmp"
                )
                try:
                    with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                        json.dump(self._data, f, indent=4, ensure_ascii=False)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_path, target_file)
                    return
                except Exception:
                    try:
                        os.close(tmp_fd)
                    except Exception:
                        pass
                    if os.path.exists(tmp_path):
                        try:
                            os.remove(tmp_path)
                        except Exception:
                            pass
                    raise
            except Exception:
                continue

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any):
        self._data[key] = value
        self.save()

    def export_to_file(self, dst_path: str) -> Tuple[bool, str]:
        """Exporta as configurações atuais para um arquivo JSON de backup."""
        if not dst_path:
            return False, "Caminho de destino inválido."
        try:
            parent = os.path.dirname(os.path.abspath(dst_path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(dst_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=4, ensure_ascii=False)
            return True, f"Backup exportado com sucesso para {os.path.basename(dst_path)}."
        except Exception as e:
            return False, f"Falha ao exportar backup: {e}"

    def import_from_file(self, src_path: str) -> Tuple[bool, str]:
        """Importa configurações de um arquivo JSON validando apenas chaves conhecidas."""
        if not src_path or not os.path.exists(src_path):
            return False, "Arquivo de backup não encontrado."
        try:
            with open(src_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                return False, "Formato de backup inválido (esperado objeto JSON)."

            accepted = 0
            for k, v in loaded.items():
                if k in DEFAULT_SETTINGS:
                    self._data[k] = v
                    accepted += 1

            if accepted == 0:
                return False, "Nenhuma configuração válida do Ducksvantage foi encontrada no arquivo."

            km = self._data.get("key_mappings")
            if not isinstance(km, dict) or not km:
                self._data["key_mappings"] = json.loads(json.dumps(DEFAULT_SETTINGS["key_mappings"]))
            else:
                for slot_id in list(km.keys()):
                    km[slot_id] = sanitize_key_mapping_slot(
                        slot_id, km.get(slot_id), DEFAULT_KEY_MAPPINGS.get(slot_id)
                    )
                for def_k, def_v in DEFAULT_KEY_MAPPINGS.items():
                    if def_k not in km:
                        km[def_k] = json.loads(json.dumps(def_v))

            self.save()
            return True, f"{accepted} configurações importadas com sucesso."
        except Exception as e:
            return False, f"Falha ao importar backup: {e}"
