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
from core.settings import DEFAULT_FAN_CURVE_POINTS

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
    # ELITE 5: Mapeador de Teclas Personalizadas (Tecla Copilot F23 & Atalhos)
    # =========================================================================
    def get_key_mappings(self) -> Dict[str, Dict[str, Any]]:
        mappings = self.settings.get("key_mappings", {})
        if not isinstance(mappings, dict):
            return {}
        return mappings

    def update_key_mapping(self, slot_id: str, slot_data: Dict[str, Any]) -> None:
        mappings = self.get_key_mappings()
        mappings[slot_id] = slot_data
        self.settings.set("key_mappings", mappings)

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
                "accent": "#00d2ff" if new_hz > 60 else "#2fe08c"
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
                "accent": "#2fe08c" if new_state else "#00d2ff"
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
                "accent": "#2fe08c" if new_state else "#8b949e"
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
                "accent": "#00d2ff"
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
                "accent": "#ff9f0a" if new_state else "#2fe08c"
            }

        if action_id == "custom_command" and custom_cmd.strip():
            try:
                subprocess.Popen(custom_cmd.strip(), shell=True)
                return {
                    "action": action_id,
                    "ok": True,
                    "osd_type": "feature",
                    "title": "Comando Personalizado Executado",
                    "subtitle": custom_cmd.strip()[:48],
                    "icon": "copilot_key.svg",
                    "accent": "#9e3dff"
                }
            except Exception as e:
                return {"action": action_id, "ok": False, "error": str(e)}

        # Default ou toggle_window
        return {"action": "toggle_window", "ok": True, "osd_type": "window"}

    # =========================================================================
    # ELITE 6: Modo Viagem / Eco-Mode Extremo (1-Clique)
    # =========================================================================
    def get_eco_travel_mode(self) -> bool:
        return bool(self.settings.get("eco_travel_mode", False))

    def set_eco_travel_mode(self, enable: bool) -> Tuple[bool, str]:
        """
        Ativa/desativa o 'Modo Viagem (Eco-Mode Extremo)' com 1 clique:
        - Ativa o Modo de Conservação da Bateria (80%)
        - Força a GPU dedicada NVIDIA para suspensão profunda D3cold (PCI power/control = auto)
        - Desliga a iluminação do teclado (0)
        - Desativa o CPU Turbo Boost
        - Muda o perfil ACPI para 'low-power' e Governor para 'powersave'
        - Reduz o envelope térmico PL1/PL2 para 15W/25W
        """
        pairs: List[Tuple[str, str]] = []

        if enable:
            # Salvar estado anterior para restauração limpa
            self.settings.set("pre_eco_profile", self.get_platform_profile())
            self.settings.set("pre_eco_kbd", self.get_kbd_backlight())
            self.settings.set("pre_eco_turbo", self.get_cpu_turbo())

            if self.paths.conservation_mode:
                pairs.append((self.paths.conservation_mode, "1"))
                self.settings.set("rapid_charge", False)

            if self.paths.platform_profile:
                choices = self.get_platform_profile_choices()
                if choices:
                    low_p = "low-power" if "low-power" in choices else ("quiet" if "quiet" in choices else choices[0])
                    pairs.append((self.paths.platform_profile, low_p))

            if self.paths.cpu_turbo_intel:
                pairs.append((self.paths.cpu_turbo_intel, "1"))  # 1 = no_turbo (Turbo OFF)
            elif self.paths.cpu_turbo_amd:
                pairs.append((self.paths.cpu_turbo_amd, "0"))    # 0 = boost OFF

            if self.paths.kbd_backlight:
                pairs.append((self.paths.kbd_backlight, "0"))

            if self.paths.nvidia_pci_power_control:
                pairs.append((self.paths.nvidia_pci_power_control, "auto"))

            if self.paths.rapl_pl1 and self.paths.rapl_pl2:
                pairs.append((self.paths.rapl_pl1, str(15 * 1_000_000)))
                pairs.append((self.paths.rapl_pl2, str(25 * 1_000_000)))

            ok, msg = PermissionsManager.write_multiple_sysfs_values(pairs) if pairs else (True, "")
            if self.features.cpu_governor:
                gov_ok, gov_msg = self.set_cpu_governor("powersave")
                if not pairs:
                    ok, msg = gov_ok, gov_msg

            self.settings.set("eco_travel_mode", True)
            self._max_power_active = False
            self._last_raw_profile = self._read_raw_platform_profile()
            self._last_profile = "low-power"
            self._last_conservation = True
            self._last_kbd_bright = 0
            return ok, "Modo Viagem (Eco-Mode Extremo) ativado." if ok else msg
        else:
            prev_prof = self.normalize_profile(str(self.settings.get("pre_eco_profile", "balanced")))
            if prev_prof == "low-power":
                prev_prof = "balanced"
            prev_kbd = int(self.settings.get("pre_eco_kbd", 1))
            prev_turbo = bool(self.settings.get("pre_eco_turbo", True))

            if self.paths.platform_profile:
                pairs.append((self.paths.platform_profile, prev_prof))

            if self.paths.cpu_turbo_intel:
                pairs.append((self.paths.cpu_turbo_intel, "0" if prev_turbo else "1"))
            elif self.paths.cpu_turbo_amd:
                pairs.append((self.paths.cpu_turbo_amd, "1" if prev_turbo else "0"))

            if self.paths.kbd_backlight:
                pairs.append((self.paths.kbd_backlight, str(prev_kbd)))

            if self.paths.rapl_pl1 and self.paths.rapl_pl2:
                pl1_def = int(self.settings.get("custom_pl1_w", 45))
                pl2_def = int(self.settings.get("custom_pl2_w", 70))
                pairs.append((self.paths.rapl_pl1, str(pl1_def * 1_000_000)))
                pairs.append((self.paths.rapl_pl2, str(pl2_def * 1_000_000)))

            ok, msg = PermissionsManager.write_multiple_sysfs_values(pairs)
            self.settings.set("eco_travel_mode", False)
            if ok:
                self._max_power_active = (prev_prof == "max-power")
                self._last_raw_profile = self._read_raw_platform_profile()
                self._last_profile = prev_prof
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

    def set_custom_fan_curve(
        self,
        points: List[List[int]],
        enabled: bool,
        cpu_temp_limit: int = 94,
        gpu_temp_limit: int = 87,
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

        cpu_temp_limit = max(85, min(100, int(cpu_temp_limit)))
        gpu_temp_limit = max(75, min(87, int(gpu_temp_limit)))

        self.settings.set("custom_fan_curve_points", clean_pts)
        self.settings.set("custom_fan_curve_enabled", bool(enabled))
        self.settings.set("custom_cpu_temp_limit", cpu_temp_limit)
        self.settings.set("custom_gpu_temp_limit", gpu_temp_limit)

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
        if self.paths.lenovo_wmi_attr_dir:
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
            pwm_nodes = list(self._hwmon_pwm_nodes)
            if not pwm_nodes and self.paths.hwmon_pwm1:
                pwm_nodes = [(self.paths.hwmon_pwm1, self.paths.hwmon_pwm1_enable)]
            for _, en_p in pwm_nodes:
                if en_p and os.path.exists(en_p):
                    PermissionsManager.write_sysfs_value(en_p, "2", allow_elevation=False)
            if not pwm_nodes and self.paths.fan_mode and os.path.exists(self.paths.fan_mode) and not self._is_wmi_gamezone:
                PermissionsManager.write_sysfs_value(self.paths.fan_mode, "1", allow_elevation=False)
            self._last_applied_pwm = -1
            return True, "Curva customizada desativada. Controle automático original do EC restaurado."

    def apply_dynamic_fan_curve_tick(self, force: bool = False) -> Optional[int]:
        """
        Avalia a temperatura atual de CPU/GPU contra a curva de ventoinhas customizada
        e atualiza o PWM / Fan Mode no Embedded Controller da Lenovo de forma não-bloqueante.
        """
        if not bool(self.settings.get("custom_fan_curve_enabled", False)) and not force:
            return None

        cpu_temp = 45.0
        if self.paths.cpu_temp_input:
            cpu_temp = self._read_file_int(self.paths.cpu_temp_input, 45000) / 1000.0
        gpu_m = self.get_gpu_metrics()
        gpu_temp = gpu_m.temperature_c if gpu_m.available else 0.0
        hottest_temp = max(cpu_temp, gpu_temp)

        pts = self.settings.get("custom_fan_curve_points", DEFAULT_FAN_CURVE_POINTS)
        target_pwm_pct = self.interpolate_fan_pwm(pts, hottest_temp)

        # Evitar escritas redundantes no EC se a variação for menor que 4% (histerese térmica)
        if not force and self._last_applied_pwm >= 0 and abs(target_pwm_pct - self._last_applied_pwm) < 4:
            return self._last_applied_pwm

        self._last_applied_pwm = target_pwm_pct
        pwm_byte = int(round((target_pwm_pct / 100.0) * 255))

        # 1. Escrita direta em todos os nós hwmon pwm* expostos pelo kernel
        pwm_nodes = list(self._hwmon_pwm_nodes)
        if not pwm_nodes and self.paths.hwmon_pwm1:
            pwm_nodes = [(self.paths.hwmon_pwm1, self.paths.hwmon_pwm1_enable)]

        for pwm_p, en_p in pwm_nodes:
            if en_p and os.path.exists(en_p) and os.access(en_p, os.W_OK):
                PermissionsManager.write_sysfs_value(en_p, "1", allow_elevation=False)
            if os.path.exists(pwm_p) and (os.access(pwm_p, os.W_OK) or force):
                PermissionsManager.write_sysfs_value(pwm_p, str(pwm_byte), allow_elevation=False)

        # 2. Escrita no nó fan_mode do driver ideapad_acpi legado (apenas quando não há lenovo-wmi-gamezone)
        if self.paths.fan_mode and os.path.exists(self.paths.fan_mode) and not self._is_wmi_gamezone:
            if target_pwm_pct == 0 and hottest_temp < 52.0:
                ec_mode = "0"
            elif target_pwm_pct < 55:
                ec_mode = "1"
            elif target_pwm_pct < 85:
                ec_mode = "4"
            else:
                ec_mode = "2"
            if os.access(self.paths.fan_mode, os.W_OK) or force:
                PermissionsManager.write_sysfs_value(self.paths.fan_mode, ec_mode, allow_elevation=False)

        return target_pwm_pct

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

            # Fallback para Intel via wrmsr, intel-undervolt ou escrita direta MSR via pkexec + python3
            if not msr_written and (core_mv != 0 or cache_mv != 0):
                if shutil.which("wrmsr") and shutil.which("pkexec"):
                    try:
                        cmd = f"wrmsr -a 0x150 {msr_core_hex} && wrmsr -a 0x150 {msr_cache_hex}"
                        res = subprocess.run(["pkexec", "sh", "-c", cmd], capture_output=True, text=True, timeout=10)
                        if res.returncode == 0:
                            msr_written = True
                            applied_details.append(f"wrmsr 0x150 ({msr_core_hex})")
                        else:
                            applied_details.append("MSR 0x150 bloqueado (OC Lock ativo na BIOS)")
                    except Exception:
                        pass
                elif shutil.which("intel-undervolt") and shutil.which("pkexec"):
                    try:
                        res = subprocess.run(["pkexec", "intel-undervolt", "apply"], capture_output=True, text=True, timeout=10)
                        if res.returncode == 0:
                            msr_written = True
                            applied_details.append("intel-undervolt service")
                    except Exception:
                        pass
                elif not direct_msr_attempted and msr_nodes and shutil.which("pkexec"):
                    py_script = (
                        "import glob, os, struct, sys\n"
                        "vc, vca = int(sys.argv[1]), int(sys.argv[2])\n"
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
                            else:
                                applied_details.append(f"MSR 0x150 falhou via Polkit (código {res.returncode})")
                    except Exception as e:
                        applied_details.append(f"Falha ao executar Polkit MSR ({e})")

        elif vendor == "AMD":
            # CPUs AMD: JAMAIS escrever no MSR 0x150! Usar ryzenadj Curve Optimizer
            if core_mv != 0:
                co_counts = max(-30, min(0, core_mv // 5))
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
                if not msr_written:
                    applied_details.append("AMD ryzenadj necessário para Curve Optimizer")
            else:
                msr_written = True
        else:
            applied_details.append("Processador genérico: undervolt não suportado")

        # 4. Avaliação de estabilidade e persistência de settings
        undervolt_requested = (core_mv != 0 or cache_mv != 0)
        if undervolt_requested and not msr_written:
            # Reverte canário e settings para 0 para não disparar falso watchdog de crash no próximo boot
            self._clear_undervolt_canary()
            self.settings.set("undervolt_core_mv", 0)
            self.settings.set("undervolt_cache_mv", 0)
            summary = (
                f"Falha ao aplicar undervolt: {', '.join(applied_details) if applied_details else 'Proteção de hardware ativa'}."
            )
            return False, summary

        # Sucesso
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

    def emergency_reset_undervolt(self, reason: str = "Reset de Emergência acionado") -> Tuple[bool, str]:
        """
        Mecanismo de Segurança / Reset de Emergência Imediato:
        Zera todos os offsets de tensão (Core = 0 mV, Cache = 0 mV), restaura o offset WMI padrão (20W)
        e remove o arquivo canário para prevenir travamentos ou Kernel Panic.
        Garante que MSR 0x150 seja manipulado exclusivamente em CPUs Intel.
        """
        self._clear_undervolt_canary()

        self.settings.set("undervolt_core_mv", 0)
        self.settings.set("undervolt_cache_mv", 0)
        self.settings.set("gpu_ac_offset_w", 20)

        vendor = self.get_cpu_vendor()
        if vendor == "Intel":
            # Restaurar MSR 0x150 para 0 mV SOMENTE em Intel se acessível diretamente sem bloquear
            msr_nodes = sorted(glob.glob("/dev/cpu/[0-9]*/msr"))
            if msr_nodes and os.access(msr_nodes[0], os.W_OK):
                try:
                    packed_zero_core = struct.pack("<Q", self._encode_intel_msr_undervolt_offset(0, 0))
                    packed_zero_cache = struct.pack("<Q", self._encode_intel_msr_undervolt_offset(2, 0))
                    for mpath in msr_nodes:
                        fd = os.open(mpath, os.O_WRONLY)
                        try:
                            os.pwrite(fd, packed_zero_core, 0x150)
                            os.pwrite(fd, packed_zero_cache, 0x150)
                        finally:
                            os.close(fd)
                except Exception:
                    pass
        elif vendor == "AMD":
            if shutil.which("ryzenadj"):
                try:
                    subprocess.run(["ryzenadj", "--set-coall=0"], capture_output=True, text=True, timeout=5)
                except Exception:
                    pass

        if self.paths.lenovo_wmi_attr_dir:
            ac_off_path = os.path.join(self.paths.lenovo_wmi_attr_dir, "gpu_nv_ac_offset", "current_value")
            if os.path.exists(ac_off_path) and os.access(ac_off_path, os.W_OK):
                PermissionsManager.write_sysfs_value(ac_off_path, "20", allow_elevation=False)

        self._last_emergency_reset = f"{reason}: Tensões restauradas para 0 mV (Padrão Seguro de Fábrica)."
        return True, self._last_emergency_reset

