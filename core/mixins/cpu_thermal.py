"""Mixin de Controle Avançado de CPU, Curva de Ventoinhas, Undervolt Watchdog, Remapper e Modo Viagem."""

import datetime
import glob
import os
import shutil
import struct
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
from core.models import UndervoltStatus
from core.permissions import PermissionsManager
from core.settings import DEFAULT_FAN_CURVE_POINTS, DEFAULT_KEY_MAPPINGS
from core.key_mapper import sanitize_key_mapping_slot

UNDERVOLT_CANARY_FILE = os.path.expanduser("~/.config/ducksvantage/undervolt_canary.lock")
UNDERVOLT_CANARY_FALLBACK = "/tmp/ducksvantage/undervolt_canary.lock"
UNDERVOLT_CANARY_PATHS = (UNDERVOLT_CANARY_FILE, UNDERVOLT_CANARY_FALLBACK)


class CpuThermalUndervoltMixin:
    """Controles de Turbo, Governor, TDP PL1/PL2, Curva de Fans, Undervolt Seguro, Key Remapper e Eco Travel."""

    # =========================================================================
    # ELITE 4: Controles Avançados de CPU: Turbo Boost, Governor e Custom TDP (PL1/PL2)
    # =========================================================================
    def get_cpu_turbo(self) -> bool:
        """Retorna True se o Turbo Boost estiver ativo (suporta Intel P-State e AMD CPUFreq)."""
        if self.paths.cpu_turbo_intel:
            no_turbo = self._read_file_int(self.paths.cpu_turbo_intel, default=0)
            return no_turbo == 0
        if self.paths.cpu_turbo_amd:
            boost = self._read_file_int(self.paths.cpu_turbo_amd, default=1)
            return boost == 1
        return True

    def set_cpu_turbo(self, enable: bool, allow_elevation: bool = True) -> Tuple[bool, str]:
        """Ativa ou desativa o Turbo Boost do processador (Intel ou AMD)."""
        if self.paths.cpu_turbo_intel:
            target_val = "0" if enable else "1"
            return PermissionsManager.write_sysfs_value(self.paths.cpu_turbo_intel, target_val, allow_elevation=allow_elevation)
        if self.paths.cpu_turbo_amd:
            target_val = "1" if enable else "0"
            return PermissionsManager.write_sysfs_value(self.paths.cpu_turbo_amd, target_val, allow_elevation=allow_elevation)
        return False, "Controle de Turbo Boost não disponível para este processador."

    def get_cpu_governor(self) -> str:
        if self.paths.cpu_governor:
            return self._read_file_text(self.paths.cpu_governor) or "powersave"
        return "powersave"

    def get_available_cpu_governors(self) -> List[str]:
        if self.paths.cpu_available_governors:
            txt = self._read_file_text(self.paths.cpu_available_governors)
            if txt:
                return txt.split()
        if self.features.cpu_governor:
            return ["performance", "powersave"]
        return []

    def set_cpu_governor(self, governor: str, allow_elevation: bool = True) -> Tuple[bool, str]:
        return PermissionsManager.write_cpu_governor_all(governor, allow_elevation=allow_elevation)

    def get_cpu_tdp_limits(self) -> Tuple[int, int]:
        """Lê os limites atuais de potência PL1 (Sustentado) e PL2 (Boost) em Watts."""
        pl1_w = int(self.settings.get("custom_pl1_w", 45))
        pl2_w = int(self.settings.get("custom_pl2_w", 70))

        if self.paths.rapl_pl1:
            raw_pl1 = self._read_file_int(self.paths.rapl_pl1, 0)
            if raw_pl1 > 0:
                pl1_w = max(10, min(115, raw_pl1 // 1_000_000))
        if self.paths.rapl_pl2:
            raw_pl2 = self._read_file_int(self.paths.rapl_pl2, 0)
            if raw_pl2 > 0:
                pl2_w = max(15, min(135, raw_pl2 // 1_000_000))
        return pl1_w, pl2_w

    def set_cpu_tdp_limits(self, pl1_w: int, pl2_w: int, allow_elevation: bool = True) -> Tuple[bool, str]:
        """Define os limites de TDP PL1 (Long Term) e PL2 (Short Term) em Watts via Intel RAPL."""
        pl1_w = max(10, min(95, int(pl1_w)))
        pl2_w = max(pl1_w, min(115, int(pl2_w)))

        self.settings.set("custom_pl1_w", pl1_w)
        self.settings.set("custom_pl2_w", pl2_w)

        if not self.paths.rapl_pl1 or not self.paths.rapl_pl2:
            return False, "Interface RAPL de controle de TDP não encontrada neste processador."

        pl1_uw = str(pl1_w * 1_000_000)
        pl2_uw = str(pl2_w * 1_000_000)

        pairs = [
            (self.paths.rapl_pl1, pl1_uw),
            (self.paths.rapl_pl2, pl2_uw),
        ]
        if self.paths.rapl_mmio_pl1 and self.paths.rapl_mmio_pl2:
            pairs.append((self.paths.rapl_mmio_pl1, pl1_uw))
            pairs.append((self.paths.rapl_mmio_pl2, pl2_uw))

        ok, msg = PermissionsManager.write_multiple_sysfs_values(pairs, allow_elevation=allow_elevation)
        if ok:
            return True, f"Limites TDP aplicados com sucesso: PL1 = {pl1_w}W | PL2 = {pl2_w}W."
        return False, msg

    # =========================================================================
    # ELITE 5: Mapeador de Teclas Personalizadas (Tecla Copilot F8/F23 & Atalhos)
    # =========================================================================
    def get_key_mappings(self) -> Dict[str, Dict[str, Any]]:
        mappings = self.settings.get("key_mappings", {})
        if not isinstance(mappings, dict):
            return {}
        sanitized: Dict[str, Dict[str, Any]] = {}
        for slot_id, cfg in mappings.items():
            sanitized[slot_id] = sanitize_key_mapping_slot(
                slot_id, cfg if isinstance(cfg, dict) else {}, DEFAULT_KEY_MAPPINGS.get(slot_id)
            )
        return sanitized

    def update_key_mapping(self, slot_id: str, slot_data: Dict[str, Any]) -> None:
        mappings = self.get_key_mappings()
        mappings[slot_id] = sanitize_key_mapping_slot(
            slot_id, slot_data, DEFAULT_KEY_MAPPINGS.get(slot_id)
        )
        self.settings.set("key_mappings", mappings)

    def reset_key_mappings_to_default(self) -> Dict[str, Dict[str, Any]]:
        """Restaura todos os slots do Mapeador de Teclas para os padrões de fábrica."""
        import json
        defaults = json.loads(json.dumps(DEFAULT_KEY_MAPPINGS))
        sanitized: Dict[str, Dict[str, Any]] = {}
        for slot_id, cfg in defaults.items():
            sanitized[slot_id] = sanitize_key_mapping_slot(slot_id, cfg, cfg)
        self.settings.set("key_mappings", sanitized)
        return sanitized

    def toggle_microphone_mute(self) -> Tuple[bool, str]:
        """Alterna o mudo do microfone via PipeWire (wpctl) ou PulseAudio (pactl)."""
        if shutil.which("wpctl"):
            try:
                subprocess.run(
                    ["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"],
                    capture_output=True, timeout=2
                )
                res = subprocess.run(
                    ["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"],
                    capture_output=True, text=True, timeout=2
                )
                muted = "MUTED" in (res.stdout or "").upper()
                return True, f"Microfone {'Silenciado (Mudo)' if muted else 'Ativado'}"
            except Exception:
                pass
        if shutil.which("pactl"):
            try:
                subprocess.run(
                    ["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "toggle"],
                    capture_output=True, timeout=2
                )
                return True, "Estado do Microfone alternado"
            except Exception:
                pass
        return False, "Utilitário de áudio (wpctl/pactl) não encontrado."

    def execute_mapped_action(self, action_id: str, custom_cmd: str = "") -> Dict[str, Any]:
        """Executa a ação configurada para uma tecla mapeada e retorna metadados para o OSD."""
        if action_id == "cycle_profile":
            ok, new_prof = self.cycle_next_profile()
            return {"action": action_id, "ok": ok, "osd_type": "profile", "value": new_prof}

        if action_id == "cycle_refresh_rate":
            ok, new_hz, msg = self.cycle_refresh_rate()
            return {
                "action": action_id,
                "ok": ok,
                "osd_type": "refresh_rate",
                "hz": new_hz,
                "title": f"Taxa de Atualização: {new_hz} Hz",
                "subtitle": "Fn + R • Painel de Vídeo",
                "icon": "refresh.svg",
                "accent": "#60a5fa" if new_hz > 60 else "#34d399"
            }

        if action_id == "toggle_max_power":
            choices = self.get_platform_profile_choices()
            high_prof = "max-power" if "max-power" in choices else "performance"
            cur = self.get_platform_profile().lower().strip()
            target = "balanced" if cur == high_prof else high_prof
            ok, _ = self.set_platform_profile(target)
            return {"action": action_id, "ok": ok, "osd_type": "profile", "value": target}

        if action_id == "toggle_eco_mode":
            new_state = not self.get_eco_travel_mode()
            ok, msg = self.set_eco_travel_mode(new_state)
            return {
                "action": action_id,
                "ok": ok,
                "osd_type": "feature",
                "title": "Modo Viagem (Eco-Mode Extremo)" if new_state else "Modo Viagem Desativado",
                "subtitle": "Conservação 80% • GPU D3cold • Turbo Off • Low Power" if new_state else "Desempenho Padrão Restaurado",
                "icon": "eco_travel.svg",
                "accent": "#34d399" if new_state else "#60a5fa"
            }

        if action_id == "toggle_conservation":
            new_state = not self.get_conservation_mode()
            ok, _ = self.set_conservation_mode(new_state)
            return {
                "action": action_id,
                "ok": ok,
                "osd_type": "feature",
                "title": f"Conservação da Bateria: {'Ativado (80%)' if new_state else 'Desativado (100%)'}",
                "subtitle": "Proteção contra degradação química",
                "icon": "edge_conservation.svg",
                "accent": "#34d399" if new_state else "#94a3b8"
            }

        if action_id == "toggle_mic_mute":
            ok, label = self.toggle_microphone_mute()
            return {
                "action": action_id,
                "ok": ok,
                "osd_type": "feature",
                "title": label,
                "subtitle": "Atalho Rápido de Áudio Ducksvantage",
                "icon": "copilot_key.svg",
                "accent": "#60a5fa"
            }

        if action_id == "toggle_touchpad":
            new_state = not self.get_touchpad_status()
            ok, _ = self.set_touchpad_status(new_state)
            return {
                "action": action_id,
                "ok": ok,
                "osd_type": "feature",
                "title": f"Touchpad: {'Bloqueado' if new_state else 'Desbloqueado'}",
                "subtitle": "Controle de Dispositivo de Entrada",
                "icon": "edge_touchpad.svg",
                "accent": "#fbbf24" if new_state else "#34d399"
            }

        if action_id == "custom_command" and custom_cmd.strip():
            try:
                subprocess.Popen(
                    custom_cmd.strip(),
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return {
                    "action": action_id,
                    "ok": True,
                    "osd_type": "feature",
                    "title": "Comando Personalizado Executado",
                    "subtitle": custom_cmd.strip()[:48],
                    "icon": "copilot_key.svg",
                    "accent": "#a78bfa"
                }
            except Exception as e:
                return {"action": action_id, "ok": False, "error": str(e)}

        # Default ou toggle_window
        return {"action": "toggle_window", "ok": True, "osd_type": "window"}

    # =========================================================================
    # ELITE 6: Modo Viagem / Eco-Mode Extremo (1-Clique & Configurável)
    # =========================================================================
    def get_eco_travel_mode(self) -> bool:
        return bool(self.settings.get("eco_travel_mode", False))

    def get_eco_travel_config(self) -> Dict[str, Any]:
        """Retorna todas as ações configuráveis do Modo Viagem/Economia e o brilho alvo."""
        return {
            "profile": bool(self.settings.get("eco_action_profile", True)),
            "conservation": bool(self.settings.get("eco_action_conservation", True)),
            "turbo_off": bool(self.settings.get("eco_action_turbo_off", True)),
            "tdp_limit": bool(self.settings.get("eco_action_tdp_limit", True)),
            "gpu_d3cold": bool(self.settings.get("eco_action_gpu_d3cold", True)),
            "kbd_off": bool(self.settings.get("eco_action_kbd_off", True)),
            "refresh_min": bool(self.settings.get("eco_action_refresh_min", False)),
            "wifi_save": bool(self.settings.get("eco_action_wifi_save", False)),
            "dim_brightness": bool(self.settings.get("eco_dim_brightness_enabled", True)),
            "brightness_pct": max(5, min(100, int(self.settings.get("eco_brightness_pct", 40) or 40))),
        }

    def set_eco_travel_config(self, **kwargs: Any) -> None:
        """Persiste quais ações o Modo Viagem/Economia está autorizado a alterar."""
        key_map = {
            "profile": "eco_action_profile",
            "conservation": "eco_action_conservation",
            "turbo_off": "eco_action_turbo_off",
            "tdp_limit": "eco_action_tdp_limit",
            "gpu_d3cold": "eco_action_gpu_d3cold",
            "kbd_off": "eco_action_kbd_off",
            "refresh_min": "eco_action_refresh_min",
            "wifi_save": "eco_action_wifi_save",
            "dim_brightness": "eco_dim_brightness_enabled",
        }
        batch: Dict[str, Any] = {}
        for arg_name, setting_key in key_map.items():
            if arg_name in kwargs:
                batch[setting_key] = bool(kwargs[arg_name])
        if "brightness_pct" in kwargs:
            batch["eco_brightness_pct"] = max(5, min(100, int(kwargs["brightness_pct"])))
        if batch:
            self.settings.update_many(batch)

    def _restore_eco_side_effects(self, restore_profile: bool = True) -> Tuple[bool, str]:
        """Restaura exatamente o estado salvo antes da ativação do Modo Viagem."""
        if getattr(self, "_restoring_eco_mode", False):
            return True, ""
        self._restoring_eco_mode = True
        try:
            raw_applied = self.settings.get("eco_applied_actions", [])
            if isinstance(raw_applied, list) and raw_applied:
                applied = {str(x) for x in raw_applied}
            else:
                cfg = self.get_eco_travel_config()
                applied = {
                    k for k in ("profile", "conservation", "turbo_off", "tdp_limit", "kbd_off", "dim_brightness")
                    if cfg.get(k, False)
                }

            pairs: List[Tuple[str, str]] = []
            prev_prof = self.normalize_profile(str(self.settings.get("pre_eco_profile", "balanced")))
            if prev_prof == "low-power":
                prev_prof = "balanced"
            prev_gov = str(self.settings.get("pre_eco_governor", "") or "").strip()
            prev_kbd = int(self.settings.get("pre_eco_kbd", 1))
            prev_turbo = bool(self.settings.get("pre_eco_turbo", True))
            prev_cons = bool(self.settings.get("pre_eco_conservation", False))

            if restore_profile and "profile" in applied and self.paths.platform_profile:
                pairs.append((self.paths.platform_profile, prev_prof))

            if "conservation" in applied and self.paths.conservation_mode:
                pairs.append((self.paths.conservation_mode, "1" if prev_cons else "0"))

            if "turbo_off" in applied:
                if self.paths.cpu_turbo_intel:
                    pairs.append((self.paths.cpu_turbo_intel, "0" if prev_turbo else "1"))
                elif self.paths.cpu_turbo_amd:
                    pairs.append((self.paths.cpu_turbo_amd, "1" if prev_turbo else "0"))

            if "kbd_off" in applied and self.paths.kbd_backlight:
                pairs.append((self.paths.kbd_backlight, str(prev_kbd)))

            if "tdp_limit" in applied and self.paths.rapl_pl1 and self.paths.rapl_pl2:
                saved_tdp = self.settings.get("pre_eco_tdp", [])
                if isinstance(saved_tdp, list) and len(saved_tdp) >= 2:
                    pl1_def, pl2_def = int(saved_tdp[0]), int(saved_tdp[1])
                else:
                    pl1_def = int(self.settings.get("custom_pl1_w", 45))
                    pl2_def = int(self.settings.get("custom_pl2_w", 70))
                pairs.append((self.paths.rapl_pl1, str(pl1_def * 1_000_000)))
                pairs.append((self.paths.rapl_pl2, str(pl2_def * 1_000_000)))
                if self.paths.rapl_mmio_pl1 and self.paths.rapl_mmio_pl2:
                    pairs.append((self.paths.rapl_mmio_pl1, str(pl1_def * 1_000_000)))
                    pairs.append((self.paths.rapl_mmio_pl2, str(pl2_def * 1_000_000)))

            ok, msg = PermissionsManager.write_multiple_sysfs_values(pairs) if pairs else (True, "")

            if "profile" in applied and self.features.cpu_governor and prev_gov:
                avail_govs = self.get_available_cpu_governors()
                if prev_gov in avail_govs:
                    self.set_cpu_governor(prev_gov, allow_elevation=False)

            if restore_profile and "profile" in applied:
                self._sync_cpu_epp_for_profile(prev_prof)

            if "refresh_min" in applied and self.features.refresh_rate:
                prev_hz = int(self.settings.get("pre_eco_refresh_hz", 0) or 0)
                if prev_hz > 0:
                    try:
                        self.set_refresh_rate(prev_hz)
                    except Exception:
                        pass

            if "wifi_save" in applied and self.features.wifi_power_save:
                prev_wf = bool(self.settings.get("pre_eco_wifi_power_save", False))
                try:
                    self.set_wifi_power_saving(prev_wf, allow_elevation=False)
                except Exception:
                    pass

            if "dim_brightness" in applied and self.features.screen_brightness:
                prev_br = int(self.settings.get("pre_eco_brightness_pct", 75) or 75)
                ok_br, msg_br = self.set_screen_brightness_pct(prev_br, allow_elevation=False)
                if not ok_br and not pairs:
                    ok, msg = False, msg_br

            self.settings.update_many({
                "eco_applied_actions": [],
                "eco_travel_mode": False,
                "pre_eco_governor": "",
            })
            if restore_profile and ok and "profile" in applied:
                self._max_power_active = (prev_prof == "max-power")
                self._last_raw_profile = self._read_raw_platform_profile()
                self._last_profile = prev_prof
                self._sync_platform_profile_cache(self._last_raw_profile)
            if "conservation" in applied and ok:
                self._last_conservation = prev_cons
            if "kbd_off" in applied and ok:
                self._last_kbd_bright = prev_kbd
            return ok, msg
        finally:
            self._restoring_eco_mode = False

    def set_eco_travel_mode(self, enable: bool) -> Tuple[bool, str]:
        """
        Ativa/desativa o 'Modo Viagem (Eco-Mode Extremo)' aplicando apenas as opções
        habilitadas pelo usuário em get_eco_travel_config() e restaurando exatamente
        o estado original ao desativar.
        """
        if enable:
            if self.get_eco_travel_mode():
                return True, "Modo Viagem (Eco-Mode Extremo) já está ativo."

            cfg = self.get_eco_travel_config()
            pairs: List[Tuple[str, str]] = []
            applied: List[str] = []

            if cfg["conservation"] and self.paths.conservation_mode:
                self.settings.set("pre_eco_conservation", bool(self.get_conservation_mode()))
                pairs.append((self.paths.conservation_mode, "1"))
                self.settings.set("rapid_charge", False)
                applied.append("conservation")

            if cfg["profile"] and (self.paths.platform_profile or self.features.cpu_governor):
                self.settings.set("pre_eco_profile", self.get_platform_profile())
                if self.features.cpu_governor:
                    self.settings.set("pre_eco_governor", self.get_cpu_governor())
                if self.paths.platform_profile:
                    choices = self.get_platform_profile_choices()
                    if choices:
                        low_p = "low-power" if "low-power" in choices else ("quiet" if "quiet" in choices else choices[0])
                        pairs.append((self.paths.platform_profile, low_p))
                applied.append("profile")

            if cfg["turbo_off"] and (self.paths.cpu_turbo_intel or self.paths.cpu_turbo_amd):
                self.settings.set("pre_eco_turbo", self.get_cpu_turbo())
                if self.paths.cpu_turbo_intel:
                    pairs.append((self.paths.cpu_turbo_intel, "1"))  # 1 = no_turbo (Turbo OFF)
                elif self.paths.cpu_turbo_amd:
                    pairs.append((self.paths.cpu_turbo_amd, "0"))    # 0 = boost OFF
                applied.append("turbo_off")

            if cfg["kbd_off"] and self.paths.kbd_backlight:
                self.settings.set("pre_eco_kbd", self.get_kbd_backlight())
                pairs.append((self.paths.kbd_backlight, "0"))
                applied.append("kbd_off")

            if cfg["gpu_d3cold"] and self.paths.nvidia_pci_power_control:
                pairs.append((self.paths.nvidia_pci_power_control, "auto"))
                applied.append("gpu_d3cold")

            if cfg["tdp_limit"] and self.paths.rapl_pl1 and self.paths.rapl_pl2:
                cur_pl1, cur_pl2 = self.get_cpu_tdp_limits()
                self.settings.set("pre_eco_tdp", [int(cur_pl1), int(cur_pl2)])
                pairs.append((self.paths.rapl_pl1, str(15 * 1_000_000)))
                pairs.append((self.paths.rapl_pl2, str(25 * 1_000_000)))
                if self.paths.rapl_mmio_pl1 and self.paths.rapl_mmio_pl2:
                    pairs.append((self.paths.rapl_mmio_pl1, str(15 * 1_000_000)))
                    pairs.append((self.paths.rapl_mmio_pl2, str(25 * 1_000_000)))
                applied.append("tdp_limit")

            ok, msg = PermissionsManager.write_multiple_sysfs_values(pairs) if pairs else (True, "")
            if cfg["profile"] and self.features.cpu_governor:
                gov_ok, gov_msg = self.set_cpu_governor("powersave")
                if not pairs:
                    ok, msg = gov_ok, gov_msg

            if cfg["refresh_min"] and self.features.refresh_rate:
                try:
                    ref_info = self.get_display_refresh_info()
                    if ref_info.available and len(ref_info.available_rates) > 1:
                        min_hz = min(ref_info.available_rates)
                        self.settings.set("pre_eco_refresh_hz", int(ref_info.current_hz))
                        if ref_info.current_hz != min_hz:
                            ok_hz, _ = self.set_refresh_rate(min_hz)
                            if ok_hz:
                                applied.append("refresh_min")
                except Exception:
                    pass

            if cfg["wifi_save"] and self.features.wifi_power_save:
                try:
                    net_st = self.get_network_power_status(force=True)
                    if net_st.wifi_available:
                        self.settings.set("pre_eco_wifi_power_save", bool(net_st.wifi_power_save_on))
                        if not net_st.wifi_power_save_on:
                            ok_wf, _ = self.set_wifi_power_saving(True, allow_elevation=False)
                            if ok_wf:
                                applied.append("wifi_save")
                except Exception:
                    pass

            if cfg["dim_brightness"] and self.features.screen_brightness:
                cur_br = self.get_screen_brightness_pct()
                if cur_br is not None and cur_br > 0:
                    self.settings.set("pre_eco_brightness_pct", int(cur_br))
                ok_br, msg_br = self.set_screen_brightness_pct(cfg["brightness_pct"], allow_elevation=False)
                if ok_br:
                    applied.append("dim_brightness")
                elif not applied:
                    ok, msg = False, msg_br

            self.settings.set("eco_applied_actions", applied)
            self.settings.set("eco_travel_mode", True)
            if "profile" in applied:
                self._max_power_active = False
                self._last_raw_profile = self._read_raw_platform_profile()
                self._last_profile = "low-power"
            if "conservation" in applied:
                self._last_conservation = True
            if "kbd_off" in applied:
                self._last_kbd_bright = 0
            return ok, "Modo Viagem (Eco-Mode Extremo) ativado." if ok else msg
        else:
            ok, msg = self._restore_eco_side_effects(restore_profile=True)
            return ok, "Modo Viagem desativado. Configurações restauradas." if ok else msg


    # =========================================================================
    # ELITE 7: Curva de Ventoinhas Personalizada (Fan Curve Editor & EC / WMI)
    # =========================================================================
    @staticmethod
    def get_fan_curve_presets() -> Dict[str, List[List[int]]]:
        """Retorna presets de curvas térmicas (Temperatura °C vs PWM %)."""
        return {
            "passive_gaming": [
                [35, 0],
                [46, 0],
                [56, 35],
                [68, 65],
                [78, 90],
                [88, 100],
            ],
            "silent": [
                [35, 0],
                [50, 0],
                [62, 25],
                [74, 45],
                [84, 65],
                [92, 85],
            ],
            "balanced": [
                [35, 0],
                [48, 25],
                [60, 45],
                [72, 70],
                [82, 90],
                [92, 100],
            ],
            "aggressive": [
                [35, 30],
                [45, 50],
                [55, 70],
                [65, 85],
                [75, 100],
                [90, 100],
            ],
        }

    def get_custom_fan_curve(self) -> Dict[str, Any]:
        """Lê a curva de ventoinhas personalizada e os limites térmicos WMI da Lenovo."""
        enabled = bool(self.settings.get("custom_fan_curve_enabled", False))
        raw_pts = self.settings.get("custom_fan_curve_points", DEFAULT_FAN_CURVE_POINTS)
        if not isinstance(raw_pts, list) or len(raw_pts) < 3:
            raw_pts = [list(p) for p in DEFAULT_FAN_CURVE_POINTS]

        cpu_limit = int(self.settings.get("custom_cpu_temp_limit", 94))
        gpu_limit = int(self.settings.get("custom_gpu_temp_limit", 87))

        if self.paths.lenovo_wmi_attr_dir:
            c_path = os.path.join(self.paths.lenovo_wmi_attr_dir, "cpu_temp", "current_value")
            g_path = os.path.join(self.paths.lenovo_wmi_attr_dir, "gpu_temp", "current_value")
            c_val = self._read_file_int(c_path, 0)
            g_val = self._read_file_int(g_path, 0)
            if 85 <= c_val <= 100:
                cpu_limit = c_val
            if 75 <= g_val <= 87:
                gpu_limit = g_val

        return {
            "enabled": enabled,
            "points": [[int(p[0]), int(p[1])] for p in raw_pts],
            "cpu_temp_limit": cpu_limit,
            "gpu_temp_limit": gpu_limit,
            "last_pwm": max(0, self._last_applied_pwm),
        }

    @staticmethod
    def interpolate_fan_pwm(points: List[List[int]], temp_c: float) -> int:
        """Interpola linearmente a porcentagem PWM (0..100%) para a temperatura atual."""
        if not points:
            return 50
        pts = sorted([[int(p[0]), max(0, min(100, int(p[1])))] for p in points], key=lambda x: x[0])
        if temp_c <= pts[0][0]:
            return pts[0][1]
        if temp_c >= pts[-1][0]:
            return pts[-1][1]
        for i in range(len(pts) - 1):
            t0, p0 = pts[i]
            t1, p1 = pts[i + 1]
            if t0 <= temp_c <= t1:
                if t1 == t0:
                    return p1
                ratio = (temp_c - t0) / float(t1 - t0)
                return int(round(p0 + ratio * (p1 - p0)))
        return pts[-1][1]

    def has_continuous_fan_control(self) -> bool:
        """Retorna True se o kernel expõe PWM contínuo (0..255) ou fan*_target com enable real."""
        return bool(self._hwmon_pwm_nodes or self.paths.hwmon_pwm1 or self._hwmon_fan_targets)

    def has_binary_fan_boost(self) -> bool:
        """Retorna True quando o EC expõe apenas modo binário (Auto vs Rotação Máxima via VPC2004/fan_mode)."""
        return bool(self.paths.fan_mode and not self.has_continuous_fan_control())

    def _pulse_vpc_fan_boost(self, allow_elevation: bool = False) -> bool:
        """
        Garante rotação máxima contínua (~5600 RPM) via VPC2004/fan_mode no Lenovo LOQ/IdeaPad.
        O firmware entra em ciclo Dust-Clean que pausa após ~6.5s mantendo fan_mode==3;
        pulsar '0' -> '2' reinicia o ciclo sem deixar fan1_input cair para 0 RPM.
        """
        fm_path = self.paths.fan_mode
        if not fm_path or not os.path.exists(fm_path):
            return False
        if not (allow_elevation or os.access(fm_path, os.W_OK)):
            return False

        cur_fm = self._read_file_int(fm_path, default=-1)
        if cur_fm == 3:
            PermissionsManager.write_sysfs_value(fm_path, "0", allow_elevation=allow_elevation)
            time.sleep(0.06)
        ok, _ = PermissionsManager.write_sysfs_value(fm_path, "2", allow_elevation=allow_elevation)
        if ok:
            self._last_vpc_boost_pulse_ts = time.time()
        return ok

    @staticmethod
    def _clamp_safe_fan_pct(target_pct: int, hottest_temp: float, gpu_temp: float = 0.0) -> int:
        """Guardrail térmico obrigatório: impede rotação baixa ou 0 RPM sob alta temperatura."""
        pct = max(0, min(100, int(target_pct)))
        if hottest_temp >= 85.0 or gpu_temp >= 82.0:
            return max(pct, 95)
        if hottest_temp >= 78.0:
            return max(pct, 75)
        if hottest_temp >= 70.0:
            return max(pct, 55)
        if hottest_temp >= 52.0 and pct == 0:
            return 25
        return pct

    def _write_fan_speed_pct(
        self,
        target_pct: Optional[int],
        hottest_temp: float,
        force: bool = False,
        allow_elevation: bool = False,
        gpu_temp: float = 0.0,
    ) -> Tuple[bool, Optional[int]]:
        """
        Aplica velocidade manual/curva em todos os nós reais disponíveis ou restaura o EC automático (None).
        """
        pwm_nodes = list(self._hwmon_pwm_nodes)
        if not pwm_nodes and self.paths.hwmon_pwm1:
            pwm_nodes = [(self.paths.hwmon_pwm1, self.paths.hwmon_pwm1_enable)]
        fan_targets = list(getattr(self, "_hwmon_fan_targets", []) or [])
        fs_path = getattr(self, "_fan_fullspeed_path", None)

        if target_pct is None:
            wrote_any = False
            for _, en_p in pwm_nodes:
                if en_p and os.path.exists(en_p) and (allow_elevation or os.access(en_p, os.W_OK)):
                    ok, _ = PermissionsManager.write_sysfs_value(en_p, "2", allow_elevation=allow_elevation)
                    wrote_any = wrote_any or ok
            for tgt_p, en_p, _min_r, _max_r in fan_targets:
                if en_p and os.path.exists(en_p) and (allow_elevation or os.access(en_p, os.W_OK)):
                    ok, _ = PermissionsManager.write_sysfs_value(en_p, "2", allow_elevation=allow_elevation)
                    wrote_any = wrote_any or ok
                elif os.path.exists(tgt_p) and (allow_elevation or os.access(tgt_p, os.W_OK)):
                    ok, _ = PermissionsManager.write_sysfs_value(tgt_p, "0", allow_elevation=allow_elevation)
                    wrote_any = wrote_any or ok
            if fs_path and os.path.exists(fs_path) and (allow_elevation or os.access(fs_path, os.W_OK)):
                ok, _ = PermissionsManager.write_sysfs_value(fs_path, "0", allow_elevation=allow_elevation)
                wrote_any = wrote_any or ok
            if self.paths.fan_mode and os.path.exists(self.paths.fan_mode) and (allow_elevation or os.access(self.paths.fan_mode, os.W_OK)):
                ok, _ = PermissionsManager.write_sysfs_value(self.paths.fan_mode, "0", allow_elevation=allow_elevation)
                wrote_any = wrote_any or ok
            self._last_applied_pwm = -1
            self._fan_override_applied_by_app = False
            return True if wrote_any or not (pwm_nodes or fan_targets or fs_path or self.paths.fan_mode) else False, None

        effective_pct = self._clamp_safe_fan_pct(target_pct, hottest_temp, gpu_temp)
        self._last_applied_pwm = effective_pct
        pwm_byte = int(round((effective_pct / 100.0) * 255))
        wrote_any = False

        # 1. Escrita direta em nós hwmon pwm*
        for pwm_p, en_p in pwm_nodes:
            if en_p and os.path.exists(en_p) and (allow_elevation or os.access(en_p, os.W_OK)):
                PermissionsManager.write_sysfs_value(en_p, "1", allow_elevation=allow_elevation)
            if os.path.exists(pwm_p) and (allow_elevation or os.access(pwm_p, os.W_OK) or force):
                ok, _ = PermissionsManager.write_sysfs_value(pwm_p, str(pwm_byte), allow_elevation=allow_elevation)
                wrote_any = wrote_any or ok

        # 2. Escrita em nós hwmon fan*_target (quando suportado pelo EC)
        for tgt_p, en_p, min_r, max_r in fan_targets:
            if en_p and os.path.exists(en_p) and (allow_elevation or os.access(en_p, os.W_OK)):
                PermissionsManager.write_sysfs_value(en_p, "1", allow_elevation=allow_elevation)
            rpm_val = 0 if effective_pct == 0 else int(round(min_r + (effective_pct / 100.0) * (max_r - min_r)))
            if os.path.exists(tgt_p) and (allow_elevation or os.access(tgt_p, os.W_OK) or force):
                ok, _ = PermissionsManager.write_sysfs_value(tgt_p, str(rpm_val), allow_elevation=allow_elevation)
                wrote_any = wrote_any or ok

        # 3. Nó fan_fullspeed (legion_laptop)
        if fs_path and os.path.exists(fs_path) and (allow_elevation or os.access(fs_path, os.W_OK)):
            ok, _ = PermissionsManager.write_sysfs_value(fs_path, "1" if effective_pct >= 90 else "0", allow_elevation=allow_elevation)
            wrote_any = wrote_any or ok

        # 4. Controle real Lenovo VPC2004:00/fan_mode (LOQ / IdeaPad: 2 = Full Speed ~5600 RPM, 0 = EC Auto)
        if self.paths.fan_mode and os.path.exists(self.paths.fan_mode):
            ec_mode = "2" if effective_pct >= 75 else "0"
            cur_fm = self._read_file_int(self.paths.fan_mode, default=-1)
            now = time.time()
            live_rpm = self._read_file_int(self.paths.fan1_input, default=-1) if self.paths.fan1_input else -1
            last_pulse = float(getattr(self, "_last_vpc_boost_pulse_ts", 0.0) or 0.0)
            boost_stale = (cur_fm == 3) and (
                (now - last_pulse) >= 4.2
                or (0 <= live_rpm < 3200 and (now - last_pulse) >= 2.0)
            )
            if ec_mode == "2":
                if force or cur_fm != 3 or boost_stale:
                    if self._pulse_vpc_fan_boost(allow_elevation=allow_elevation):
                        wrote_any = True
            else:
                if (force or cur_fm not in (0, 133)) and (allow_elevation or os.access(self.paths.fan_mode, os.W_OK)):
                    ok, _ = PermissionsManager.write_sysfs_value(self.paths.fan_mode, "0", allow_elevation=allow_elevation)
                    wrote_any = wrote_any or ok

        self._fan_override_applied_by_app = bool(wrote_any)
        return wrote_any, effective_pct

    def get_manual_fan_speed(self) -> Dict[str, Any]:
        """Retorna o estado da velocidade manual direta e o último PWM aplicado."""
        enabled = bool(self.settings.get("manual_fan_enabled", False))
        speed_pct = max(0, min(100, int(self.settings.get("manual_fan_speed_pct", 100) or 100)))
        return {
            "enabled": enabled,
            "speed_pct": speed_pct,
            "last_pwm": max(0, self._last_applied_pwm),
            "continuous_pwm": self.has_continuous_fan_control(),
            "binary_boost_only": self.has_binary_fan_boost(),
        }

    def set_manual_fan_speed(
        self,
        enabled: bool,
        speed_pct: int = 100,
        allow_elevation: bool = True,
    ) -> Tuple[bool, str]:
        """
        Ativa/desativa a velocidade manual fixa da ventoinha (ex.: 25%..100%) com guardrail térmico
        e suporte real a EC PWM / fan*_target / VPC2004 fan_mode (~5600 RPM contínuo).
        """
        if not enabled:
            self.settings.set("manual_fan_enabled", False)
            if not bool(self.settings.get("custom_fan_curve_enabled", False)):
                self._write_fan_speed_pct(None, 40.0, force=True, allow_elevation=allow_elevation)
            return True, "Controle manual desativado. Ventoinha de volta ao automático do EC."

        clamped_pct = 100 if self.has_binary_fan_boost() else max(25, min(100, int(speed_pct)))
        self.settings.update_many({
            "custom_fan_curve_enabled": False,
            "manual_fan_enabled": True,
            "manual_fan_speed_pct": clamped_pct,
            "cooling_preset": "max" if clamped_pct >= 90 else "manual",
        })

        cpu_temp = (
            self._read_file_int(self.paths.cpu_temp_input, 45000) / 1000.0
            if self.paths.cpu_temp_input
            else 45.0
        )
        gpu_m = self.get_gpu_metrics()
        gpu_temp = gpu_m.temperature_c if gpu_m.available else 0.0
        hottest = max(cpu_temp, gpu_temp)

        ok, eff = self._write_fan_speed_pct(
            clamped_pct, hottest, force=True, allow_elevation=allow_elevation, gpu_temp=gpu_temp
        )
        if not ok:
            self.settings.set("manual_fan_enabled", False)
            return False, "Sem permissão de escrita no controlador de ventoinha (repare as regras UDEV)."

        eff_val = eff if eff is not None else clamped_pct
        if self.has_binary_fan_boost():
            return True, "Turbo Máximo ativo no EC (acelerando continuamente até ~5600 RPM)."
        return True, f"Velocidade manual aplicada no EC: {eff_val}% PWM."

    def set_custom_fan_curve(
        self,
        points: List[List[int]],
        enabled: bool,
        cpu_temp_limit: Optional[int] = 94,
        gpu_temp_limit: Optional[int] = 87,
    ) -> Tuple[bool, str]:
        """
        Salva a curva personalizada de ventoinhas e escreve os parâmetros térmicos
        no Embedded Controller (EC) e Lenovo WMI Other.
        """
        clean_pts = []
        for p in points:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                t = max(30, min(100, int(p[0])))
                pwm = max(0, min(100, int(p[1])))
                clean_pts.append([t, pwm])
        clean_pts.sort(key=lambda x: x[0])
        if len(clean_pts) < 3:
            clean_pts = [list(x) for x in DEFAULT_FAN_CURVE_POINTS]

        cpu_temp_limit = 94 if cpu_temp_limit is None else max(85, min(100, int(cpu_temp_limit)))
        gpu_temp_limit = 87 if gpu_temp_limit is None else max(75, min(87, int(gpu_temp_limit)))

        batch: Dict[str, Any] = {
            "custom_fan_curve_points": clean_pts,
            "custom_fan_curve_enabled": bool(enabled),
            "custom_cpu_temp_limit": cpu_temp_limit,
            "custom_gpu_temp_limit": gpu_temp_limit,
        }
        if enabled:
            batch["manual_fan_enabled"] = False
        self.settings.update_many(batch)

        if enabled and self.paths.platform_profile:
            choices = [c.lower().strip() for c in self.get_platform_profile_choices()]
            if "custom" in choices and self._read_raw_platform_profile() != "custom":
                ok_c, _ = PermissionsManager.write_sysfs_value(self.paths.platform_profile, "custom")
                if ok_c:
                    self._max_power_active = False
                    self._promoted_max_power_from_low = False
                    self._last_raw_profile = "custom"
                    self._last_profile = "custom"
                    self._sync_platform_profile_cache("custom")
                    time.sleep(0.05)

        pairs: List[Tuple[str, str]] = []
        if self.paths.lenovo_wmi_attr_dir and (enabled or self._read_raw_platform_profile() == "custom"):
            c_path = os.path.join(self.paths.lenovo_wmi_attr_dir, "cpu_temp", "current_value")
            g_path = os.path.join(self.paths.lenovo_wmi_attr_dir, "gpu_temp", "current_value")
            if os.path.exists(c_path):
                pairs.append((c_path, str(cpu_temp_limit)))
            if os.path.exists(g_path):
                pairs.append((g_path, str(gpu_temp_limit)))

        if pairs:
            PermissionsManager.write_multiple_sysfs_values(pairs)

        if enabled:
            applied_pwm = self.apply_dynamic_fan_curve_tick(force=True)
            return (
                True,
                f"Curva de ventoinhas aplicada no EC (Alvo atual: {applied_pwm if applied_pwm is not None else 50}% PWM | "
                f"Limites WMI: CPU {cpu_temp_limit}°C / GPU {gpu_temp_limit}°C).",
            )
        else:
            # Restaurar controle automático do EC
            self._write_fan_speed_pct(None, 40.0, force=True, allow_elevation=False)
            return True, "Curva customizada desativada. Controle automático original do EC restaurado."

    def apply_dynamic_fan_curve_tick(self, force: bool = False) -> Optional[int]:
        """
        Avalia velocidade manual fixa, boost contínuo em Max-Power ou curva customizada
        e atualiza o PWM / Fan Mode no Embedded Controller da Lenovo sem bloquear a UI.
        """
        manual_on = bool(self.settings.get("manual_fan_enabled", False))
        curve_on = bool(self.settings.get("custom_fan_curve_enabled", False))
        max_boost_active = bool(
            not manual_on
            and not curve_on
            and getattr(self, "_max_power_active", False)
            and self.paths.fan_mode
            and getattr(self, "_fan_override_applied_by_app", False)
        )
        if not manual_on and not curve_on and not max_boost_active and not force:
            return None

        cpu_temp = 45.0
        if self.paths.cpu_temp_input:
            cpu_temp = self._read_file_int(self.paths.cpu_temp_input, 45000) / 1000.0
        gpu_m = self.get_gpu_metrics()
        gpu_temp = gpu_m.temperature_c if gpu_m.available else 0.0
        hottest_temp = max(cpu_temp, gpu_temp)

        def _needs_vpc_reassert(safe_val: int) -> bool:
            if safe_val < 75 or not self.paths.fan_mode or not os.path.exists(self.paths.fan_mode):
                return False
            cur_fm = self._read_file_int(self.paths.fan_mode, default=-1)
            if cur_fm != 3:
                return True
            now_t = time.time()
            last_p = float(getattr(self, "_last_vpc_boost_pulse_ts", 0.0) or 0.0)
            live_r = self._read_file_int(self.paths.fan1_input, default=-1) if self.paths.fan1_input else -1
            return (now_t - last_p) >= 4.2 or (0 <= live_r < 3200 and (now_t - last_p) >= 2.0)

        if max_boost_active:
            if _needs_vpc_reassert(100) or force:
                _, eff = self._write_fan_speed_pct(100, hottest_temp, force=True, allow_elevation=False, gpu_temp=gpu_temp)
                return eff
            return 100

        if manual_on:
            target_pct = 100 if self.has_binary_fan_boost() else max(
                25, min(100, int(self.settings.get("manual_fan_speed_pct", 100) or 100))
            )
            safe_pct = self._clamp_safe_fan_pct(target_pct, hottest_temp, gpu_temp)
            reassert_fm = _needs_vpc_reassert(safe_pct)
            if not force and not reassert_fm and self._last_applied_pwm >= 0 and abs(safe_pct - self._last_applied_pwm) < 4:
                return self._last_applied_pwm
            _, eff = self._write_fan_speed_pct(safe_pct, hottest_temp, force=bool(force or reassert_fm), allow_elevation=False, gpu_temp=gpu_temp)
            return eff

        pts = self.settings.get("custom_fan_curve_points", DEFAULT_FAN_CURVE_POINTS)
        target_pwm_pct = self.interpolate_fan_pwm(pts, hottest_temp)
        safe_pct = self._clamp_safe_fan_pct(target_pwm_pct, hottest_temp, gpu_temp)
        reassert_fm = _needs_vpc_reassert(safe_pct)

        # Evitar escritas redundantes no EC se a variação for menor que 4% (histerese térmica)
        if not force and not reassert_fm and self._last_applied_pwm >= 0 and abs(safe_pct - self._last_applied_pwm) < 4:
            return self._last_applied_pwm

        _, eff = self._write_fan_speed_pct(safe_pct, hottest_temp, force=bool(force or reassert_fm), allow_elevation=False, gpu_temp=gpu_temp)
        return eff

    def has_cooling_controls(self) -> bool:
        """Retorna True se o notebook expõe controle de ventoinha (PWM/EC), alvos térmicos WMI ou perfis ACPI."""
        return bool(
            self.features.fan_control
            or self.features.wmi_cpu_temp
            or self.features.wmi_gpu_temp
            or self.features.platform_profile
        )

    def get_wmi_thermal_bounds(self) -> Dict[str, Tuple[int, int, int]]:
        """Retorna (min_c, max_c, current_c) reais para cpu_temp e gpu_temp do Lenovo WMI Other."""
        defaults: Dict[str, Tuple[int, int, int]] = {
            "cpu_temp": (85, 100, int(self.settings.get("custom_cpu_temp_limit", 94) or 94)),
            "gpu_temp": (75, 87, int(self.settings.get("custom_gpu_temp_limit", 87) or 87)),
        }
        wmi_dir = self.paths.lenovo_wmi_attr_dir
        out: Dict[str, Tuple[int, int, int]] = {}
        for attr_id, (def_lo, def_hi, def_cur) in defaults.items():
            lo, hi, cur = def_lo, def_hi, def_cur
            if wmi_dir:
                adir = os.path.join(wmi_dir, attr_id)
                r_lo = self._read_file_int(os.path.join(adir, "min_value"), 0)
                r_hi = self._read_file_int(os.path.join(adir, "max_value"), 0)
                r_cur = self._read_file_int(os.path.join(adir, "current_value"), 0)
                if 40 <= r_lo < r_hi <= 115:
                    lo, hi = r_lo, r_hi
                if lo <= r_cur <= hi:
                    cur = r_cur
            cur = max(lo, min(hi, cur))
            out[attr_id] = (lo, hi, cur)
        return out

    def apply_wmi_thermal_targets(
        self,
        cpu_temp_limit: int,
        gpu_temp_limit: int,
        allow_elevation: bool = True,
    ) -> Tuple[bool, str]:
        """Aplica limites térmicos CPU/GPU no Lenovo WMI Other (ativa modo custom quando necessário)."""
        if not (self.features.wmi_cpu_temp or self.features.wmi_gpu_temp):
            return False, "Alvos térmicos WMI não detectados neste dispositivo."

        bounds = self.get_wmi_thermal_bounds()
        c_lo, c_hi, _ = bounds["cpu_temp"]
        g_lo, g_hi, _ = bounds["gpu_temp"]
        cpu_lim = max(c_lo, min(c_hi, int(cpu_temp_limit)))
        gpu_lim = max(g_lo, min(g_hi, int(gpu_temp_limit)))

        if self.paths.platform_profile:
            choices = [c.lower().strip() for c in self.get_platform_profile_choices()]
            if "custom" in choices and self._read_raw_platform_profile() != "custom":
                ok_c, msg_c = PermissionsManager.write_sysfs_value(
                    self.paths.platform_profile, "custom", allow_elevation=allow_elevation
                )
                if not ok_c:
                    return False, f"Falha ao ativar perfil custom para alvos térmicos: {msg_c}"
                self._max_power_active = False
                self._promoted_max_power_from_low = False
                self._last_raw_profile = "custom"
                self._last_profile = "custom"
                self._sync_platform_profile_cache("custom")
                time.sleep(0.05)

        pairs: List[Tuple[str, str]] = []
        wmi_dir = self.paths.lenovo_wmi_attr_dir
        if wmi_dir:
            if self.features.wmi_cpu_temp:
                c_path = os.path.join(wmi_dir, "cpu_temp", "current_value")
                if os.path.exists(c_path):
                    pairs.append((c_path, str(cpu_lim)))
            if self.features.wmi_gpu_temp:
                g_path = os.path.join(wmi_dir, "gpu_temp", "current_value")
                if os.path.exists(g_path):
                    pairs.append((g_path, str(gpu_lim)))

        if not pairs:
            return False, "Nós WMI cpu_temp/gpu_temp indisponíveis para gravação."

        ok, msg = PermissionsManager.write_multiple_sysfs_values(pairs, allow_elevation=allow_elevation)
        if not ok:
            return False, msg

        self.settings.set("custom_cpu_temp_limit", cpu_lim)
        self.settings.set("custom_gpu_temp_limit", gpu_lim)
        return True, f"Alvos térmicos do EC aplicados: CPU {cpu_lim}°C | GPU {gpu_lim}°C (perfil Custom)."

    def get_active_cooling_preset(self) -> str:
        """Retorna o modo de ventilação ativo ('quiet', 'auto', 'cool', 'max', 'manual' ou 'custom')."""
        if self.features.fan_control and bool(self.settings.get("manual_fan_enabled", False)):
            pct = int(self.settings.get("manual_fan_speed_pct", 100) or 100)
            saved = str(self.settings.get("cooling_preset", "") or "")
            if pct >= 90 and saved == "max":
                return "max"
            return "manual"

        if self.features.fan_control and bool(self.settings.get("custom_fan_curve_enabled", False)):
            saved = str(self.settings.get("cooling_preset", "custom") or "custom")
            return saved if saved in ("quiet", "auto", "cool", "max", "custom") else "custom"

        if self.features.platform_profile:
            prof = self.normalize_profile(self.get_platform_profile())
            if prof == "max-power":
                return "max"
            if prof in ("low-power", "quiet"):
                return "quiet"
            if prof == "custom":
                if self.features.wmi_cpu_temp or self.features.wmi_gpu_temp:
                    bounds = self.get_wmi_thermal_bounds()
                    c_lo, _, c_cur = bounds["cpu_temp"]
                    g_lo, _, g_cur = bounds["gpu_temp"]
                    if (self.features.wmi_cpu_temp and c_cur <= c_lo + 2) or (self.features.wmi_gpu_temp and g_cur <= g_lo + 2):
                        return "cool"
                return "custom"
            if prof == "performance":
                saved = str(self.settings.get("cooling_preset", "") or "")
                if not self.features.max_power_profile and saved != "cool":
                    return "max"
                return "cool"
            return "auto"

        saved = str(self.settings.get("cooling_preset", "auto") or "auto")
        return saved if saved in ("quiet", "auto", "cool", "max", "custom", "manual") else "auto"

    def apply_cooling_preset(self, preset_id: str, allow_elevation: bool = True) -> Tuple[bool, str]:
        """Aplica em 1 clique um modo de ventilação real (EC VPC2004, PWM/Target ou WMI)."""
        if not self.has_cooling_controls():
            return False, "Nenhum controle de ventilação suportado foi detectado."

        pid = str(preset_id or "auto").lower().strip()
        if pid not in ("quiet", "auto", "cool", "max"):
            pid = "auto"

        choices = [c.lower().strip() for c in self.get_platform_profile_choices()] if self.features.platform_profile else []

        if pid == "quiet":
            self.settings.set("manual_fan_enabled", False)
            if self.features.fan_control and not self.features.platform_profile:
                pts = self.get_fan_curve_presets()["silent"]
                ok, msg = self.set_custom_fan_curve(pts, True)
            else:
                if self.features.fan_control and bool(self.settings.get("custom_fan_curve_enabled", False)):
                    self.set_custom_fan_curve(self.get_custom_fan_curve()["points"], False)
                self._write_fan_speed_pct(None, 40.0, force=True, allow_elevation=False)
                ok, msg = self.set_platform_profile("low-power", allow_elevation=allow_elevation)
                if ok:
                    msg = "Ventoinhas em modo Silencioso (perfil EC Silencioso / 0 RPM em uso leve)."
            if ok:
                self.settings.set("cooling_preset", "quiet")
            return ok, msg

        if pid == "auto":
            self.settings.set("manual_fan_enabled", False)
            if self.features.fan_control and bool(self.settings.get("custom_fan_curve_enabled", False)):
                self.set_custom_fan_curve(self.get_custom_fan_curve()["points"], False)
            self._write_fan_speed_pct(None, 40.0, force=True, allow_elevation=False)
            if self.features.platform_profile:
                ok, msg = self.set_platform_profile("balanced", allow_elevation=allow_elevation)
                if ok:
                    msg = "Ventoinhas em modo Automático (controle inteligente padrão do EC)."
            else:
                ok, msg = True, "Controle automático original das ventoinhas restaurado."
            if ok:
                self.settings.set("cooling_preset", "auto")
            return ok, msg

        if pid == "cool":
            self.settings.update_many({"manual_fan_enabled": False, "custom_fan_curve_enabled": False})
            self._write_fan_speed_pct(None, 40.0, force=True, allow_elevation=False)
            has_wmi_targets = bool(self.features.wmi_cpu_temp or self.features.wmi_gpu_temp)
            cool_curve = [[30, 55], [45, 65], [60, 80], [72, 92], [82, 100], [92, 100]]
            if has_wmi_targets and (not self.features.platform_profile or "custom" in choices):
                bounds = self.get_wmi_thermal_bounds()
                c_lo, _, _ = bounds["cpu_temp"]
                g_lo, _, _ = bounds["gpu_temp"]
                ok, msg = self.apply_wmi_thermal_targets(c_lo, g_lo, allow_elevation=allow_elevation)
                if ok:
                    if self.has_continuous_fan_control():
                        self.set_custom_fan_curve(cool_curve, True, c_lo, g_lo)
                        msg = f"Modo Mais Frio ativo: EC adiantado (CPU {c_lo}°C / GPU {g_lo}°C + curva proativa)."
                    else:
                        msg = f"Modo Mais Frio ativo: EC adiantado para acelerar mais cedo (Alvos CPU {c_lo}°C / GPU {g_lo}°C)."
            elif self.has_continuous_fan_control():
                ok, msg = self.set_custom_fan_curve(cool_curve, True)
            else:
                ok, msg = self.set_platform_profile("performance", allow_elevation=allow_elevation)
                if ok:
                    msg = "Modo Mais Frio ativo: curva térmica de Desempenho aplicada no EC."
            if ok:
                self.settings.set("cooling_preset", "cool")
            return ok, msg

        # pid == "max"
        target_prof = "max-power" if self.features.max_power_profile else "performance"
        self.settings.set("custom_fan_curve_enabled", False)
        if self.features.platform_profile:
            ok, msg = self.set_platform_profile(
                target_prof, allow_elevation=allow_elevation, preserve_fan_override=True
            )
            if ok and self.features.fan_control:
                ok_f, _ = self.set_manual_fan_speed(True, 100, allow_elevation=allow_elevation)
                if ok_f:
                    msg = f"Turbo Máximo ativo ({target_prof.upper()} + rotação máxima contínua ~5600 RPM)."
                else:
                    self.settings.set("manual_fan_enabled", False)
                    msg = f"Turbo Máximo ativo ({target_prof.upper()})."
        elif self.features.fan_control:
            ok, msg = self.set_manual_fan_speed(True, 100, allow_elevation=allow_elevation)
        else:
            ok, msg = False, "Turbo Máximo indisponível neste dispositivo."
        if ok:
            self.settings.set("cooling_preset", "max")
        return ok, msg

    # =========================================================================
    # ELITE 8: Overclock & Undervolt Dinâmico (Intel HX / AMD) + Watchdog Seguro
    # =========================================================================
    @staticmethod
    def _encode_intel_msr_undervolt_offset(plane: int, offset_mv: int) -> int:
        """
        Codifica o valor de offset em mV (-150 a 0 mV) para o registrador MSR 0x150
        (Intel OC Mailbox: Plane 0 = CPU Core, Plane 2 = CPU Cache).
        Fórmula oficial Intel OC Mailbox: round(offset_mv * 1.024) em complemento de 2 (11 bits) << 21.
        """
        clamped_mv = max(-150, min(0, int(offset_mv)))
        units = int(round(clamped_mv * 1.024)) & 0x7FF
        return 0x8000001100000000 | ((int(plane) & 0xF) << 40) | (units << 21)

    @staticmethod
    def _has_undervolt_canary() -> bool:
        return any(os.path.exists(p) for p in UNDERVOLT_CANARY_PATHS)

    @staticmethod
    def _write_undervolt_canary(core_mv: int, cache_mv: int) -> None:
        payload = f"{datetime.datetime.now().isoformat()}|core={core_mv}|cache={cache_mv}\n"
        for cpath in UNDERVOLT_CANARY_PATHS:
            try:
                os.makedirs(os.path.dirname(cpath), exist_ok=True)
                with open(cpath, "w", encoding="utf-8") as f:
                    f.write(payload)
                return
            except Exception:
                continue

    @staticmethod
    def _clear_undervolt_canary() -> None:
        for cpath in UNDERVOLT_CANARY_PATHS:
            if os.path.exists(cpath):
                try:
                    os.remove(cpath)
                except Exception:
                    pass

    def _check_undervolt_crash_recovery(self) -> None:
        """
        Watchdog de Segurança contra Kernel Panic:
        Se o arquivo canário existir na inicialização do aplicativo, significa que o último
        undervolt não foi confirmado ou causou travamento. Restaura imediatamente 0 mV.
        """
        if self._has_undervolt_canary():
            self._clear_undervolt_canary()
            self.settings.set("undervolt_core_mv", 0)
            self.settings.set("undervolt_cache_mv", 0)
            self._last_emergency_reset = (
                "Watchdog de Segurança acionado: o último ajuste de tensão não foi confirmado "
                "e foi revertido automaticamente para 0 mV para proteger o sistema."
            )

    def get_undervolt_status(self) -> UndervoltStatus:
        """Retorna o estado atual de Undervolt (Core/Cache) e Offset AC da GPU."""
        cpu_m = self.get_cpu_metrics()
        vendor = cpu_m.vendor
        if self.features.cpu_undervolt and self.features.wmi_gpu_ac_offset:
            if vendor == "AMD":
                method = "AMD Curve Optimizer (ryzenadj) + Lenovo WMI"
            else:
                method = "MSR 0x150 (Intel HX OC Mailbox) + Lenovo WMI"
        elif self.features.cpu_undervolt:
            if vendor == "AMD":
                method = "AMD Curve Optimizer (ryzenadj)"
            else:
                method = "MSR 0x150 (Intel OC Mailbox)"
        elif self.features.wmi_gpu_ac_offset:
            method = "Lenovo WMI GPU / AC Power Offset"
        else:
            method = "Não suportado neste hardware"

        core_mv = max(-150, min(0, int(self.settings.get("undervolt_core_mv", 0))))
        cache_mv = max(-150, min(0, int(self.settings.get("undervolt_cache_mv", 0))))
        gpu_offset_w = int(self.settings.get("gpu_ac_offset_w", 20))

        if self.paths.lenovo_wmi_attr_dir:
            ac_off_path = os.path.join(self.paths.lenovo_wmi_attr_dir, "gpu_nv_ac_offset", "current_value")
            val = self._read_file_int(ac_off_path, -1)
            if 10 <= val <= 30:
                gpu_offset_w = val

        return UndervoltStatus(
            supported=bool(self.features.cpu_undervolt or self.features.wmi_gpu_ac_offset),
            cpu_vendor=vendor,
            method=method,
            core_offset_mv=core_mv,
            cache_offset_mv=cache_mv,
            gpu_ac_offset_w=gpu_offset_w,
            safe_guard_active=self._has_undervolt_canary(),
            last_emergency_reset=self._last_emergency_reset,
            min_mv=-150,
            max_mv=0,
        )

    def apply_undervolt_offsets(
        self,
        core_mv: int,
        cache_mv: int,
        gpu_ac_offset_w: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """
        Aplica offsets negativos seguros de tensão (Core e Cache: -150 mV a 0 mV)
        via registrador MSR 0x150 (Intel HX) / ryzenadj (AMD) e Offset de Potência WMI.
        Cria o arquivo canário antes da escrita para ativar o Watchdog de 15 segundos.
        """
        core_mv = max(-150, min(0, int(core_mv)))
        cache_mv = max(-150, min(0, int(cache_mv)))
        prev_core = int(self.settings.get("undervolt_core_mv", 0) or 0)
        prev_cache = int(self.settings.get("undervolt_cache_mv", 0) or 0)
        needs_hw_write = bool(
            core_mv != 0
            or cache_mv != 0
            or prev_core != 0
            or prev_cache != 0
            or getattr(self, "_undervolt_active_in_hw", False)
        )
        if gpu_ac_offset_w is not None:
            gpu_ac_offset_w = max(10, min(30, int(gpu_ac_offset_w)))
        else:
            gpu_ac_offset_w = int(self.settings.get("gpu_ac_offset_w", 20))

        # 1. Gravar Canário de Segurança se houver offset negativo de tensão
        if core_mv < 0 or cache_mv < 0:
            self._write_undervolt_canary(core_mv, cache_mv)
        else:
            self._clear_undervolt_canary()

        msr_core_hex = hex(self._encode_intel_msr_undervolt_offset(0, core_mv))
        msr_cache_hex = hex(self._encode_intel_msr_undervolt_offset(2, cache_mv))
        applied_details = []

        # 2. Aplicar Lenovo WMI gpu_nv_ac_offset se disponível
        if self.paths.lenovo_wmi_attr_dir:
            ac_off_path = os.path.join(self.paths.lenovo_wmi_attr_dir, "gpu_nv_ac_offset", "current_value")
            if os.path.exists(ac_off_path):
                cur_ac_off = (self._read_file_text(ac_off_path) or "").strip()
                if cur_ac_off != str(gpu_ac_offset_w):
                    self._ensure_custom_profile_for_wmi(ac_off_path, allow_elevation=False)
                ok_wmi, _ = PermissionsManager.write_sysfs_value(ac_off_path, str(gpu_ac_offset_w), allow_elevation=False)
                if ok_wmi:
                    applied_details.append(f"WMI AC Offset: +{gpu_ac_offset_w}W")
                    self.settings.set("gpu_ac_offset_w", gpu_ac_offset_w)
        else:
            self.settings.set("gpu_ac_offset_w", gpu_ac_offset_w)

        # 3. Escrita de tensão diferenciada por fabricante de CPU
        vendor = self.get_cpu_vendor()
        msr_written = False

        if vendor == "Intel":
            # Escrita direta em /dev/cpu/*/msr (Plane 0 Core & Plane 2 Cache) se acessível
            msr_nodes = sorted(glob.glob("/dev/cpu/[0-9]*/msr"))
            direct_msr_attempted = False
            val_core = self._encode_intel_msr_undervolt_offset(0, core_mv)
            val_cache = self._encode_intel_msr_undervolt_offset(2, cache_mv)
            if msr_nodes and os.access(msr_nodes[0], os.W_OK):
                direct_msr_attempted = True
                try:
                    packed_core = struct.pack("<Q", val_core)
                    packed_cache = struct.pack("<Q", val_cache)
                    for mpath in msr_nodes:
                        fd = os.open(mpath, os.O_WRONLY)
                        try:
                            os.pwrite(fd, packed_core, 0x150)
                            os.pwrite(fd, packed_cache, 0x150)
                        finally:
                            os.close(fd)
                    msr_written = True
                    applied_details.append(f"MSR 0x150 ({msr_core_hex})")
                except OSError as e:
                    # Tratar 12ª/13ª/14ª Geração com OC Lock / Undervolt Protection ativado na BIOS
                    msr_written = False
                    if e.errno in (1, 5, 13):  # EPERM, EIO, EACCES
                        applied_details.append("Intel OC Lock/Undervolt Protection ativo na BIOS")
                    else:
                        applied_details.append(f"MSR OSError ({e.strerror})")
                except Exception as e:
                    msr_written = False
                    applied_details.append(f"MSR Exception ({e})")

            # Fallback para Intel via wrmsr, escrita direta MSR via pkexec + modprobe msr, ou intel-undervolt com atualização real do conf
            if not msr_written and needs_hw_write:
                if shutil.which("wrmsr") and shutil.which("pkexec"):
                    try:
                        cmd = f"modprobe msr 2>/dev/null || true; wrmsr -a 0x150 {msr_core_hex} && wrmsr -a 0x150 {msr_cache_hex}"
                        res = subprocess.run(["pkexec", "sh", "-c", cmd], capture_output=True, text=True, timeout=10)
                        if res.returncode == 0:
                            msr_written = True
                            applied_details.append(f"wrmsr 0x150 ({msr_core_hex})")
                        else:
                            applied_details.append("MSR 0x150 bloqueado (OC Lock ativo na BIOS)")
                    except Exception:
                        pass
                elif not direct_msr_attempted and shutil.which("pkexec"):
                    py_script = (
                        "import glob, os, struct, subprocess, sys\n"
                        "vc, vca = int(sys.argv[1]), int(sys.argv[2])\n"
                        "subprocess.run(['modprobe', 'msr'], check=False)\n"
                        "nodes = sorted(glob.glob('/dev/cpu/[0-9]*/msr'))\n"
                        "if not nodes:\n"
                        "    sys.stderr.write('No /dev/cpu/*/msr nodes found\\n')\n"
                        "    sys.exit(2)\n"
                        "pc, pca = struct.pack('<Q', vc), struct.pack('<Q', vca)\n"
                        "for p in nodes:\n"
                        "    fd = os.open(p, os.O_WRONLY)\n"
                        "    try:\n"
                        "        os.pwrite(fd, pc, 0x150)\n"
                        "        os.pwrite(fd, pca, 0x150)\n"
                        "    finally:\n"
                        "        os.close(fd)\n"
                    )
                    try:
                        res = subprocess.run(
                            ["pkexec", sys.executable or "/usr/bin/python3", "-c", py_script, str(val_core), str(val_cache)],
                            capture_output=True, text=True, timeout=20
                        )
                        if res.returncode == 0:
                            msr_written = True
                            applied_details.append(f"MSR 0x150 via Polkit ({msr_core_hex})")
                        else:
                            err_txt = (res.stderr or res.stdout or "").lower()
                            if any(k in err_txt for k in ("operation not permitted", "input/output error", "permission denied", "eperm", "eio")):
                                applied_details.append("MSR 0x150 bloqueado (OC Lock / Undervolt Protection ativo na BIOS)")
                            elif res.returncode in (126, 127) or "dismissed" in err_txt or "cancel" in err_txt or "not authorized" in err_txt:
                                applied_details.append("Elevação Polkit cancelada pelo usuário")
                            elif shutil.which("intel-undervolt"):
                                # Atualiza /etc/intel-undervolt.conf antes de aplicar para evitar no-op
                                iu_script = (
                                    "import re, subprocess, sys\n"
                                    "core, cache = int(sys.argv[1]), int(sys.argv[2])\n"
                                    "conf = '/etc/intel-undervolt.conf'\n"
                                    "with open(conf, 'r', encoding='utf-8') as f: txt = f.read()\n"
                                    "txt = re.sub(r\"(?m)^undervolt\\s+0\\s+'CPU'\\s+[-\\d.]+\", f\"undervolt 0 'CPU' {core}\", txt)\n"
                                    "txt = re.sub(r\"(?m)^undervolt\\s+2\\s+'CPU Cache'\\s+[-\\d.]+\", f\"undervolt 2 'CPU Cache' {cache}\", txt)\n"
                                    "with open(conf, 'w', encoding='utf-8') as f: f.write(txt)\n"
                                    "sys.exit(subprocess.run(['intel-undervolt', 'apply']).returncode)\n"
                                )
                                res_iu = subprocess.run(
                                    ["pkexec", sys.executable or "/usr/bin/python3", "-c", iu_script, str(core_mv), str(cache_mv)],
                                    capture_output=True, text=True, timeout=15
                                )
                                if res_iu.returncode == 0:
                                    msr_written = True
                                    applied_details.append(f"intel-undervolt ({core_mv}/{cache_mv} mV)")
                                else:
                                    applied_details.append(f"MSR 0x150 falhou via Polkit (código {res.returncode})")
                            else:
                                applied_details.append(f"MSR 0x150 falhou via Polkit (código {res.returncode})")
                    except Exception as e:
                        applied_details.append(f"Falha ao executar Polkit MSR ({e})")

        elif vendor == "AMD":
            # CPUs AMD: JAMAIS escrever no MSR 0x150! Usar ryzenadj Curve Optimizer
            if needs_hw_write:
                co_counts = 0 if core_mv == 0 else max(-30, min(0, core_mv // 5))
                if shutil.which("ryzenadj"):
                    try:
                        res = subprocess.run(
                            ["ryzenadj", f"--set-coall={co_counts}"],
                            capture_output=True, text=True, timeout=5
                        )
                        if res.returncode == 0:
                            msr_written = True
                            applied_details.append(f"Ryzen CO ({co_counts})")
                        elif shutil.which("pkexec"):
                            res2 = subprocess.run(
                                ["pkexec", "ryzenadj", f"--set-coall={co_counts}"],
                                capture_output=True, text=True, timeout=10
                            )
                            if res2.returncode == 0:
                                msr_written = True
                                applied_details.append(f"Ryzen CO ({co_counts})")
                    except Exception:
                        pass
                if not msr_written and core_mv != 0:
                    applied_details.append("AMD ryzenadj necessário para Curve Optimizer")
                elif not msr_written and core_mv == 0:
                    msr_written = True
            else:
                msr_written = True
        else:
            applied_details.append("Processador genérico: undervolt não suportado")

        # 4. Avaliação de estabilidade e persistência de settings
        undervolt_requested = (core_mv != 0 or cache_mv != 0)
        if undervolt_requested and not msr_written:
            # Reverte canário e settings para 0 para não disparar falso watchdog de crash no próximo boot
            self._clear_undervolt_canary()
            self._undervolt_active_in_hw = False
            self.settings.set("undervolt_core_mv", 0)
            self.settings.set("undervolt_cache_mv", 0)
            summary = (
                f"Falha ao aplicar undervolt: {', '.join(applied_details) if applied_details else 'Proteção de hardware ativa'}."
            )
            return False, summary

        if needs_hw_write and not undervolt_requested and not msr_written:
            self._undervolt_active_in_hw = False
            summary = (
                f"Não foi possível restaurar 0 mV no hardware: {', '.join(applied_details) if applied_details else 'Sem permissão root/Polkit'}."
            )
            return False, summary

        # Sucesso
        self._undervolt_active_in_hw = bool(msr_written and undervolt_requested)
        self.settings.set("undervolt_core_mv", core_mv)
        self.settings.set("undervolt_cache_mv", cache_mv)

        summary = (
            f"Offsets configurados: Core {core_mv} mV | Cache {cache_mv} mV | "
            f"GPU/AC Offset {gpu_ac_offset_w} W."
        )
        if applied_details:
            summary += " [" + ", ".join(applied_details) + "]"
        return True, summary

    def confirm_undervolt_stability(self) -> Tuple[bool, str]:
        """Confirma que o undervolt está estável dentro da janela de 15s e remove o canário."""
        self._clear_undervolt_canary()
        self._last_emergency_reset = ""
        return True, "Estabilidade confirmada! Offsets mantidos com segurança."

    def emergency_reset_undervolt(
        self,
        reason: str = "Reset de Emergência acionado",
        allow_elevation: bool = True,
    ) -> Tuple[bool, str]:
        """
        Mecanismo de Segurança / Reset de Emergência Imediato:
        Zera todos os offsets de tensão (Core = 0 mV, Cache = 0 mV), restaura o offset WMI padrão (20W)
        e remove o arquivo canário para prevenir travamentos ou Kernel Panic.
        Garante que MSR 0x150 seja manipulado exclusivamente em CPUs Intel e usa Polkit se necessário.
        """
        was_hw_active = bool(getattr(self, "_undervolt_active_in_hw", False))
        self._clear_undervolt_canary()

        self.settings.set("undervolt_core_mv", 0)
        self.settings.set("undervolt_cache_mv", 0)
        self.settings.set("gpu_ac_offset_w", 20)

        qt_plat = os.environ.get("QT_QPA_PLATFORM", "").lower()
        can_elevate = bool(
            allow_elevation
            and shutil.which("pkexec")
            and (qt_plat not in ("offscreen", "minimal") or os.environ.get("DUCKSVANTAGE_ALLOW_TEST_PKEXEC") == "1")
        )

        hw_reset_ok = False
        vendor = self.get_cpu_vendor()
        if vendor == "Intel":
            # Restaurar MSR 0x150 para 0 mV SOMENTE em Intel
            msr_nodes = sorted(glob.glob("/dev/cpu/[0-9]*/msr"))
            val_zero_core = self._encode_intel_msr_undervolt_offset(0, 0)
            val_zero_cache = self._encode_intel_msr_undervolt_offset(2, 0)
            if msr_nodes and os.access(msr_nodes[0], os.W_OK):
                try:
                    packed_zero_core = struct.pack("<Q", val_zero_core)
                    packed_zero_cache = struct.pack("<Q", val_zero_cache)
                    for mpath in msr_nodes:
                        fd = os.open(mpath, os.O_WRONLY)
                        try:
                            os.pwrite(fd, packed_zero_core, 0x150)
                            os.pwrite(fd, packed_zero_cache, 0x150)
                        finally:
                            os.close(fd)
                    hw_reset_ok = True
                except Exception:
                    pass
            elif can_elevate and (was_hw_active or msr_nodes):
                py_zero = (
                    "import glob, os, struct, subprocess, sys\n"
                    "vc, vca = int(sys.argv[1]), int(sys.argv[2])\n"
                    "subprocess.run(['modprobe', 'msr'], check=False)\n"
                    "pc, pca = struct.pack('<Q', vc), struct.pack('<Q', vca)\n"
                    "for p in sorted(glob.glob('/dev/cpu/[0-9]*/msr')):\n"
                    "    fd = os.open(p, os.O_WRONLY)\n"
                    "    try:\n"
                    "        os.pwrite(fd, pc, 0x150)\n"
                    "        os.pwrite(fd, pca, 0x150)\n"
                    "    finally:\n"
                    "        os.close(fd)\n"
                )
                try:
                    res = subprocess.run(
                        ["pkexec", sys.executable or "/usr/bin/python3", "-c", py_zero, str(val_zero_core), str(val_zero_cache)],
                        capture_output=True, text=True, timeout=15
                    )
                    hw_reset_ok = (res.returncode == 0)
                except Exception:
                    hw_reset_ok = False
        elif vendor == "AMD":
            if shutil.which("ryzenadj"):
                try:
                    res = subprocess.run(["ryzenadj", "--set-coall=0"], capture_output=True, text=True, timeout=5)
                    hw_reset_ok = (res.returncode == 0)
                    if not hw_reset_ok and can_elevate:
                        res2 = subprocess.run(["pkexec", "ryzenadj", "--set-coall=0"], capture_output=True, text=True, timeout=15)
                        hw_reset_ok = (res2.returncode == 0)
                except Exception:
                    pass

        if self.paths.lenovo_wmi_attr_dir:
            ac_off_path = os.path.join(self.paths.lenovo_wmi_attr_dir, "gpu_nv_ac_offset", "current_value")
            if os.path.exists(ac_off_path) and os.access(ac_off_path, os.W_OK):
                PermissionsManager.write_sysfs_value(ac_off_path, "20", allow_elevation=False)

        self._undervolt_active_in_hw = False
        if was_hw_active and not hw_reset_ok:
            self._last_emergency_reset = (
                f"{reason}: Configuração salva zerada para 0 mV, mas não foi possível gravar no registrador "
                "sem permissão root/Polkit. Reinicie o notebook para garantir 0 mV de fábrica."
            )
            return False, self._last_emergency_reset

        self._last_emergency_reset = f"{reason}: Tensões restauradas para 0 mV (Padrão Seguro de Fábrica)."
        return True, self._last_emergency_reset

