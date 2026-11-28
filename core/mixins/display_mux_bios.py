"""Mixin de GPU MUX Switch, Taxa de Atualização (Hz), LCD Overdrive e Atributos WMI da BIOS."""

import glob
import json
import os
import re
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple
from core.models import BiosAttribute, DisplayRefreshInfo, GpuMuxInfo
from core.permissions import PermissionsManager


class DisplayMuxBiosMixin:
    """Alternância de GPU MUX, gerenciamento dinâmico de Hz/Display, Overdrive e BIOS WMI."""

    LENOVO_CUSTOM_POWER_ATTRS: Tuple[Tuple[str, str, str, int, int], ...] = (
        ("gpu_nv_ctgp", "Potência Base da GPU (cTGP)", "W", 35, 95),
        ("gpu_nv_ppab", "Dynamic Boost GPU (PPAB)", "W", 0, 25),
        ("gpu_nv_cpu_boost", "Dynamic Boost CPU → GPU", "W", 0, 25),
        ("ppt_cpu_cl", "Limite Cruzado CPU+GPU", "W", 15, 55),
        ("ppt_pl1_spl", "CPU Sustentado WMI (PL1)", "W", 15, 65),
        ("ppt_pl2_sppt", "CPU Boost Curto WMI (PL2)", "W", 20, 85),
    )

    PROMOTED_BIOS_ATTR_IDS = frozenset({
        "lcd_overdrive",
        "gpu_nv_ctgp",
        "gpu_nv_ppab",
        "gpu_nv_cpu_boost",
        "ppt_cpu_cl",
        "ppt_pl1_spl",
        "ppt_pl2_sppt",
        "cpu_temp",
        "gpu_temp",
        "gpu_nv_ac_offset",
        "usb_charging",
        "usb_power_in_sleep",
        "gpu_mode",
    })

    # =========================================================================
    # RECURSO 1: GPU MUX Switch (Modo Híbrido vs dGPU Direta vs iGPU Pura)
    # =========================================================================
    def _scan_gpu_mux(self) -> None:
        """Descobre ferramentas e nós do kernel para alternância de modos de GPU (MUX Switch)."""
        # 1. Nós do kernel Lenovo WMI / ACPI
        for cand in (
            "/sys/bus/platform/drivers/ideapad_acpi/VPC2004:00/gpu_mode",
            "/sys/devices/platform/ideapad_acpi/gpu_mode",
        ) + tuple(glob.glob("/sys/bus/platform/drivers/ideapad_acpi/VPC*/gpu_mode")) + tuple(glob.glob("/sys/class/firmware-attributes/*/attributes/gpu_mode/current_value")):
            if os.path.exists(cand):
                self.paths.gpu_mode = cand
                break

        # 2. Somente ativa GPU MUX se houver ferramenta dedicada ou nó sysfs real (lenovo-wmi / ideapad_acpi)
        has_tool = any(shutil.which(cmd) for cmd in ("supergfxctl", "envycontrol", "prime-select"))
        self.features.gpu_mux = bool(has_tool or self.paths.gpu_mode)

    def get_gpu_mux_info(self) -> GpuMuxInfo:
        """Retorna o estado atual do GPU MUX Switch, modos suportados e backend ativo."""
        now = time.time()
        if self._cached_gpu_mux_info and (now - self._last_gpu_mux_scan < 4.0):
            return self._cached_gpu_mux_info

        modes = ["hybrid", "dedicated", "integrated"]
        cur_mode = self.settings.get("gpu_mux_mode", "hybrid")
        backend_name = "none"
        req_reboot = False
        msg = ""

        # 1. supergfxctl (ASUS / Lenovo ROG / Legion com daemon supergfxctl)
        if shutil.which("supergfxctl"):
            backend_name = "supergfxctl"
            try:
                res_g = subprocess.run(["supergfxctl", "-g"], capture_output=True, text=True, timeout=3)
                if res_g.returncode == 0:
                    raw = res_g.stdout.strip().lower()
                    if "dedicated" in raw or "discrete" in raw:
                        cur_mode = "dedicated"
                    elif "integrated" in raw:
                        cur_mode = "integrated"
                    else:
                        cur_mode = "hybrid"

                res_s = subprocess.run(["supergfxctl", "-s"], capture_output=True, text=True, timeout=3)
                if "reboot" in (res_s.stdout + res_s.stderr).lower() or "action" in (res_s.stdout + res_s.stderr).lower():
                    req_reboot = True
                    msg = "Reinicialização necessária para efetivar a troca de GPU no supergfxctl."
            except Exception:
                pass

        # 2. envycontrol
        elif shutil.which("envycontrol"):
            backend_name = "envycontrol"
            try:
                res = subprocess.run(["envycontrol", "--query"], capture_output=True, text=True, timeout=3)
                if res.returncode == 0:
                    raw = res.stdout.strip().lower()
                    if "nvidia" in raw:
                        cur_mode = "dedicated"
                    elif "integrated" in raw:
                        cur_mode = "integrated"
                    else:
                        cur_mode = "hybrid"
            except Exception:
                pass

        # 3. prime-select (Ubuntu / Debian / Linux Mint)
        elif shutil.which("prime-select"):
            backend_name = "prime-select"
            try:
                res = subprocess.run(["prime-select", "query"], capture_output=True, text=True, timeout=3)
                if res.returncode == 0:
                    raw = res.stdout.strip().lower()
                    if "nvidia" in raw:
                        cur_mode = "dedicated"
                    elif "intel" in raw:
                        cur_mode = "integrated"
                    else:
                        cur_mode = "hybrid"
            except Exception:
                pass

        # 4. Nó Lenovo ACPI / WMI (gpu_mode)
        elif self.paths.gpu_mode and os.path.exists(self.paths.gpu_mode):
            backend_name = "lenovo-wmi"
            val = self._read_file_text(self.paths.gpu_mode) or "0"
            val = val.strip().lower()
            if val in ("1", "discrete", "dedicated"):
                cur_mode = "dedicated"
            elif val in ("2", "igpu", "integrated"):
                cur_mode = "integrated"
            else:
                cur_mode = "hybrid"
        else:
            backend_name = "none"
            modes = []

        is_avail = backend_name != "none" and len(modes) > 0
        self.features.gpu_mux = is_avail

        info = GpuMuxInfo(
            available=is_avail,
            current_mode=cur_mode,
            available_modes=modes,
            backend_name=backend_name,
            requires_reboot=req_reboot,
            message=msg
        )
        self._cached_gpu_mux_info = info
        self._last_gpu_mux_scan = now
        return info

    def set_gpu_mux_mode(self, mode: str) -> Tuple[bool, str, bool]:
        """
        Altera o modo de trabalho da GPU (hybrid, dedicated, integrated).
        Retorna (sucesso, mensagem, requer_reboot).
        """
        mode = mode.lower().strip()
        if mode not in ("hybrid", "dedicated", "integrated"):
            return False, f"Modo '{mode}' inválido. Escolha entre: hybrid, dedicated ou integrated.", False

        info = self.get_gpu_mux_info()
        backend = info.backend_name

        if mode not in info.available_modes:
            return False, f"O modo '{mode}' não é suportado pelo backend ativo ({backend}). Instale 'envycontrol' ou 'supergfxctl' para comutação de hardware.", False

        if backend == "supergfxctl":
            mapped = {"hybrid": "Hybrid", "dedicated": "Dedicated", "integrated": "Integrated"}[mode]
            try:
                res = subprocess.run(["supergfxctl", "-m", mapped], capture_output=True, text=True, timeout=8)
                if res.returncode == 0:
                    self.settings.set("gpu_mux_mode", mode)
                    self._cached_gpu_mux_info = None
                    req = "reboot" in res.stdout.lower() or "logout" in res.stdout.lower()
                    msg = f"Modo {mapped} configurado via supergfxctl."
                    if req:
                        msg += " Reinicialização de sessão necessária."
                    return True, msg, req
                return False, f"supergfxctl retornou erro: {res.stderr or res.stdout}", False
            except Exception as e:
                return False, f"Falha ao executar supergfxctl: {e}", False

        elif backend == "envycontrol":
            mapped = {"hybrid": "hybrid", "dedicated": "nvidia", "integrated": "integrated"}[mode]
            cmd = ["envycontrol", "-s", mapped, "--no-confirm"]
            if os.geteuid() != 0 and shutil.which("pkexec"):
                cmd = ["pkexec"] + cmd
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                if res.returncode == 0:
                    self.settings.set("gpu_mux_mode", mode)
                    self._cached_gpu_mux_info = None
                    return True, f"Modo {mode.upper()} gravado via EnvyControl. Reinicie o sistema para aplicar.", True
                return False, f"EnvyControl erro: {res.stderr or res.stdout}", False
            except Exception as e:
                return False, f"Falha ao executar envycontrol: {e}", False

        elif backend == "prime-select":
            mapped = {"hybrid": "on-demand", "dedicated": "nvidia", "integrated": "intel"}[mode]
            cmd = ["prime-select", mapped]
            if os.geteuid() != 0 and shutil.which("pkexec"):
                cmd = ["pkexec"] + cmd
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
                if res.returncode == 0:
                    self.settings.set("gpu_mux_mode", mode)
                    self._cached_gpu_mux_info = None
                    return True, f"Modo {mapped} gravado via prime-select. Reinicie a sessão para aplicar.", True
                return False, f"prime-select erro: {res.stderr or res.stdout}", False
            except Exception as e:
                return False, f"Falha ao executar prime-select: {e}", False

        elif backend == "lenovo-wmi" and self.paths.gpu_mode:
            mapped_val = {"hybrid": "0", "dedicated": "1", "integrated": "2"}[mode]
            ok, msg = PermissionsManager.write_sysfs_value(self.paths.gpu_mode, mapped_val, allow_elevation=True)
            if ok:
                self.settings.set("gpu_mux_mode", mode)
                self._cached_gpu_mux_info = None
                return True, f"Modo GPU {mode.upper()} gravado na BIOS Lenovo. Reinicie o notebook.", True
            return False, f"Erro ao gravar no nó Lenovo gpu_mode: {msg}", False

        return False, "Comutação de GPU MUX não é suportada pelo hardware/sistema atual.", False

    # =========================================================================
    # RECURSO 2: Taxa de Atualização Automática (144Hz/165Hz ↔ 60Hz e Fn+R)
    # =========================================================================
    def _scan_display_refresh(self) -> None:
        """Detecta se o ambiente e painel suportam troca real entre múltiplas taxas de atualização."""
        info = self.get_display_refresh_info()
        self.features.refresh_rate = bool(
            info.available
            and info.backend_name in ("kscreen-doctor", "wlr-randr", "xrandr")
            and len(info.available_rates) > 1
        )
        # Não poluir o cache durante a inicialização para permitir consultas atualizadas sob demanda
        self._cached_refresh_info = None
        self._last_refresh_scan = 0.0

    def get_display_refresh_info(self) -> DisplayRefreshInfo:
        """Detecta display ativo, resolução atual e taxas de atualização suportadas."""
        now = time.time()
        if self._cached_refresh_info and (now - self._last_refresh_scan < 3.0):
            return self._cached_refresh_info

        # 1. KDE Plasma (Wayland / X11) via kscreen-doctor
        if shutil.which("kscreen-doctor"):
            try:
                env = os.environ.copy()
                if "QT_QPA_PLATFORM" not in env and not env.get("WAYLAND_DISPLAY") and not env.get("DISPLAY"):
                    env["QT_QPA_PLATFORM"] = "offscreen"
                res = subprocess.run(["kscreen-doctor", "-j"], capture_output=True, text=True, env=env, timeout=3)
                if res.returncode == 0:
                    data = json.loads(res.stdout)
                    outputs = data.get("outputs", [])
                    candidates = [o for o in outputs if o.get("connected") and o.get("enabled")]
                    internal = [o for o in candidates if any(p in o.get("name", "").upper() for p in ("EDP", "LVDS", "DSI"))]
                    chosen = internal[0] if internal else (candidates[0] if candidates else None)

                    if chosen:
                        d_name = chosen.get("name", "Display")
                        cur_mode_id = chosen.get("currentModeId")
                        modes = chosen.get("modes", [])
                        cur_mode = next((m for m in modes if m.get("id") == cur_mode_id), None)
                        if cur_mode:
                            w = cur_mode.get("size", {}).get("width", 1920)
                            h = cur_mode.get("size", {}).get("height", 1080)
                            cur_res = f"{w}x{h}"
                            rates_set = set()
                            for m in modes:
                                if m.get("size", {}).get("width") == w and m.get("size", {}).get("height") == h:
                                    r_raw = m.get("refreshRate", 60)
                                    hz = round(r_raw / 1000.0) if r_raw > 1000 else round(r_raw)
                                    if hz > 0:
                                        rates_set.add(hz)

                            raw_cur_hz = cur_mode.get("refreshRate", 60)
                            cur_hz = round(raw_cur_hz / 1000.0) if raw_cur_hz > 1000 else round(raw_cur_hz)
                            rates = sorted(list(rates_set)) if rates_set else [60]

                            vrr_raw = chosen.get("vrrPolicy")
                            vrr_supported = vrr_raw is not None
                            vrr_map = {0: "never", 1: "always", 2: "automatic"}
                            vrr_pol = vrr_map.get(vrr_raw, str(vrr_raw).lower() if isinstance(vrr_raw, str) else "never")
                            if vrr_pol not in ("never", "always", "automatic"):
                                vrr_pol = "never"

                            info = DisplayRefreshInfo(
                                available=True,
                                current_hz=cur_hz,
                                available_rates=rates,
                                display_name=d_name,
                                resolution=cur_res,
                                backend_name="kscreen-doctor",
                                auto_switch_ac=self.get_auto_refresh_rate_transition(),
                                vrr_supported=vrr_supported,
                                vrr_policy=vrr_pol,
                            )
                            self._cached_refresh_info = info
                            self._last_refresh_scan = now
                            return info
            except Exception:
                pass

        # 2. wlroots Wayland via wlr-randr (com agrupamento por saída para multi-monitor)
        if shutil.which("wlr-randr"):
            try:
                res = subprocess.run(["wlr-randr"], capture_output=True, text=True, timeout=3)
                if res.returncode == 0:
                    lines = res.stdout.splitlines()
                    displays = []
                    curr_disp = None
                    for line in lines:
                        if line and not line.startswith(" ") and not line.startswith("\t"):
                            parts = line.split()
                            if parts:
                                d_name = parts[0]
                                curr_disp = {
                                    "name": d_name,
                                    "is_internal": any(p in d_name.upper() for p in ("EDP", "LVDS", "DSI")),
                                    "cur_res": "1920x1080",
                                    "cur_hz": 60,
                                    "rates": set()
                                }
                                displays.append(curr_disp)
                                continue
                        if curr_disp:
                            m = re.search(r"(\d+x\d+)\s+px,\s+([\d\.]+)\s+Hz(?:\s+\((current)\))?", line)
                            if m:
                                res_str, hz_str, is_cur = m.group(1), m.group(2), m.group(3)
                                hz_val = round(float(hz_str))
                                curr_disp["rates"].add(hz_val)
                                if is_cur:
                                    curr_disp["cur_res"] = res_str
                                    curr_disp["cur_hz"] = hz_val

                    internal = [d for d in displays if d["is_internal"]]
                    chosen = internal[0] if internal else (displays[0] if displays else None)
                    if chosen:
                        rates = sorted(list(chosen["rates"])) if chosen["rates"] else [chosen["cur_hz"]]
                        info = DisplayRefreshInfo(
                            available=True,
                            current_hz=chosen["cur_hz"],
                            available_rates=rates,
                            display_name=chosen["name"],
                            resolution=chosen["cur_res"],
                            backend_name="wlr-randr",
                            auto_switch_ac=self.get_auto_refresh_rate_transition()
                        )
                        self._cached_refresh_info = info
                        self._last_refresh_scan = now
                        return info
            except Exception:
                pass

        # 3. X11 via xrandr (com agrupamento por saída para suporte perfeito a multi-monitor)
        if shutil.which("xrandr"):
            try:
                res = subprocess.run(["xrandr", "--current"], capture_output=True, text=True, timeout=3)
                if res.returncode == 0:
                    lines = res.stdout.splitlines()
                    displays = []
                    curr_disp = None
                    for line in lines:
                        if " connected" in line:
                            parts = line.split()
                            d_name = parts[0]
                            is_primary = "primary" in parts
                            curr_disp = {
                                "name": d_name,
                                "is_internal": any(p in d_name.upper() for p in ("EDP", "LVDS", "DSI")),
                                "is_primary": is_primary,
                                "cur_res": "1920x1080",
                                "cur_hz": 60,
                                "rates": set()
                            }
                            displays.append(curr_disp)
                            continue
                        elif line and not line.startswith("   ") and not line.startswith("\t"):
                            curr_disp = None

                        if curr_disp:
                            m_res = re.match(r"^\s*(\d+x\d+)\s+(.+)$", line)
                            if m_res:
                                r_str, rest = m_res.group(1), m_res.group(2)
                                rate_matches = re.findall(r"([\d\.]+)([\*\+]*)", rest)
                                for r_val, marks in rate_matches:
                                    try:
                                        hz = round(float(r_val))
                                        if "*" in marks:
                                            curr_disp["cur_res"] = r_str
                                            curr_disp["cur_hz"] = hz
                                        if "*" in marks or curr_disp["cur_res"] == r_str:
                                            curr_disp["rates"].add(hz)
                                    except ValueError:
                                        pass

                    internal = [d for d in displays if d["is_internal"]]
                    primary = [d for d in displays if d["is_primary"]]
                    chosen = internal[0] if internal else (primary[0] if primary else (displays[0] if displays else None))

                    if chosen:
                        rates = sorted(list(chosen["rates"])) if chosen["rates"] else [chosen["cur_hz"]]
                        info = DisplayRefreshInfo(
                            available=True,
                            current_hz=chosen["cur_hz"],
                            available_rates=rates,
                            display_name=chosen["name"],
                            resolution=chosen["cur_res"],
                            backend_name="xrandr",
                            auto_switch_ac=self.get_auto_refresh_rate_transition()
                        )
                        self._cached_refresh_info = info
                        self._last_refresh_scan = now
                        return info
            except Exception:
                pass

        # 4. Fallback DRM sysfs & EDID binário do painel
        cur_res = "1920x1080"
        drm_rates = set()
        for edid_f in sorted(glob.glob("/sys/class/drm/card*-eDP-*/edid") + glob.glob("/sys/class/drm/card*/edid")):
            try:
                with open(edid_f, "rb") as ef:
                    edid_bytes = ef.read()
                if len(edid_bytes) >= 128:
                    for desc_offset in (54, 72, 90, 108):
                        d = edid_bytes[desc_offset:desc_offset + 18]
                        if len(d) == 18:
                            pix_clk = d[0] | (d[1] << 8)
                            if pix_clk > 0:
                                pix_clk_khz = pix_clk * 10
                                h_act = d[2] | ((d[4] & 0xF0) << 4)
                                h_blk = d[3] | ((d[4] & 0x0F) << 8)
                                v_act = d[5] | ((d[7] & 0xF0) << 4)
                                v_blk = d[6] | ((d[7] & 0x0F) << 8)
                                h_tot = h_act + h_blk
                                v_tot = v_act + v_blk
                                if h_tot > 0 and v_tot > 0:
                                    hz_calc = round((pix_clk_khz * 1000.0) / (h_tot * v_tot))
                                    if 24 <= hz_calc <= 360:
                                        drm_rates.add(hz_calc)
                                        if not cur_res or cur_res == "1920x1080":
                                            cur_res = f"{h_act}x{v_act}"
            except Exception:
                pass
            if drm_rates:
                break

        for modes_f in sorted(glob.glob("/sys/class/drm/card*-eDP-*/modes") + glob.glob("/sys/class/drm/card*/modes")):
            m_text = self._read_file_text(modes_f) or ""
            if m_text.strip():
                cur_res = m_text.strip().splitlines()[0]
                break

        last_hz = int(self.settings.get("last_refresh_rate", 60))
        if drm_rates:
            rates = sorted(list(drm_rates))
            cur_hz = last_hz if last_hz in rates else rates[0]
        else:
            rates = [60]
            cur_hz = 60

        info = DisplayRefreshInfo(
            available=False,
            current_hz=cur_hz,
            available_rates=rates,
            display_name="eDP-1",
            resolution=cur_res,
            backend_name="drm-fallback",
            auto_switch_ac=self.get_auto_refresh_rate_transition()
        )
        self._cached_refresh_info = info
        self._last_refresh_scan = now
        return info

    def set_refresh_rate(self, hz: int) -> Tuple[bool, str]:
        """Aplica a taxa de atualização selecionada (ex: 60 ou 144) no display ativo."""
        info = self.get_display_refresh_info()
        target_hz = int(hz)
        backend = info.backend_name

        if backend == "kscreen-doctor":
            env = os.environ.copy()
            if "QT_QPA_PLATFORM" not in env and not env.get("WAYLAND_DISPLAY") and not env.get("DISPLAY"):
                env["QT_QPA_PLATFORM"] = "offscreen"

            cmd = ["kscreen-doctor", f"output.{info.display_name}.mode.{info.resolution}@{target_hz}"]
            res = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=5)
            if res.returncode == 0:
                self.settings.set("last_refresh_rate", target_hz)
                self._cached_refresh_info = None
                return True, f"Taxa de atualização ajustada para {target_hz} Hz."

            try:
                res_j = subprocess.run(["kscreen-doctor", "-j"], capture_output=True, text=True, env=env, timeout=5)
                if res_j.returncode == 0:
                    data = json.loads(res_j.stdout)
                    for out in data.get("outputs", []):
                        if out.get("name") == info.display_name:
                            for m in out.get("modes", []):
                                m_hz = round(m.get("refreshRate", 0) / 1000.0) if m.get("refreshRate", 0) > 1000 else round(m.get("refreshRate", 0))
                                if m_hz == target_hz and f"{m.get('size', {}).get('width')}x{m.get('size', {}).get('height')}" == info.resolution:
                                    m_id = m.get("id")
                                    res_set = subprocess.run(["kscreen-doctor", f"output.{info.display_name}.mode.{m_id}"], capture_output=True, text=True, env=env, timeout=5)
                                    if res_set.returncode == 0:
                                        self.settings.set("last_refresh_rate", target_hz)
                                        self._cached_refresh_info = None
                                        return True, f"Taxa de atualização ajustada para {target_hz} Hz."
            except Exception:
                pass
            return False, f"kscreen-doctor não conseguiu aplicar {target_hz} Hz no painel {info.display_name}."

        elif backend == "wlr-randr":
            cmd = ["wlr-randr", "--output", info.display_name, "--mode", f"{info.resolution}@{target_hz}Hz"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                self.settings.set("last_refresh_rate", target_hz)
                self._cached_refresh_info = None
                return True, f"Taxa de atualização ajustada para {target_hz} Hz."
            return False, f"wlr-randr não conseguiu aplicar {target_hz} Hz: {res.stderr or res.stdout}"

        elif backend == "xrandr":
            cmd = ["xrandr", "--output", info.display_name, "--mode", info.resolution, "--rate", str(target_hz)]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                self.settings.set("last_refresh_rate", target_hz)
                self._cached_refresh_info = None
                return True, f"Taxa de atualização ajustada para {target_hz} Hz."
            return False, f"xrandr não conseguiu aplicar {target_hz} Hz: {res.stderr or res.stdout}"

        return False, "Nenhum backend gráfico ativo (kscreen-doctor / wlr-randr / xrandr) suporta troca de taxa de atualização."

    def cycle_refresh_rate(self) -> Tuple[bool, int, str]:
        """Cicla para a próxima taxa suportada (ex: 60Hz ↔ 144Hz) ao estilo Fn+R Lenovo."""
        info = self.get_display_refresh_info()
        rates = sorted(info.available_rates) if info.available_rates else [60, 144]
        cur = info.current_hz

        if cur == rates[-1]:
            target = rates[0]
        else:
            higher = [r for r in rates if r > cur]
            target = higher[0] if higher else rates[0]

        ok, msg = self.set_refresh_rate(target)
        return ok, target, msg

    def get_auto_refresh_rate_transition(self) -> bool:
        return bool(self.settings.get("auto_refresh_rate_transition", True))

    def set_auto_refresh_rate_transition(self, enable: bool) -> None:
        self.settings.set("auto_refresh_rate_transition", bool(enable))

    def set_vrr_policy(self, policy: str) -> Tuple[bool, str]:
        """Define a política de VRR / Adaptive Sync no painel via kscreen-doctor."""
        pol = str(policy or "automatic").strip().lower()
        if pol not in ("never", "always", "automatic"):
            return False, f"Política VRR inválida: {policy}"
        if not shutil.which("kscreen-doctor"):
            return False, "kscreen-doctor não disponível neste ambiente."
        info = self.get_display_refresh_info()
        if not info.display_name:
            return False, "Painel de exibição ativo não identificado."
        env = os.environ.copy()
        if "QT_QPA_PLATFORM" not in env and not env.get("WAYLAND_DISPLAY") and not env.get("DISPLAY"):
            env["QT_QPA_PLATFORM"] = "offscreen"
        res = subprocess.run(
            ["kscreen-doctor", f"output.{info.display_name}.vrrpolicy.{pol}"],
            capture_output=True, text=True, env=env, timeout=4
        )
        if res.returncode == 0:
            self._cached_refresh_info = None
            return True, f"VRR / Adaptive Sync ajustado para '{pol}' em {info.display_name}."
        return False, f"kscreen-doctor não aplicou VRR ({pol}): {res.stderr or res.stdout}"

    # =========================================================================
    # RECURSO 2.5: Modo Mesa / Monitor Externo Automático (HDMI / DisplayPort)
    # =========================================================================
    def get_external_monitors(self) -> List[str]:
        """Detecta monitores externos conectados via /sys/class/drm/card*-*/status."""
        monitors: List[str] = []
        internal_prefixes = ("EDP", "LVDS", "DSI", "VIRTUAL")
        for status_p in sorted(glob.glob("/sys/class/drm/card*-*/status")):
            state = (self._read_file_text(status_p) or "").strip().lower()
            if state != "connected":
                continue
            conn_dir = os.path.basename(os.path.dirname(status_p))
            conn_name = re.sub(r"^card\d+-", "", conn_dir)
            if any(conn_name.upper().startswith(p) for p in internal_prefixes):
                continue
            monitors.append(conn_name)
        return monitors

    def get_dock_mode_config(self) -> Dict[str, Any]:
        return {
            "enabled": bool(self.settings.get("dock_mode_enabled", False)),
            "target_profile": self.normalize_profile(str(self.settings.get("dock_target_profile", "performance") or "performance")),
            "keep_max_hz": bool(self.settings.get("dock_keep_max_hz", True)),
            "inhibit_lid_sleep": bool(self.settings.get("dock_inhibit_lid_sleep", False)),
        }

    def set_dock_mode_config(
        self,
        enabled: bool,
        target_profile: str = "performance",
        keep_max_hz: bool = True,
        inhibit_lid_sleep: bool = False,
    ) -> None:
        self.settings.set("dock_mode_enabled", bool(enabled))
        self.settings.set("dock_target_profile", self.normalize_profile(target_profile))
        self.settings.set("dock_keep_max_hz", bool(keep_max_hz))
        self.settings.set("dock_inhibit_lid_sleep", bool(inhibit_lid_sleep))
        if not enabled:
            self._stop_dock_lid_inhibit()
            self._dock_active = False

    def _start_dock_lid_inhibit(self) -> None:
        proc = getattr(self, "_dock_lid_proc", None)
        if proc is not None and proc.poll() is None:
            return
        plat = (os.environ.get("QT_QPA_PLATFORM") or "").lower()
        if plat in ("offscreen", "minimal"):
            return
        if shutil.which("systemd-inhibit"):
            try:
                self._dock_lid_proc = subprocess.Popen(
                    [
                        "systemd-inhibit",
                        "--what=handle-lid-switch",
                        "--who=Ducksvantage",
                        "--why=Modo Mesa (Monitor Externo)",
                        "sleep", "infinity",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except Exception:
                self._dock_lid_proc = None

    def _stop_dock_lid_inhibit(self) -> None:
        proc = getattr(self, "_dock_lid_proc", None)
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=1.5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            self._dock_lid_proc = None

    def check_external_monitor_dock_mode(self) -> Optional[Dict[str, Any]]:
        """Monitora conexão/desconexão de HDMI/DP externo e aplica Modo Mesa automaticamente."""
        cfg = self.get_dock_mode_config()
        if not cfg["enabled"]:
            return None

        monitors = self.get_external_monitors()
        connected = len(monitors) > 0
        prev_state = getattr(self, "_dock_active", None)

        if prev_state is None and not connected:
            self._dock_active = False
            return None

        if connected and prev_state is not True:
            self._dock_active = True
            if self.get_active_game():
                if cfg["inhibit_lid_sleep"]:
                    self._start_dock_lid_inhibit()
                return None

            self._dock_pre_profile = self.get_platform_profile()
            notes: List[str] = []
            if self.features.platform_profile:
                ok_p, _ = self.set_platform_profile(cfg["target_profile"], allow_elevation=False)
                if ok_p:
                    notes.append(cfg["target_profile"].upper())
            if cfg["keep_max_hz"] and self.features.refresh_rate:
                info = self.get_display_refresh_info()
                if info.available and len(info.available_rates) > 1:
                    max_hz = max(info.available_rates)
                    self._dock_pre_hz = info.current_hz
                    if info.current_hz < max_hz and self.set_refresh_rate(max_hz)[0]:
                        notes.append(f"{max_hz} Hz")
            if cfg["inhibit_lid_sleep"]:
                self._start_dock_lid_inhibit()
                notes.append("Tampa Liberada")

            return {
                "type": "dock_mode_entered",
                "monitors": monitors,
                "summary": f"{', '.join(monitors)} • {' • '.join(notes) if notes else 'Modo Mesa Ativo'}",
            }

        if not connected and prev_state is True:
            self._dock_active = False
            self._stop_dock_lid_inhibit()
            if self.get_active_game():
                return None
            prev_p = getattr(self, "_dock_pre_profile", "balanced") or "balanced"
            if self.features.platform_profile:
                self.set_platform_profile(prev_p, allow_elevation=False)
            prev_hz = getattr(self, "_dock_pre_hz", None)
            self._dock_pre_hz = None
            if prev_hz and self.features.refresh_rate:
                self.set_refresh_rate(int(prev_hz))
            return {
                "type": "dock_mode_exited",
                "monitors": [],
                "summary": f"Perfil restaurado: {prev_p.upper()}",
            }

        return None

    # =========================================================================
    # RECURSO 3: LCD Overdrive & Ajustes de BIOS / Lenovo WMI (Zero Hardcoding)
    # =========================================================================
    def _scan_bios_attributes(self) -> None:
        """Descobre nós de firmware attributes da BIOS Lenovo e LCD Overdrive."""
        for cand in (
            glob.glob("/sys/class/firmware-attributes/lenovo-wmi-other-*/attributes/lcd_overdrive/current_value")
            + glob.glob("/sys/class/firmware-attributes/thinklmi/attributes/LcdOverdrive/current_value")
            + glob.glob("/sys/class/firmware-attributes/*/attributes/*lcd_overdrive*/current_value")
            + glob.glob("/sys/bus/platform/drivers/ideapad_acpi/*/lcd_overdrive")
            + glob.glob("/sys/devices/platform/ideapad_acpi/lcd_overdrive")
            + glob.glob("/sys/bus/platform/drivers/legion_laptop/*/overdrive")
            + glob.glob("/sys/devices/platform/PNP0C09:00/overdrive")
        ):
            if os.path.exists(cand):
                self.paths.lcd_overdrive = cand
                self.features.lcd_overdrive = True
                break

        wmi_attrs = glob.glob("/sys/class/firmware-attributes/*/attributes/*/current_value")
        non_promoted = [
            p for p in wmi_attrs
            if os.path.basename(os.path.dirname(p)).lower() not in self.PROMOTED_BIOS_ATTR_IDS
        ]
        self.features.bios_attributes = bool(non_promoted)

    def is_lcd_overdrive_supported(self) -> bool:
        """Indica se a tela suporta aceleração de tempo de resposta (Overdrive)."""
        return bool(self.paths.lcd_overdrive or self.features.lcd_overdrive)

    def get_lcd_overdrive(self) -> bool:
        """Lê o estado atual do LCD Overdrive."""
        if self.paths.lcd_overdrive and os.path.exists(self.paths.lcd_overdrive):
            txt = (self._read_file_text(self.paths.lcd_overdrive) or "").strip().lower()
            return txt in ("1", "enabled", "on", "true")
        return False

    def set_lcd_overdrive(self, enabled: bool, allow_elevation: bool = True) -> Tuple[bool, str]:
        """Ativa ou desativa a aceleração de tempo de resposta dos pixels do LCD."""
        if self.paths.lcd_overdrive and os.path.exists(self.paths.lcd_overdrive):
            poss_file = os.path.join(os.path.dirname(self.paths.lcd_overdrive), "possible_values")
            poss = self._read_file_text(poss_file) or ""
            if "Enabled" in poss or "Disabled" in poss:
                val = "Enabled" if enabled else "Disabled"
            else:
                val = "1" if enabled else "0"
            ok, msg = PermissionsManager.write_sysfs_value(
                self.paths.lcd_overdrive, val, allow_elevation=allow_elevation
            )
            if ok:
                return True, f"LCD Overdrive {'ativado' if enabled else 'desativado'} com sucesso."
            return False, f"Falha ao aplicar LCD Overdrive: {msg}"
        return False, "LCD Overdrive não suportado pelo painel ou BIOS deste notebook."

    def get_bios_attributes(self) -> List[BiosAttribute]:
        """
        Inspeciona dinamicamente TODOS os atributos expostos pela BIOS da máquina em
        /sys/class/firmware-attributes/*/attributes/ (Zero Hardcoding).
        """
        now = time.time()
        if self._cached_bios_attrs and (now - self._last_bios_attrs_scan < 4.0):
            return self._cached_bios_attrs

        attrs: List[BiosAttribute] = []
        wmi_base_dirs = sorted(glob.glob("/sys/class/firmware-attributes/*/attributes"))
        if not wmi_base_dirs:
            return attrs

        known_labels = {
            "flip_to_boot": ("Ligar ao Abrir a Tampa (Flip to Boot)", "Energia & Boot"),
            "usb_charging": ("Energia USB em Suspensão (Always-On USB)", "Energia & Boot"),
            "usb_power_in_sleep": ("Energia USB em Suspensão (Always-On USB)", "Energia & Boot"),
            "zero_rpm_fan_boot": ("Ventoinhas em Zero RPM no Boot", "Ajustes Térmicos & Potência"),
            "lcd_overdrive": ("LCD Overdrive (Tempo de Resposta)", "Tela & Vídeo"),
            "cpu_temp": ("Limite Térmico da CPU (Thermal Limit)", "Ajustes Térmicos & Potência"),
            "gpu_temp": ("Limite Térmico da GPU (Thermal Limit)", "Ajustes Térmicos & Potência"),
            "gpu_nv_ac_offset": ("GPU NVIDIA AC Baseline Offset", "Ajustes Térmicos & Potência"),
            "gpu_nv_ctgp": ("GPU Configurable TGP (cTGP)", "Ajustes Térmicos & Potência"),
            "gpu_nv_cpu_boost": ("NVIDIA Dynamic CPU Boost", "Ajustes Térmicos & Potência"),
            "gpu_nv_ppab": ("NVIDIA Power Performance Boost (PPAB)", "Ajustes Térmicos & Potência"),
            "ppt_cpu_cl": ("CPU Cross Loading Power Limit", "Ajustes Térmicos & Potência"),
            "ppt_pl1_spl": ("CPU Sustained Power Limit (PL1 SPL)", "Ajustes Térmicos & Potência"),
            "ppt_pl1_tau": ("CPU Sustained Limit Duration (PL1 Tau)", "Ajustes Térmicos & Potência"),
            "ppt_pl2_sppt": ("CPU Slow Package Limit (PL2 SPPT)", "Ajustes Térmicos & Potência"),
        }

        seen = set()
        for bdir in wmi_base_dirs:
            try:
                for attr_name in sorted(os.listdir(bdir)):
                    if attr_name in seen:
                        continue
                    a_path = os.path.join(bdir, attr_name)
                    if not os.path.isdir(a_path):
                        continue
                    cur_file = os.path.join(a_path, "current_value")
                    if not os.path.exists(cur_file):
                        continue
                    try:
                        if not (os.stat(cur_file).st_mode & 0o222):
                            continue
                    except OSError:
                        pass

                    seen.add(attr_name)
                    cur_val = (self._read_file_text(cur_file) or "").strip()
                    type_val = (self._read_file_text(os.path.join(a_path, "type")) or "enumeration").strip().lower()
                    disp_name = (self._read_file_text(os.path.join(a_path, "display_name")) or "").strip()
                    def_val = (self._read_file_text(os.path.join(a_path, "default_value")) or "").strip()

                    if attr_name in known_labels:
                        title, cat = known_labels[attr_name]
                    elif disp_name:
                        title = disp_name
                        cat = "Ajustes da BIOS"
                    else:
                        title = attr_name.replace("_", " ").title()
                        cat = "Ajustes da BIOS"

                    min_v, max_v, step_v = None, None, 1
                    poss_list: List[str] = []

                    if type_val == "integer":
                        min_v = self._read_file_int(os.path.join(a_path, "min_value"), 0)
                        max_v = self._read_file_int(os.path.join(a_path, "max_value"), 100)
                        step_v = self._read_file_int(os.path.join(a_path, "scalar_increment"), 1)
                        if step_v <= 0:
                            step_v = 1
                        # Corrige nós de firmware onde o driver expõe min=0 max=0 (ex: cTGP, PPAB)
                        if max_v <= min_v:
                            cur_int = int(cur_val) if (cur_val and cur_val.isdigit()) else 0
                            min_v = 0
                            max_v = max(100, cur_int + 25) if cur_int > 0 else 100
                    else:
                        poss_raw = self._read_file_text(os.path.join(a_path, "possible_values")) or ""
                        if ";" in poss_raw:
                            poss_list = [p.strip() for p in poss_raw.split(";") if p.strip()]
                        elif "," in poss_raw:
                            poss_list = [p.strip() for p in poss_raw.split(",") if p.strip()]
                        else:
                            poss_list = [p.strip() for p in poss_raw.splitlines() if p.strip()]

                        poss_lower = [p.lower() for p in poss_list]
                        if (
                            set(poss_lower) in ({"0", "1"}, {"disabled", "enabled"}, {"off", "on"}, {"no", "yes"})
                            or (not poss_list and cur_val.lower() in ("0", "1", "disabled", "enabled", "off", "on"))
                        ):
                            type_val = "boolean"

                    attrs.append(BiosAttribute(
                        attr_id=attr_name,
                        display_name=title,
                        category=cat,
                        attr_type=type_val,
                        current_value=cur_val,
                        default_value=def_val,
                        min_value=min_v,
                        max_value=max_v,
                        scalar_increment=step_v,
                        possible_values=poss_list,
                        path=cur_file
                    ))
            except Exception:
                pass

        self._cached_bios_attrs = attrs
        self._last_bios_attrs_scan = now
        return attrs

    def set_bios_attribute(self, attr_id: str, new_value: str) -> Tuple[bool, str]:
        """Aplica um novo valor para um atributo de BIOS Lenovo via sysfs firmware-attributes."""
        clean_val = str(new_value).strip()
        attrs = self.get_bios_attributes()
        target = next((a for a in attrs if a.attr_id == attr_id), None)
        path = target.path if target else None

        if not path:
            for bdir in glob.glob("/sys/class/firmware-attributes/*/attributes"):
                cand = os.path.join(bdir, attr_id, "current_value")
                if os.path.exists(cand):
                    path = cand
                    break

        if not path:
            return False, f"Atributo de firmware '{attr_id}' não encontrado no sistema."

        # Mapeamento estrito para atributos booleanos de acordo com os possíveis valores da BIOS
        poss = target.possible_values if (target and target.possible_values) else []
        if not poss and path:
            poss_f = os.path.join(os.path.dirname(path), "possible_values")
            poss_txt = self._read_file_text(poss_f) or ""
            if poss_txt:
                poss = [p.strip() for p in re.split(r"[;\n,]+", poss_txt) if p.strip()]

        if (target and target.attr_type == "boolean") or (poss and set(p.lower() for p in poss) in ({"0", "1"}, {"disabled", "enabled"}, {"off", "on"}, {"no", "yes"})):
            is_true = clean_val.lower() in ("1", "enabled", "on", "true", "yes")
            if poss:
                for p in poss:
                    p_low = p.lower()
                    if is_true and p_low in ("1", "enabled", "on", "true", "yes"):
                        clean_val = p
                        break
                    elif not is_true and p_low in ("0", "disabled", "off", "false", "no"):
                        clean_val = p
                        break
            else:
                clean_val = "1" if is_true else "0"

        switched_custom = self._ensure_custom_profile_for_wmi(path, allow_elevation=True)
        ok, msg = PermissionsManager.write_sysfs_value(path, clean_val, allow_elevation=True)
        if ok:
            self._cached_bios_attrs = None
            extra = " (Perfil alterado para Custom para liberar escrita WMI)" if switched_custom else ""
            return True, f"Atributo '{attr_id}' atualizado para '{clean_val}' com sucesso.{extra}"
        return False, msg

    # =========================================================================
    # RECURSO 4: Painel Dedicado do Modo Custom Lenovo (cTGP GPU + Dynamic Boost + WMI PPT)
    # =========================================================================
    def get_lenovo_custom_power_controls(self) -> List[Dict[str, Any]]:
        """Lê os limites dedicados de GPU (cTGP / Dynamic Boost) e PPT do lenovo-wmi-other."""
        wmi_dir = self.paths.lenovo_wmi_attr_dir
        if not wmi_dir or not os.path.isdir(wmi_dir):
            return []

        controls: List[Dict[str, Any]] = []
        for attr_id, label, unit, fb_min, fb_max in self.LENOVO_CUSTOM_POWER_ATTRS:
            a_dir = os.path.join(wmi_dir, attr_id)
            cur_p = os.path.join(a_dir, "current_value")
            if not os.path.exists(cur_p):
                continue
            cur_v = self._read_file_int(cur_p, default=-1)
            if cur_v < 0:
                continue
            def_v = self._read_file_int(os.path.join(a_dir, "default_value"), default=cur_v)
            raw_min = self._read_file_int(os.path.join(a_dir, "min_value"), default=0)
            raw_max = self._read_file_int(os.path.join(a_dir, "max_value"), default=0)
            step_v = max(1, self._read_file_int(os.path.join(a_dir, "scalar_increment"), default=1))

            has_real_bounds = (raw_max > raw_min)
            if has_real_bounds:
                min_v, max_v = raw_min, raw_max
            else:
                min_v = fb_min
                max_v = max(fb_max, cur_v + 20, def_v + 20)

            controls.append({
                "attr_id": attr_id,
                "label": label,
                "unit": unit,
                "current": cur_v,
                "default": def_v,
                "min": min_v,
                "max": max_v,
                "step": step_v,
                "has_real_bounds": has_real_bounds,
                "path": cur_p,
            })
        return controls

    def set_lenovo_custom_power_values(self, values: Dict[str, int], allow_elevation: bool = True) -> Tuple[bool, str]:
        """Aplica os valores de cTGP/Boost/PPT no lenovo-wmi-other ativando o perfil Custom antes."""
        controls = {c["attr_id"]: c for c in self.get_lenovo_custom_power_controls()}
        if not controls:
            return False, "Atributos Custom WMI de GPU/PPT não encontrados neste notebook."

        valid_items = [(aid, int(val)) for aid, val in values.items() if aid in controls]
        if not valid_items:
            return False, "Nenhum parâmetro válido informado para o Modo Custom."

        first_path = controls[valid_items[0][0]]["path"]
        switched = self._ensure_custom_profile_for_wmi(first_path, allow_elevation=allow_elevation)

        applied: List[str] = []
        rejected: List[str] = []
        for aid, raw_val in valid_items:
            ctrl = controls[aid]
            clamped = max(ctrl["min"], min(ctrl["max"], int(raw_val)))
            ok, _ = PermissionsManager.write_sysfs_value(ctrl["path"], str(clamped), allow_elevation=allow_elevation)
            if ok:
                applied.append(f"{aid}={clamped}{ctrl['unit']}")
            else:
                rejected.append(aid)

        self._cached_bios_attrs = None
        if applied:
            extra = " (Modo Custom ativado)" if switched else ""
            warn = f" [Ignorados pelo firmware: {', '.join(rejected)}]" if rejected else ""
            return True, f"Limites aplicados{extra}: {', '.join(applied)}{warn}"
        return False, f"Firmware recusou escrita para: {', '.join(rejected)}"

    def apply_lenovo_custom_power_preset(self, preset_key: str, allow_elevation: bool = True) -> Tuple[bool, str]:
        """Aplica preset rápido 1-clique: 'cool_quiet' (Jogos Frios) ou 'max_gpu' (Potência Máxima GPU)."""
        controls = self.get_lenovo_custom_power_controls()
        if not controls:
            return False, "Atributos Custom WMI de GPU/PPT não encontrados neste notebook."

        key = str(preset_key or "").strip().lower()
        if key not in ("cool_quiet", "max_gpu"):
            return False, f"Preset Custom desconhecido: {preset_key}"

        self._ensure_custom_profile_for_wmi(controls[0]["path"], allow_elevation=allow_elevation)

        applied: List[str] = []
        if key == "cool_quiet":
            cool_targets = {
                "gpu_nv_ctgp": 45,
                "gpu_nv_ppab": 0,
                "gpu_nv_cpu_boost": 5,
                "ppt_cpu_cl": 25,
                "ppt_pl1_spl": 30,
                "ppt_pl2_sppt": 45,
            }
            for c in controls:
                aid = c["attr_id"]
                target = max(c["min"], min(c["max"], cool_targets.get(aid, c["min"])))
                ok, _ = PermissionsManager.write_sysfs_value(c["path"], str(target), allow_elevation=allow_elevation)
                if ok:
                    applied.append(f"{aid}={target}W")
        else:
            for c in controls:
                aid = c["attr_id"]
                if c["has_real_bounds"]:
                    target = c["max"]
                    ok, _ = PermissionsManager.write_sysfs_value(c["path"], str(target), allow_elevation=allow_elevation)
                    if ok:
                        applied.append(f"{aid}={target}W")
                else:
                    # Quando kernel reporta min=0,max=0 (ex: LOQ cTGP), tenta boost seguro e faz fallback ao default
                    base = max(c["default"], c["current"])
                    for candidate in (base + 10, base + 5, base):
                        ok, _ = PermissionsManager.write_sysfs_value(c["path"], str(candidate), allow_elevation=allow_elevation)
                        if ok:
                            applied.append(f"{aid}={candidate}W")
                            break

        self._cached_bios_attrs = None
        if applied:
            title = "Jogos Frios & Silenciosos" if key == "cool_quiet" else "Potência Máxima GPU"
            return True, f"{title} aplicado: {', '.join(applied[:4])}"
        return False, "Não foi possível aplicar os limites no Modo Custom."

