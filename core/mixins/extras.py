"""Mixin de Presets do Usuário, Diagnóstico Técnico, Preferências, Teclado RGB 4-Zonas e Atualizações GitHub."""

import fcntl
import glob
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple
from core.permissions import PermissionsManager

APP_VERSION = "2.2.0"
GITHUB_REPO = "Patopatetico2-lab/DucksVantage"


class PresetsDiagnosticsRgbMixin:
    """Presets personalizados, diagnóstico Markdown, preferências/backup, RGB ITE/sysfs e update check."""

    # =========================================================================
    # Perfis Personalizados Salváveis pelo Usuário (Presets em 1 Clique)
    # =========================================================================
    def get_user_presets(self) -> List[Dict[str, Any]]:
        """Retorna a lista de presets personalizados salvos pelo usuário."""
        raw = self.settings.get("user_presets", [])
        if not isinstance(raw, list):
            return []
        return [dict(item) for item in raw if isinstance(item, dict) and item.get("id") and item.get("name")]

    def format_user_preset_summary(self, preset: Dict[str, Any]) -> str:
        """Retorna um resumo curto legível dos parâmetros contidos em um preset."""
        parts: List[str] = []
        if "profile" in preset and preset["profile"]:
            pinfo = self.get_profile_info(str(preset["profile"]))
            parts.append(pinfo.get("short_title", str(preset["profile"]).upper()))
        if "governor" in preset and preset["governor"]:
            parts.append(f"Gov {str(preset['governor'])}")
        if "turbo_enabled" in preset:
            parts.append("Turbo On" if preset["turbo_enabled"] else "Turbo Off")
        if "pl1_w" in preset and "pl2_w" in preset:
            parts.append(f"TDP {preset['pl1_w']}/{preset['pl2_w']}W")
        if preset.get("fan_curve_enabled"):
            parts.append("Curva EC")
        if isinstance(preset.get("wmi_custom_power"), dict) and "gpu_nv_ctgp" in preset["wmi_custom_power"]:
            parts.append(f"cTGP {preset['wmi_custom_power']['gpu_nv_ctgp']}W")
        if "refresh_hz" in preset and preset["refresh_hz"]:
            parts.append(f"{preset['refresh_hz']} Hz")
        return " • ".join(parts) if parts else "Preset vazio"

    def save_current_as_preset(self, name: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Captura o estado atual suportado do notebook e salva como preset de 1 clique."""
        clean_name = " ".join((name or "").split())[:40]
        if not clean_name:
            return False, "Informe um nome para o preset personalizado.", None

        preset_id = re.sub(r"[^a-z0-9]+", "-", clean_name.lower()).strip("-")
        if not preset_id:
            preset_id = f"preset-{int(time.time())}"

        preset: Dict[str, Any] = {
            "id": preset_id,
            "name": clean_name,
        }
        captured_any = False

        if self.features.platform_profile:
            preset["profile"] = self.normalize_profile(self.get_platform_profile())
            captured_any = True
        if self.features.cpu_governor:
            preset["governor"] = self.get_cpu_governor()
            captured_any = True
        if self.features.turbo_boost:
            preset["turbo_enabled"] = bool(self.get_cpu_turbo())
            captured_any = True
        if self.features.custom_tdp:
            pl1_w, pl2_w = self.get_cpu_tdp_limits()
            preset["pl1_w"] = int(pl1_w)
            preset["pl2_w"] = int(pl2_w)
            captured_any = True
        if self.features.fan_control:
            fan_cfg = self.get_custom_fan_curve()
            preset["fan_curve_enabled"] = bool(fan_cfg.get("enabled", False))
            preset["fan_curve_points"] = list(fan_cfg.get("points", []))
            if "cpu_temp_limit" in fan_cfg:
                preset["cpu_temp_limit"] = int(fan_cfg["cpu_temp_limit"])
            if "gpu_temp_limit" in fan_cfg:
                preset["gpu_temp_limit"] = int(fan_cfg["gpu_temp_limit"])
            captured_any = True
        if self.features.wmi_custom_power and preset.get("profile") == "custom":
            try:
                ctrls = self.get_lenovo_custom_power_controls()
                if ctrls:
                    preset["wmi_custom_power"] = {c["attr_id"]: int(c["current"]) for c in ctrls}
                    captured_any = True
            except Exception:
                pass
        if self.features.refresh_rate:
            try:
                ref_info = self.get_display_refresh_info()
                if ref_info.available and len(ref_info.available_rates) > 1:
                    preset["refresh_hz"] = int(ref_info.current_hz)
                    captured_any = True
            except Exception:
                pass

        if not captured_any:
            return False, "Nenhum parâmetro de desempenho controlável foi detectado neste hardware.", None

        presets = self.get_user_presets()
        replaced = False
        for idx, existing in enumerate(presets):
            if existing.get("id") == preset_id:
                presets[idx] = preset
                replaced = True
                break
        if not replaced:
            if len(presets) >= 12:
                return False, "Limite máximo de 12 presets atingido. Remova um antigo para salvar.", None
            presets.append(preset)

        self.settings.set("user_presets", presets)
        summary = self.format_user_preset_summary(preset)
        return True, f"Preset '{clean_name}' {'atualizado' if replaced else 'salvo'}: {summary}", preset

    def apply_user_preset(self, preset_id: str, allow_elevation: bool = True) -> Tuple[bool, str]:
        """Aplica todas as configurações suportadas de um preset salvo."""
        presets = self.get_user_presets()
        target = next((p for p in presets if p.get("id") == preset_id), None)
        if not target:
            return False, "Preset personalizado não encontrado."

        applied_parts: List[str] = []
        errors: List[str] = []

        if "profile" in target and self.features.platform_profile:
            prof = self.normalize_profile(str(target["profile"]))
            ok, msg = self.set_platform_profile(prof, allow_elevation=allow_elevation)
            if ok:
                applied_parts.append(self.get_profile_info(prof).get("short_title", prof.upper()))
            else:
                errors.append(f"Perfil: {msg}")

        if "governor" in target and self.features.cpu_governor:
            gov = str(target["governor"])
            ok, msg = self.set_cpu_governor(gov, allow_elevation=allow_elevation)
            if ok:
                applied_parts.append(f"Gov {gov}")
            else:
                errors.append(f"Governor: {msg}")

        if "turbo_enabled" in target and self.features.turbo_boost:
            tb = bool(target["turbo_enabled"])
            ok, msg = self.set_cpu_turbo(tb, allow_elevation=allow_elevation)
            if ok:
                applied_parts.append("Turbo On" if tb else "Turbo Off")
            else:
                errors.append(f"Turbo: {msg}")

        if "pl1_w" in target and "pl2_w" in target and self.features.custom_tdp:
            ok, msg = self.set_cpu_tdp_limits(int(target["pl1_w"]), int(target["pl2_w"]), allow_elevation=allow_elevation)
            if ok:
                applied_parts.append(f"TDP {target['pl1_w']}/{target['pl2_w']}W")
            else:
                errors.append(f"TDP: {msg}")

        if "fan_curve_enabled" in target and "fan_curve_points" in target and self.features.fan_control:
            ok_fc, msg_fc = self.set_custom_fan_curve(
                target["fan_curve_points"],
                bool(target["fan_curve_enabled"]),
                target.get("cpu_temp_limit"),
                target.get("gpu_temp_limit"),
            )
            if ok_fc and target["fan_curve_enabled"]:
                applied_parts.append("Curva EC")
            elif not ok_fc:
                errors.append(f"Fan EC: {msg_fc}")

        if isinstance(target.get("wmi_custom_power"), dict) and self.features.wmi_custom_power:
            ok_wmi, msg_wmi = self.set_lenovo_custom_power_values(
                target["wmi_custom_power"], allow_elevation=allow_elevation
            )
            if ok_wmi:
                applied_parts.append("WMI Custom")
            else:
                errors.append(f"WMI Custom: {msg_wmi}")

        if "refresh_hz" in target and self.features.refresh_rate:
            hz = int(target["refresh_hz"])
            ok, msg = self.set_refresh_rate(hz)
            if ok:
                applied_parts.append(f"{hz} Hz")
            else:
                errors.append(f"Tela: {msg}")

        if applied_parts:
            summary = " • ".join(applied_parts)
            if errors:
                summary += f" (Avisos: {'; '.join(errors)})"
            return True, summary

        return False, "; ".join(errors) if errors else "Nenhum parâmetro aplicável neste hardware."

    def delete_user_preset(self, preset_id: str) -> Tuple[bool, str]:
        """Remove um preset personalizado salvo pelo ID."""
        presets = self.get_user_presets()
        filtered = [p for p in presets if p.get("id") != preset_id]
        if len(filtered) == len(presets):
            return False, "Preset não encontrado."
        self.settings.set("user_presets", filtered)
        return True, "Preset removido com sucesso."

    def export_user_preset_to_file(self, preset_id: str, dst_path: str) -> Tuple[bool, str]:
        """Exporta um preset 1-clique completo (perfil, TDP, curva EC, Hz) para JSON."""
        presets = self.get_user_presets()
        target = next((p for p in presets if p.get("id") == preset_id), None)
        if not target:
            return False, "Preset não encontrado."
        try:
            parent = os.path.dirname(os.path.abspath(dst_path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(dst_path, "w", encoding="utf-8") as fh:
                json.dump({"ducksvantage_preset": target}, fh, indent=2, ensure_ascii=False)
            return True, f"Preset '{target['name']}' exportado para {os.path.basename(dst_path)}."
        except Exception as e:
            return False, f"Falha ao exportar preset: {e}"

    def import_user_preset_from_file(self, src_path: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Importa um preset 1-clique de arquivo JSON validando seus campos."""
        if not src_path or not os.path.exists(src_path):
            return False, "Arquivo de preset não encontrado.", None
        try:
            with open(src_path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            obj = raw.get("ducksvantage_preset", raw) if isinstance(raw, dict) else None
            if not isinstance(obj, dict) or not obj.get("name"):
                return False, "Arquivo JSON não contém um preset Ducksvantage válido.", None

            clean_name = " ".join(str(obj["name"]).split())[:40]
            pid = str(obj.get("id") or re.sub(r"[^a-z0-9]+", "-", clean_name.lower()).strip("-")) or f"preset-{int(time.time())}"
            imported = dict(obj)
            imported["id"] = pid
            imported["name"] = clean_name

            presets = self.get_user_presets()
            replaced = False
            for idx, cur in enumerate(presets):
                if cur.get("id") == pid:
                    presets[idx] = imported
                    replaced = True
                    break
            if not replaced:
                if len(presets) >= 12:
                    return False, "Limite máximo de 12 presets atingido.", None
                presets.append(imported)
            self.settings.set("user_presets", presets)
            return True, f"Preset '{clean_name}' importado ({self.format_user_preset_summary(imported)}).", imported
        except Exception as e:
            return False, f"Falha ao importar preset: {e}", None

    # =========================================================================
    # Diagnóstico Técnico Completo para Suporte e Issues (Sem Dados Pessoais)
    # =========================================================================
    def generate_hardware_diagnostic_report(self) -> str:
        """
        Gera um relatório técnico completo em Markdown (DMI, BIOS, CPU/EPP/RAPL,
        GPU/MUX/Tela, Bateria, Módulos de Kernel, Atributos WMI, Capacidades e UDEV)
        sem expor nome de usuário, hostname ou número de série.
        """
        sys_i = self.system_info
        lines: List[str] = [
            "# Ducksvantage Hardware & Kernel Diagnostic Report",
            "",
            "## Sistema & DMI",
            f"- **Modelo:** {sys_i.sys_vendor} {sys_i.display_model_name} ({sys_i.product_name})",
            f"- **Linha Detectada:** {sys_i.laptop_line} (Board: `{sys_i.board_name}`)",
            f"- **BIOS:** `{sys_i.bios_version}` ({sys_i.bios_date})",
            f"- **OS / Kernel:** {sys_i.os_name} | Kernel `{sys_i.kernel_version}`",
            f"- **Sessão Gráfica:** `{os.environ.get('XDG_SESSION_TYPE', 'N/A')}` ({os.environ.get('XDG_CURRENT_DESKTOP', 'N/A')})",
            f"- **Armazenamento:** {sys_i.ssd_summary}",
        ]

        # CPU / EPP / TDP
        lines.append("")
        lines.append("## CPU & Energia")
        try:
            cpu_m = self.get_cpu_metrics()
            epp_cur = self._read_file_text("/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference") or "N/A"
            epp_avail = self._read_file_text("/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_available_preferences") or "N/A"
            lines.append(f"- **CPU:** {cpu_m.model_name} ({cpu_m.vendor}, {cpu_m.cores_count} threads)")
            lines.append(f"- **Governor Ativo:** `{cpu_m.governor}` (Disponíveis: `{' '.join(cpu_m.available_governors) or 'N/A'}`)")
            lines.append(f"- **EPP:** `{epp_cur}` (Disponíveis: `{epp_avail}`)")
            lines.append(f"- **Turbo Boost:** `{cpu_m.turbo_enabled}` (Suportado: `{self.features.turbo_boost}`)")
            lines.append(f"- **RAPL TDP:** PL1=`{cpu_m.pl1_w}W` | PL2=`{cpu_m.pl2_w}W` (Suportado: `{self.features.custom_tdp}`)")
        except Exception as e:
            lines.append(f"- *Falha ao coletar CPU:* {e}")

        # Perfis Térmicos & Fans
        lines.append("")
        lines.append("## Perfis Térmicos & Refrigeração")
        try:
            active_prof = self.get_platform_profile()
            choices = self.get_platform_profile_choices()
            fan_m = self.get_fan_metrics()
            lines.append(f"- **Platform Profile Ativo:** `{active_prof}` | Nó: `{self.paths.platform_profile or 'N/A'}`")
            lines.append(f"- **Perfis Expostos pelo Kernel:** `{' '.join(choices) or 'N/A'}` (Max-Power={self.features.max_power_profile})")
            lines.append(f"- **Ventoinhas:** Fan1=`{fan_m.rpm} RPM` | Fan2=`{fan_m.second_rpm} RPM` | Status=`{fan_m.status_label}` (Controle PWM={self.features.fan_control})")
        except Exception as e:
            lines.append(f"- *Falha ao coletar térmico:* {e}")

        # GPU, MUX & Tela
        lines.append("")
        lines.append("## GPU, MUX & Tela")
        try:
            gpu_m = self.get_gpu_metrics()
            mux = self.get_gpu_mux_info()
            ref = self.get_display_refresh_info()
            lines.append(f"- **GPU:** {gpu_m.name} | Estado=`{gpu_m.runtime_state}` | P-State=`{gpu_m.pstate}`")
            lines.append(f"- **GPU MUX:** Backend=`{mux.backend_name}` | Atual=`{mux.current_mode}` | Modos=`{mux.available_modes}`")
            lines.append(f"- **Display:** `{ref.display_name or 'N/A'}` ({ref.resolution or 'N/A'}) @ `{ref.current_hz} Hz` | Taxas=`{ref.available_rates}` | Backend=`{ref.backend_name}`")
            lines.append(f"- **LCD Overdrive:** Suportado=`{self.features.lcd_overdrive}`")
        except Exception as e:
            lines.append(f"- *Falha ao coletar GPU/Tela:* {e}")

        # Bateria
        lines.append("")
        lines.append("## Bateria")
        try:
            bat = self.get_battery_info()
            if bat.available:
                lines.append(
                    f"- **Carga:** {bat.capacity_percent}% ({bat.status}, AC=`{bat.ac_connected}`) | "
                    f"**Saúde:** {bat.health_percent:.1f}% ({bat.energy_full_wh:.2f}/{bat.energy_design_wh:.2f} Wh, `{bat.cycle_count}` ciclos)"
                )
                lines.append(
                    f"- **Controles:** Conservação={self.features.conservation_mode} (ativo=`{bat.conservation_mode_active}`) | "
                    f"Rapid Charge={self.features.rapid_charge} (ativo=`{bat.rapid_charge_active}`)"
                )
            else:
                lines.append("- Bateria não detectada.")
        except Exception as e:
            lines.append(f"- *Falha ao coletar bateria:* {e}")

        # Armazenamento NVMe SMART
        if self.features.nvme_health:
            lines.append("")
            lines.append("## Armazenamento NVMe SMART")
            try:
                nv_list = self.get_nvme_health_info()
                for d in nv_list:
                    h_txt = f"{d['health_percent']}%" if d.get("health_percent") is not None else "N/A"
                    lines.append(
                        f"- `{d['device']}` ({d['model']} / FW `{d['firmware']}`): "
                        f"Saúde `{h_txt}` ({d['badge']}) | Temp `{d['temp_c']}°C` | "
                        f"TBW `{d['tbw_tb']} TB` | `{d['power_on_hours']}h`"
                    )
            except Exception as e:
                lines.append(f"- *Falha ao coletar SMART NVMe:* {e}")

        # Módulos do Kernel Relevantes
        lines.append("")
        lines.append("## Módulos de Kernel Relevantes")
        try:
            mods_raw = self._read_file_text("/proc/modules") or ""
            keywords = ("lenovo", "ideapad", "legion", "thinkpad", "yoga", "wmi", "nvidia", "amdgpu", "i915", "xe", "acpi")
            loaded = []
            for mline in mods_raw.splitlines():
                mname = mline.split(" ", 1)[0].strip()
                if mname and any(k in mname.lower() for k in keywords):
                    loaded.append(mname)
            loaded = sorted(set(loaded))[:25]
            lines.append(f"- `{', '.join(loaded) if loaded else 'Nenhum módulo específico listado'}`")
        except Exception as e:
            lines.append(f"- *Falha ao ler /proc/modules:* {e}")

        # BIOS WMI Attributes
        lines.append("")
        lines.append("## Atributos Lenovo BIOS WMI")
        try:
            attrs = self.get_bios_attributes()
            if attrs:
                preview = ", ".join(f"`{a.attr_id}={a.current_value}`" for a in attrs[:20])
                lines.append(f"- Total `{len(attrs)}` atributos graváveis: {preview}")
            else:
                lines.append("- Nenhum atributo gravável em `/sys/class/firmware-attributes/*/attributes`.")
        except Exception as e:
            lines.append(f"- *Falha ao listar BIOS WMI:* {e}")

        # Capacidades UI & Status UDEV
        lines.append("")
        lines.append("## Capacidades & Permissões UDEV")
        try:
            caps = self.get_detected_capabilities()
            cap_str = ", ".join(f"{c['name']} ({c['detail']})" for c in caps)
            lines.append(f"- **Capacidades ({len(caps)}):** {cap_str or 'Nenhuma proprietária'}")
            lines.append(
                f"- **UDEV:** instalada=`{PermissionsManager.is_udev_rule_installed()}` | "
                f"atualizada=`{PermissionsManager.is_udev_rule_up_to_date()}` | "
                f"escrita_direta=`{self.has_full_write_permissions()}`"
            )
        except Exception as e:
            lines.append(f"- *Falha ao coletar capacidades/UDEV:* {e}")

        return "\n".join(lines)

    # =========================================================================
    # Preferências Gerais do Aplicativo, OSD, AC/Bateria e Backup JSON
    # =========================================================================
    def get_osd_enabled(self) -> bool:
        return bool(self.settings.get("osd_enabled", True))

    def set_osd_enabled(self, enabled: bool) -> None:
        self.settings.set("osd_enabled", bool(enabled))

    def get_osd_position(self) -> str:
        pos = str(self.settings.get("osd_position", "bottom-center") or "bottom-center")
        return pos if pos in ("bottom-center", "top-center", "top-right") else "bottom-center"

    def set_osd_position(self, pos: str) -> None:
        if pos not in ("bottom-center", "top-center", "top-right"):
            pos = "bottom-center"
        self.settings.set("osd_position", pos)

    def get_osd_duration_ms(self) -> int:
        try:
            val = int(self.settings.get("osd_duration_ms", 1800))
        except (TypeError, ValueError):
            val = 1800
        return max(1000, min(4000, val))

    def set_osd_duration_ms(self, duration_ms: int) -> None:
        clamped = max(1000, min(4000, int(duration_ms)))
        self.settings.set("osd_duration_ms", clamped)

    def get_minimize_to_tray(self) -> bool:
        return bool(self.settings.get("minimize_to_tray", True))

    def set_minimize_to_tray(self, enabled: bool) -> None:
        self.settings.set("minimize_to_tray", bool(enabled))

    def get_ui_mode(self) -> str:
        val = str(self.settings.get("ui_mode", "basic") or "basic").strip().lower()
        return "advanced" if val == "advanced" else "basic"

    def set_ui_mode(self, mode: str) -> None:
        norm = "advanced" if str(mode or "").strip().lower() == "advanced" else "basic"
        self.settings.set("ui_mode", norm)

    def is_advanced_mode(self) -> bool:
        return self.get_ui_mode() == "advanced"

    def get_ac_profile(self) -> str:
        raw = str(self.settings.get("ac_profile", "performance") or "performance")
        norm = self.normalize_profile(raw)
        supported = self.get_supported_canonical_profiles()
        if supported and norm not in supported:
            return "performance" if "performance" in supported else ("balanced" if "balanced" in supported else supported[-1])
        return norm

    def set_ac_profile(self, profile: str) -> None:
        self.settings.set("ac_profile", self.normalize_profile(profile))

    def get_battery_profile(self) -> str:
        raw = str(self.settings.get("battery_profile", "low-power") or "low-power")
        norm = self.normalize_profile(raw)
        supported = self.get_supported_canonical_profiles()
        if supported and norm not in supported:
            return "low-power" if "low-power" in supported else ("balanced" if "balanced" in supported else supported[0])
        return norm

    def set_battery_profile(self, profile: str) -> None:
        self.settings.set("battery_profile", self.normalize_profile(profile))

    def export_settings(self, dst_path: str) -> Tuple[bool, str]:
        return self.settings.export_to_file(dst_path)

    def import_settings(self, src_path: str) -> Tuple[bool, str]:
        ok, msg = self.settings.import_from_file(src_path)
        if ok:
            self._cached_running_game = None
            self._last_game_scan_time = 0.0
        return ok, msg

    # =========================================================================
    # Teclado RGB 4-Zonas (Auto-Discovery USB ITE hidraw / multicolor sysfs)
    # =========================================================================
    def _scan_rgb_keyboard(self) -> None:
        """Detecta teclados RGB 4-zonas Lenovo Legion/LOQ via hidraw (ITE 048d) ou sysfs multicolor."""
        self.paths.rgb_hidraw = None
        self.paths.rgb_sysfs_dir = None
        self._rgb_backend_name = "none"
        self.features.rgb_keyboard = False

        # 1. Controlador USB ITE 4-Zone (048d:c9xx / 048d:c1xx) em /sys/class/hidraw/
        for hdir in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
            uevent = self._read_file_text(os.path.join(hdir, "device", "uevent")) or ""
            hid_up = uevent.upper()
            if "0000048D" in hid_up and re.search(r"0000048D:0000C[19][0-9A-F]{2}", hid_up):
                dev_path = f"/dev/{os.path.basename(hdir)}"
                if os.path.exists(dev_path):
                    self.paths.rgb_hidraw = dev_path
                    self._rgb_backend_name = "ite-hidraw"
                    self.features.rgb_keyboard = True
                    return

        # 2. Fallback: sysfs LEDs multicolor (multi_intensity)
        for led_dir in sorted(glob.glob("/sys/class/leds/*rgb*") + glob.glob("/sys/class/leds/*kbd_backlight*")):
            mi = os.path.join(led_dir, "multi_intensity")
            if os.path.exists(mi):
                self.paths.rgb_sysfs_dir = led_dir
                self._rgb_backend_name = "sysfs-multicolor"
                self.features.rgb_keyboard = True
                return

    @staticmethod
    def _parse_hex_rgb(hex_color: str) -> Tuple[int, int, int]:
        clean = str(hex_color or "").strip().lstrip("#")
        if len(clean) == 6:
            try:
                return int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16)
            except ValueError:
                pass
        return 0, 210, 255

    @classmethod
    def _build_ite_rgb_packet(cls, mode: str, zones: List[str], brightness: int, speed: int) -> bytes:
        """Constrói pacote HID Feature Report de 33 bytes para teclados Lenovo ITE 4-Zonas."""
        mode_map = {
            "off": 0x01,
            "static": 0x01,
            "breath": 0x03,
            "wave": 0x04,
            "smooth": 0x06,
        }
        m_low = (mode or "static").lower().strip()
        effect_byte = mode_map.get(m_low, 0x01)
        br = 0 if m_low == "off" else max(1, min(2, int(brightness)))
        spd = max(1, min(4, int(speed)))

        pkt = bytearray(33)
        pkt[0] = 0xCC
        pkt[1] = 0x16
        pkt[2] = effect_byte
        pkt[3] = spd
        pkt[4] = br

        safe_zones = list(zones or [])
        while len(safe_zones) < 4:
            safe_zones.append("#00d2ff")
        for idx in range(4):
            r, g, b = (0, 0, 0) if m_low == "off" else cls._parse_hex_rgb(safe_zones[idx])
            base = 5 + (idx * 3)
            pkt[base] = r
            pkt[base + 1] = g
            pkt[base + 2] = b

        pkt[18] = 1 if m_low == "wave" else 0
        return bytes(pkt)

    def get_rgb_keyboard_state(self) -> Dict[str, Any]:
        zones = self.settings.get("rgb_zones", ["#00d2ff", "#00d2ff", "#00d2ff", "#00d2ff"])
        if not isinstance(zones, list) or len(zones) != 4:
            zones = ["#00d2ff", "#00d2ff", "#00d2ff", "#00d2ff"]
        return {
            "supported": bool(self.features.rgb_keyboard),
            "backend": self._rgb_backend_name,
            "mode": str(self.settings.get("rgb_mode", "static")),
            "brightness": int(self.settings.get("rgb_brightness", 2)),
            "speed": int(self.settings.get("rgb_speed", 2)),
            "zones": [str(z) for z in zones],
        }

    def set_rgb_keyboard_state(self, mode: str, zones: List[str], brightness: int = 2, speed: int = 2) -> Tuple[bool, str]:
        """Aplica cores e efeito no teclado RGB 4-zonas (hidraw ITE ou sysfs multicolor)."""
        if not self.features.rgb_keyboard:
            return False, "Teclado RGB 4-Zonas não detectado neste dispositivo."

        m_low = (mode or "static").lower().strip()
        if m_low not in ("static", "breath", "wave", "smooth", "off"):
            m_low = "static"
        br = max(0, min(2, int(brightness)))
        spd = max(1, min(4, int(speed)))
        safe_zones = [str(z) for z in (zones or ["#00d2ff"] * 4)][:4]
        while len(safe_zones) < 4:
            safe_zones.append("#00d2ff")

        if self.paths.rgb_hidraw and os.path.exists(self.paths.rgb_hidraw):
            pkt = self._build_ite_rgb_packet(m_low, safe_zones, br, spd)
            hidiocsfeature = (3 << 30) | (len(pkt) << 16) | (ord("H") << 8) | 0x06
            try:
                fd = os.open(self.paths.rgb_hidraw, os.O_RDWR)
                try:
                    buf = bytearray(pkt)
                    fcntl.ioctl(fd, hidiocsfeature, buf)
                finally:
                    os.close(fd)
            except PermissionError:
                return False, (
                    f"Sem permissão em {self.paths.rgb_hidraw}. "
                    "Atualize as Regras UDEV na aba 'Sobre o Dispositivo' para liberar hidraw 048d."
                )
            except Exception as e:
                return False, f"Falha ao enviar comando RGB ITE em {self.paths.rgb_hidraw}: {e}"
        elif self.paths.rgb_sysfs_dir:
            mi_path = os.path.join(self.paths.rgb_sysfs_dir, "multi_intensity")
            br_path = os.path.join(self.paths.rgb_sysfs_dir, "brightness")
            r, g, b = (0, 0, 0) if m_low == "off" else self._parse_hex_rgb(safe_zones[0])
            ok_mi, msg_mi = PermissionsManager.write_sysfs_value(mi_path, f"{r} {g} {b}", allow_elevation=True)
            if not ok_mi:
                return False, msg_mi
            if os.path.exists(br_path):
                PermissionsManager.write_sysfs_value(br_path, str(0 if m_low == "off" else br), allow_elevation=True)
        else:
            return False, "Interface de teclado RGB indisponível."

        self.settings.set("rgb_mode", m_low)
        self.settings.set("rgb_brightness", br)
        self.settings.set("rgb_speed", spd)
        self.settings.set("rgb_zones", safe_zones)
        return True, f"Iluminação RGB aplicada ({m_low.upper()}, brilho {br})."

    # =========================================================================
    # Verificador Manual de Atualizações no GitHub (Zero Telemetria)
    # =========================================================================
    @staticmethod
    def _parse_semver_tuple(ver_str: str) -> Optional[Tuple[int, ...]]:
        """Extrai tupla numérica de versão (ex: 'v2.1.0' -> (2, 1, 0))."""
        m = re.search(r"(\d+(?:\.\d+)*)", str(ver_str or "").strip())
        if not m:
            return None
        return tuple(int(p) for p in m.group(1).split("."))

    def _fetch_github_json(self, api_url: str, timeout: float = 5.0) -> Any:
        req = urllib.request.Request(
            api_url,
            headers={
                "User-Agent": f"Ducksvantage/{APP_VERSION}",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))

    def check_for_updates(self, timeout: float = 5.0) -> Dict[str, Any]:
        """
        Consulta manualmente atualizações em GITHUB_REPO:
        - Em clone Git (.git presente): compara commit SHA local com commits/main remoto.
        - Em instalação empacotada (/opt/ducksvantage sem .git): compara APP_VERSION com
          releases/latest ou tags do repositório para evitar falsos positivos.
        """
        repo_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        local_sha = ""
        if shutil.which("git") and os.path.isdir(os.path.join(repo_dir, ".git")):
            try:
                res = subprocess.run(
                    ["git", "-C", repo_dir, "rev-parse", "--short", "HEAD"],
                    capture_output=True, text=True, timeout=2
                )
                if res.returncode == 0:
                    local_sha = res.stdout.strip()
            except Exception:
                pass

        repo_web_url = f"https://github.com/{GITHUB_REPO}"
        try:
            # 1. Modo Git Clone: comparar SHA do commit local com main
            if local_sha:
                data = self._fetch_github_json(
                    f"https://api.github.com/repos/{GITHUB_REPO}/commits/main",
                    timeout=timeout,
                )
                remote_full = str((data or {}).get("sha", "")).strip()
                remote_sha = remote_full[:7] if remote_full else ""
                commit_obj = (data or {}).get("commit", {}) or {}
                remote_msg = str(commit_obj.get("message", "")).splitlines()[0][:90] if commit_obj.get("message") else ""
                remote_date = str((commit_obj.get("committer") or {}).get("date", ""))[:10]

                up_to_date = bool(remote_full and remote_full.lower().startswith(local_sha.lower()))
                if up_to_date:
                    status_msg = f"Você já está na versão mais recente (commit {local_sha})."
                elif remote_sha:
                    status_msg = f"Nova atualização disponível no GitHub! Local: {local_sha} → Remoto: {remote_sha}."
                else:
                    status_msg = "Consulta concluída sem hash de commit remoto."

                return {
                    "ok": True,
                    "up_to_date": up_to_date,
                    "local_version": APP_VERSION,
                    "local_sha": local_sha,
                    "remote_version": APP_VERSION,
                    "remote_sha": remote_sha or "N/A",
                    "remote_message": remote_msg,
                    "remote_date": remote_date,
                    "url": repo_web_url,
                    "message": status_msg,
                }

            # 2. Modo Instalação Empacotada (sem .git): comparar versão semântica contra Releases/Tags
            remote_tag = ""
            remote_date = ""
            remote_msg = ""
            try:
                rel = self._fetch_github_json(
                    f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                    timeout=timeout,
                )
                if isinstance(rel, dict) and rel.get("tag_name"):
                    remote_tag = str(rel.get("tag_name", "")).strip()
                    remote_date = str(rel.get("published_at", ""))[:10]
                    rel_name = str(rel.get("name", "") or "").strip()
                    remote_msg = rel_name or f"Release {remote_tag}"
            except urllib.error.HTTPError as http_err:
                if http_err.code != 404:
                    raise

            if not remote_tag:
                try:
                    tags = self._fetch_github_json(
                        f"https://api.github.com/repos/{GITHUB_REPO}/tags?per_page=5",
                        timeout=timeout,
                    )
                    if isinstance(tags, list) and tags:
                        best_ver: Optional[Tuple[int, ...]] = None
                        for t in tags:
                            t_name = str((t or {}).get("name", "")).strip()
                            t_ver = self._parse_semver_tuple(t_name)
                            if t_ver is not None and (best_ver is None or t_ver > best_ver):
                                best_ver = t_ver
                                remote_tag = t_name
                        if not remote_tag and tags[0].get("name"):
                            remote_tag = str(tags[0]["name"]).strip()
                        remote_msg = f"Tag {remote_tag}" if remote_tag else ""
                except urllib.error.HTTPError as http_err:
                    if http_err.code != 404:
                        raise

            local_ver = self._parse_semver_tuple(APP_VERSION) or (0,)
            remote_ver = self._parse_semver_tuple(remote_tag)

            if remote_tag and remote_ver is not None:
                if remote_ver <= local_ver:
                    up_to_date = True
                    status_msg = f"Você já está na versão mais recente (v{APP_VERSION})."
                else:
                    up_to_date = False
                    status_msg = f"Nova versão disponível no GitHub: v{APP_VERSION} → {remote_tag}!"
                return {
                    "ok": True,
                    "up_to_date": up_to_date,
                    "local_version": APP_VERSION,
                    "local_sha": "N/A",
                    "remote_version": remote_tag,
                    "remote_sha": remote_tag,
                    "remote_message": remote_msg,
                    "remote_date": remote_date,
                    "url": repo_web_url,
                    "message": status_msg,
                }

            # Fallback informativo caso o repositório ainda não tenha releases/tags publicados
            data = self._fetch_github_json(
                f"https://api.github.com/repos/{GITHUB_REPO}/commits/main",
                timeout=timeout,
            )
            remote_full = str((data or {}).get("sha", "")).strip()
            remote_sha = remote_full[:7] if remote_full else "N/A"
            commit_obj = (data or {}).get("commit", {}) or {}
            remote_msg = str(commit_obj.get("message", "")).splitlines()[0][:90] if commit_obj.get("message") else ""
            remote_date = str((commit_obj.get("committer") or {}).get("date", ""))[:10]
            return {
                "ok": True,
                "up_to_date": True,
                "local_version": APP_VERSION,
                "local_sha": "N/A",
                "remote_version": f"v{APP_VERSION}",
                "remote_sha": remote_sha,
                "remote_message": remote_msg,
                "remote_date": remote_date,
                "url": repo_web_url,
                "message": f"Versão instalada: v{APP_VERSION} (último commit em main: {remote_sha} em {remote_date or 'N/A'}).",
            }
        except Exception as e:
            return {
                "ok": False,
                "up_to_date": None,
                "local_version": APP_VERSION,
                "local_sha": local_sha or "N/A",
                "remote_version": "N/A",
                "remote_sha": "N/A",
                "remote_message": "",
                "remote_date": "",
                "url": repo_web_url,
                "message": f"Não foi possível consultar o GitHub ({e}).",
            }

