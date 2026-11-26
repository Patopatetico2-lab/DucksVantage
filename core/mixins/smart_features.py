"""
Mixin de Recursos Inteligentes & Integração KDE Plasma 6 (core/mixins/smart_features.py):
- Bloqueio de Wake-on-USB (/sys/bus/usb/devices/*/power/wakeup)
- Detector de Thermal / Power Throttling em Tempo Real (CPU sysfs + NVIDIA)
- Leitura de energia RAPL para sessões de jogo
- Instalação do Widget KDE Plasma 6 (Plasmoid) e Plugin KRunner D-Bus
"""

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import psutil
from typing import Any, Dict, List, Optional, Tuple
from core.permissions import PermissionsManager
from core.mixins.telemetry_battery import HAS_PYNVML, pynvml


class SmartFeaturesMixin:
    """Agrupa recursos avançados de energia, térmicos, áudio, automação e integração Plasma 6."""

    # =========================================================================
    # 4. Bloqueio de Wake-on-USB (Evita mouse/dongle acordar notebook na mochila)
    # =========================================================================
    def get_usb_wakeup_devices(self) -> List[Dict[str, Any]]:
        """Lista dispositivos USB reais com controle /sys/bus/usb/devices/*/power/wakeup."""
        devices: List[Dict[str, Any]] = []
        for wk_path in sorted(glob.glob("/sys/bus/usb/devices/*/power/wakeup")):
            dev_dir = os.path.dirname(os.path.dirname(wk_path))
            bus_id = os.path.basename(dev_dir)
            # Ignora controladores raiz xHCI/EHCI (usb1, usb2...)
            if re.fullmatch(r"usb\d+", bus_id):
                continue
            state = (self._read_file_text(wk_path) or "").strip().lower()
            if state not in ("enabled", "disabled"):
                continue

            product = (self._read_file_text(os.path.join(dev_dir, "product")) or "").strip()
            manuf = (self._read_file_text(os.path.join(dev_dir, "manufacturer")) or "").strip()
            vid = (self._read_file_text(os.path.join(dev_dir, "idVendor")) or "").strip()
            pid = (self._read_file_text(os.path.join(dev_dir, "idProduct")) or "").strip()

            if product and manuf and manuf.lower() not in product.lower():
                friendly = f"{manuf} {product}".strip()
            elif product:
                friendly = product
            elif vid and pid:
                friendly = f"Dispositivo USB {vid}:{pid}"
            else:
                friendly = f"Porta USB {bus_id}"

            devices.append({
                "bus_id": bus_id,
                "name": friendly,
                "vendor_product": f"{vid}:{pid}" if (vid and pid) else bus_id,
                "path": wk_path,
                "enabled": (state == "enabled"),
            })
        return devices

    def get_usb_wakeup_blocked(self) -> bool:
        """Retorna True se o bloqueio Wake-on-USB estiver ativo ou todos dispositivos USB desativados."""
        devs = self.get_usb_wakeup_devices()
        if devs:
            return all(not d["enabled"] for d in devs)
        return bool(self.settings.get("usb_wakeup_blocked", False))

    def set_usb_wakeup_blocked(self, blocked: bool, allow_elevation: bool = True) -> Tuple[bool, str]:
        """Bloqueia ('disabled') ou reabilita ('enabled') wakeup dos dispositivos USB no sysfs."""
        devs = self.get_usb_wakeup_devices()
        if not devs:
            self.settings.set("usb_wakeup_blocked", bool(blocked))
            return False, "Nenhum dispositivo USB com suporte a wakeup foi detectado."

        target_val = "disabled" if blocked else "enabled"
        pairs = [(d["path"], target_val) for d in devs if d["enabled"] == bool(blocked)]
        if not pairs:
            self.settings.set("usb_wakeup_blocked", bool(blocked))
            return True, (
                f"Wake-on-USB já estava {'bloqueado' if blocked else 'liberado'} em {len(devs)} dispositivo(s)."
            )

        ok, msg = PermissionsManager.write_multiple_sysfs_values(pairs, allow_elevation=allow_elevation)
        if ok:
            self.settings.set("usb_wakeup_blocked", bool(blocked))
            return True, (
                f"Wake-on-USB {'bloqueado (seguro na mochila)' if blocked else 'liberado'} "
                f"em {len(pairs)} dispositivo(s)."
            )
        return False, msg

    # =========================================================================
    # 5. Detector de Thermal / Power Throttling em Tempo Real
    # =========================================================================
    def get_throttling_status(self) -> Dict[str, Any]:
        """
        Monitora eventos reais de Thermal Throttling da CPU (sysfs) e razões de limite
        da GPU NVIDIA sem acordar dGPU em estado D3cold.
        """
        total_cpu_events = 0
        cpu_paths = sorted(
            glob.glob("/sys/devices/system/cpu/cpu*/thermal_throttle/package_throttle_count")
            + glob.glob("/sys/devices/system/cpu/cpu*/thermal_throttle/core_throttle_count")
        )
        for p in cpu_paths:
            total_cpu_events += max(0, self._read_file_int(p, default=0))

        prev_sum = getattr(self, "_prev_cpu_throttle_sum", None)
        cpu_delta = 0 if prev_sum is None else max(0, total_cpu_events - prev_sum)
        self._prev_cpu_throttle_sum = total_cpu_events

        cpu_temp = 0.0
        if self.paths.cpu_temp_input:
            cpu_temp = self._read_file_int(self.paths.cpu_temp_input, default=0) / 1000.0

        cpu_throttling = bool(cpu_delta > 0 or cpu_temp >= 95.0)

        gpu_reasons = list(getattr(self, "_cached_gpu_throttle_reasons", []) or [])
        gpu_thermal = any(r in gpu_reasons for r in ("thermal_hw", "thermal_sw", "power_brake"))
        gpu_power_cap = ("power_cap" in gpu_reasons)

        reasons: List[str] = []
        if cpu_delta > 0:
            reasons.append(f"CPU Thermal Throttle (+{cpu_delta} eventos)")
        elif cpu_temp >= 95.0:
            reasons.append(f"CPU próxima do TJMax ({cpu_temp:.0f}°C)")
        if "thermal_hw" in gpu_reasons or "thermal_sw" in gpu_reasons:
            reasons.append("GPU NVIDIA em Thermal Slowdown")
        if "power_brake" in gpu_reasons:
            reasons.append("GPU Power Brake")
        if gpu_power_cap:
            reasons.append("GPU atingiu limite TGP (Power Cap)")

        if cpu_throttling or gpu_thermal:
            severity = "thermal"
            badge = "THROTTLING TÉRMICO"
        elif gpu_power_cap:
            severity = "power"
            badge = "POWER CAP GPU"
        else:
            severity = "ok"
            badge = "SEM THROTTLING"

        return {
            "throttling_now": bool(cpu_throttling or gpu_thermal or gpu_power_cap),
            "cpu_throttling": cpu_throttling,
            "gpu_thermal_throttling": gpu_thermal,
            "gpu_power_capped": gpu_power_cap,
            "cpu_total_events": total_cpu_events,
            "cpu_delta_events": cpu_delta,
            "reasons": reasons,
            "severity": severity,
            "badge": badge,
        }

    # =========================================================================
    # Consumo RAPL Intel (usado em métricas de sessão de jogos)
    # =========================================================================
    def _read_rapl_package_watts(self) -> float:
        """Lê consumo médio em Watts do domínio Intel RAPL package-0 via delta de energy_uj."""
        uj_path = "/sys/class/powercap/intel-rapl:0/energy_uj"
        if not os.path.exists(uj_path):
            return 0.0
        cur_uj = self._read_file_int(uj_path, default=-1)
        now = time.time()
        if cur_uj < 0:
            return 0.0
        prev_uj = getattr(self, "_prev_rapl_uj", None)
        prev_ts = getattr(self, "_prev_rapl_ts", 0.0)
        self._prev_rapl_uj = cur_uj
        self._prev_rapl_ts = now
        if prev_uj is None or prev_ts <= 0 or (now - prev_ts) <= 0.1 or cur_uj < prev_uj:
            return 0.0
        watts = ((cur_uj - prev_uj) / 1_000_000.0) / (now - prev_ts)
        return round(max(0.0, min(250.0, watts)), 1)

    # =========================================================================
    # 11 & 12. Instaladores KDE Plasma 6 (Plasmoid & KRunner D-Bus)
    # =========================================================================
    @staticmethod
    def is_kde_plasma_session() -> bool:
        """Retorna True quando o ambiente gráfico ativo é KDE Plasma."""
        cur = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
        sess = os.environ.get("DESKTOP_SESSION", "").upper()
        kde_full = os.environ.get("KDE_FULL_SESSION", "").strip().lower()
        return ("KDE" in cur or "PLASMA" in cur or "PLASMA" in sess or kde_full in ("true", "1"))

    @staticmethod
    def get_plasmoid_source_dir() -> str:
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        local_dir = os.path.join(repo_root, "plasmoid", "org.ducksvantage.plasmoid")
        if os.path.isdir(local_dir):
            return local_dir
        usr_share = "/usr/share/ducksvantage/plasmoid/org.ducksvantage.plasmoid"
        if os.path.isdir(usr_share):
            return usr_share
        return local_dir

    @staticmethod
    def get_plasmoid_install_dir() -> str:
        return os.path.expanduser("~/.local/share/plasma/plasmoids/org.ducksvantage.plasmoid")

    def is_kde_plasmoid_installed(self) -> bool:
        inst = self.get_plasmoid_install_dir()
        return os.path.exists(os.path.join(inst, "metadata.json")) and os.path.exists(
            os.path.join(inst, "contents", "ui", "main.qml")
        )

    def install_kde_plasmoid(self) -> Tuple[bool, str]:
        """Instala ou atualiza o widget nativo do Ducksvantage na barra do KDE Plasma 6."""
        src = self.get_plasmoid_source_dir()
        if not os.path.isdir(src):
            return False, f"Pacote Plasmoid não encontrado em {src}."

        kpkg = shutil.which("kpackagetool6")
        if kpkg:
            action_flag = "-u" if self.is_kde_plasmoid_installed() else "-i"
            try:
                res = subprocess.run([kpkg, "-t", "Plasma/Applet", action_flag, src], capture_output=True, text=True, timeout=10)
                if res.returncode == 0:
                    return True, "Widget KDE Plasma 6 instalado/atualizado! Clique com o botão direito no painel -> 'Adicionar Widgets' -> 'Ducksvantage'."
            except Exception:
                pass

        dst = self.get_plasmoid_install_dir()
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            return True, f"Widget KDE instalado em {dst}! Adicione pelo painel do Plasma."
        except Exception as e:
            return False, f"Falha ao instalar Plasmoid KDE: {e}"

    @staticmethod
    def get_krunner_desktop_path() -> str:
        return os.path.expanduser("~/.local/share/krunner/dbusplugins/plasma-runner-ducksvantage.desktop")

    def is_krunner_plugin_installed(self) -> bool:
        return os.path.isfile(self.get_krunner_desktop_path())

    def install_krunner_plugin(self) -> Tuple[bool, str]:
        """Registra o plugin D-Bus do Ducksvantage para busca rápida no KRunner (Alt+Espaço)."""
        desktop_path = self.get_krunner_desktop_path()
        dbus_svc_path = os.path.expanduser("~/.local/share/dbus-1/services/org.ducksvantage.Control.service")
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        main_py = os.path.join(repo_root, "main.py")
        icon_p = os.path.join(repo_root, "assets", "app_icon.svg")
        py_bin = sys.executable or shutil.which("python3") or "/usr/bin/python3"

        krunner_content = (
            "[Desktop Entry]\n"
            "Name=Ducksvantage\n"
            "Comment=Perfis térmicos, Hz, Eco-Mode e temperaturas no Lenovo\n"
            "Comment[pt_BR]=Perfis térmicos, Hz, Eco-Mode e temperaturas no Lenovo\n"
            f"Icon={icon_p if os.path.exists(icon_p) else 'ducksvantage'}\n"
            "Type=Service\n"
            "X-KDE-PluginInfo-Name=ducksvantage\n"
            "X-KDE-PluginInfo-Version=1.0\n"
            "X-KDE-PluginInfo-License=GPL-3.0\n"
            "X-KDE-PluginInfo-EnabledByDefault=true\n"
            "X-Plasma-API=DBus\n"
            "X-Plasma-DBusRunner-Service=org.ducksvantage.Control\n"
            "X-Plasma-DBusRunner-Path=/KRunner\n"
            "X-Plasma-Request-Actions-Once=true\n"
            "X-Plasma-Runner-Min-Letter-Count=2\n"
            "X-Plasma-Runner-Unique-Results=true\n"
            "X-Plasma-Runner-Weak-Results=true\n"
        )
        exec_cmd = "/usr/bin/ducksvantage --minimized" if os.path.exists("/usr/bin/ducksvantage") else f"{py_bin} {main_py} --minimized"
        service_content = (
            "[D-BUS Service]\n"
            "Name=org.ducksvantage.Control\n"
            f"Exec={exec_cmd}\n"
        )
        try:
            os.makedirs(os.path.dirname(desktop_path), exist_ok=True)
            with open(desktop_path, "w", encoding="utf-8") as fh:
                fh.write(krunner_content)
            os.chmod(desktop_path, 0o644)

            os.makedirs(os.path.dirname(dbus_svc_path), exist_ok=True)
            with open(dbus_svc_path, "w", encoding="utf-8") as fh:
                fh.write(service_content)
            os.chmod(dbus_svc_path, 0o644)

            if shutil.which("kquitapp6"):
                subprocess.run(["kquitapp6", "krunner"], capture_output=True, timeout=2)
            return True, "Plugin KRunner ativado! Pressione Alt+Espaço e digite 'dv', 'max', 'eco' ou 'hz'."
        except Exception as e:
            return False, f"Falha ao registrar plugin KRunner: {e}"

    # =========================================================================
    # 15. Carga 100% Única ("Carregar até 100% Só Hoje")
    # =========================================================================
    def get_one_time_full_charge_status(self) -> Dict[str, Any]:
        """Retorna estado do temporizador/gatilho de carga única até 100%."""
        supported = bool(self.features.conservation_mode)
        active = bool(supported and self.settings.get("one_time_full_charge_active", False))
        mode = str(self.settings.get("one_time_full_charge_mode", "until_full") or "until_full").strip().lower()
        if mode not in ("until_full", "2h", "4h", "8h"):
            mode = "until_full"
        until_ts = float(self.settings.get("one_time_full_charge_until_ts", 0.0) or 0.0)
        rem_mins = 0
        if active and mode != "until_full" and until_ts > 0:
            rem_mins = max(0, int((until_ts - time.time()) / 60.0))

        if not active:
            label = "Inativo (Conservação 80% normal)"
        elif mode == "until_full":
            label = "Carga até 100% ativa • Reativa 80% ao completar"
        else:
            hrs, mins = divmod(rem_mins, 60)
            t_str = f"{hrs}h{mins:02d}m" if hrs > 0 else f"{mins} min"
            label = f"Carga 100% temporária • Volta aos 80% em ~{t_str}"

        return {
            "supported": supported,
            "active": active,
            "mode": mode,
            "until_ts": until_ts,
            "remaining_minutes": rem_mins,
            "label": label,
        }

    def set_one_time_full_charge_mode(self, mode: str) -> None:
        m = str(mode or "until_full").strip().lower()
        if m not in ("until_full", "2h", "4h", "8h"):
            m = "until_full"
        self.settings.set("one_time_full_charge_mode", m)
        if bool(self.settings.get("one_time_full_charge_active", False)):
            hours_map = {"2h": 2, "4h": 4, "8h": 8}
            if m in hours_map:
                self.settings.set("one_time_full_charge_until_ts", time.time() + hours_map[m] * 3600.0)
            else:
                self.settings.set("one_time_full_charge_until_ts", 0.0)

    def start_one_time_full_charge(self, mode: Optional[str] = None) -> Tuple[bool, str]:
        """Desativa temporariamente a Conservação 80% para permitir carga até 100% hoje."""
        if not self.features.conservation_mode:
            return False, "Modo de Conservação não suportado neste hardware."
        m = str(mode or self.settings.get("one_time_full_charge_mode", "until_full") or "until_full").strip().lower()
        if m not in ("until_full", "2h", "4h", "8h"):
            m = "until_full"

        ok, msg = self.set_conservation_mode(False)
        if not ok:
            return False, msg

        hours_map = {"2h": 2, "4h": 4, "8h": 8}
        until_ts = (time.time() + hours_map[m] * 3600.0) if m in hours_map else 0.0
        self.settings.set("one_time_full_charge_mode", m)
        self.settings.set("one_time_full_charge_until_ts", until_ts)
        self.settings.set("one_time_full_charge_active", True)
        if m == "until_full":
            return True, "Carga até 100% liberada hoje! A Conservação 80% voltará automaticamente ao completar."
        return True, f"Carga até 100% liberada por {m}! Conservação 80% será reativada automaticamente."

    def cancel_one_time_full_charge(self, restore_conservation: bool = True) -> Tuple[bool, str]:
        """Encerra a carga 100% única e restaura a Conservação 80% se solicitado."""
        self.settings.set("one_time_full_charge_active", False)
        self.settings.set("one_time_full_charge_until_ts", 0.0)
        if restore_conservation and self.features.conservation_mode:
            ok, msg = self.set_conservation_mode(True)
            if not ok:
                return False, msg
            return True, "Conservação 80% restaurada."
        return True, "Temporizador de carga 100% cancelado."

    def check_one_time_full_charge_tick(self) -> Optional[Dict[str, Any]]:
        """Monitora se a carga 100% foi atingida ou se o tempo expirou para restaurar 80%."""
        if not self.features.conservation_mode or not bool(self.settings.get("one_time_full_charge_active", False)):
            return None
        if self.get_conservation_mode():
            self.settings.set("one_time_full_charge_active", False)
            self.settings.set("one_time_full_charge_until_ts", 0.0)
            return None

        mode = str(self.settings.get("one_time_full_charge_mode", "until_full") or "until_full").strip().lower()
        until_ts = float(self.settings.get("one_time_full_charge_until_ts", 0.0) or 0.0)
        bat = self.get_battery_info()

        reached_full = bool(
            bat.available and (bat.capacity_percent >= 99 or bat.status.strip().lower() == "full")
        )
        expired = bool(until_ts > 0 and time.time() >= until_ts)
        if mode != "until_full" and expired:
            reason = f"Tempo ({mode}) expirado"
        elif reached_full:
            reason = f"Carga em {bat.capacity_percent}%"
        elif expired:
            reason = "Prazo expirado"
        else:
            return None

        ok, _ = self.cancel_one_time_full_charge(restore_conservation=True)
        if not ok:
            return None
        return {
            "type": "one_time_full_charge_completed",
            "percent": bat.capacity_percent,
            "reason": reason,
            "summary": f"{reason} • Conservação 80% reativada automaticamente!",
        }

    # =========================================================================
    # 16. Detector de Processos Acordando a GPU NVIDIA ("Vilões da Bateria")
    # =========================================================================
    def get_nvidia_wakelock_processes(self, force: bool = False) -> Dict[str, Any]:
        """
        Lista processos mantendo a GPU NVIDIA acordada fora do D3cold.
        NUNCA consulta pynvml/nvidia-smi se runtime_status já estiver em D3cold ('suspended').
        """
        now = time.time()
        cached = getattr(self, "_cached_nvidia_wakelocks", None)
        last_t = getattr(self, "_last_nvidia_wakelock_scan", 0.0)
        if not force and cached is not None and (now - last_t < 4.0):
            return cached

        pci_ctrl = "auto"
        if self.paths.nvidia_pci_power_control and os.path.exists(self.paths.nvidia_pci_power_control):
            pci_ctrl = (self._read_file_text(self.paths.nvidia_pci_power_control) or "auto").strip()

        if self.paths.nvidia_drm_card:
            rt_path = os.path.join(self.paths.nvidia_drm_card, "device", "power", "runtime_status")
            rt_status = (self._read_file_text(rt_path) or "active").lower()
            if "suspend" in rt_status:
                res = {
                    "supported": bool(self.features.nvidia_wakelock_detect),
                    "gpu_awake": False,
                    "runtime_state": "D3cold",
                    "pci_power_control": pci_ctrl,
                    "processes": [],
                    "offenders": [],
                }
                self._cached_nvidia_wakelocks = res
                self._last_nvidia_wakelock_scan = now
                return res

        if not self.features.nvidia_wakelock_detect:
            res = {
                "supported": False,
                "gpu_awake": False,
                "runtime_state": "iGPU",
                "pci_power_control": pci_ctrl,
                "processes": [],
                "offenders": [],
            }
            self._cached_nvidia_wakelocks = res
            self._last_nvidia_wakelock_scan = now
            return res

        system_names = {
            "xorg", "xwayland", "kwin_wayland", "kwin_x11", "gnome-shell",
            "mutter", "sway", "hyprland", "sddm", "sddm-greeter", "gdm",
            "plasmashell", "nvidia-powerd", "systemd", "dbus-daemon",
        }
        cur_uid = os.getuid() if hasattr(os, "getuid") else None
        my_pid = os.getpid()
        found_by_pid: Dict[int, Dict[str, Any]] = {}

        def _add_proc(pid_val: int, name_val: str = "", vram_mb: int = 0) -> None:
            if pid_val <= 0 or pid_val == my_pid:
                return
            entry = found_by_pid.get(pid_val)
            clean_name = os.path.basename((name_val or "").replace("\\", "/").strip())
            if not entry:
                found_by_pid[pid_val] = {
                    "pid": pid_val,
                    "name": clean_name or f"pid-{pid_val}",
                    "vram_mb": max(0, int(vram_mb)),
                }
            else:
                if clean_name and entry["name"].startswith("pid-"):
                    entry["name"] = clean_name
                if vram_mb > entry["vram_mb"]:
                    entry["vram_mb"] = int(vram_mb)

        # 1. NVML (se inicializado e GPU já acordada)
        if getattr(self, "_nvml_initialized", False) and pynvml is not None:
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                for fn_name in ("nvmlDeviceGetComputeRunningProcesses", "nvmlDeviceGetGraphicsRunningProcesses"):
                    fn = getattr(pynvml, fn_name, None)
                    if not fn:
                        continue
                    try:
                        for item in fn(handle):
                            used_b = getattr(item, "usedGpuMemory", 0) or 0
                            mb = int(used_b / (1024 * 1024)) if 0 < used_b < (1 << 50) else 0
                            _add_proc(int(item.pid), "", mb)
                    except Exception:
                        continue
            except Exception:
                pass

        # 2. nvidia-smi pmon / compute-apps
        smi = shutil.which("nvidia-smi")
        if smi:
            try:
                r = subprocess.run(
                    [smi, "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=1.5
                )
                if r.returncode == 0 and r.stdout.strip():
                    for line in r.stdout.splitlines():
                        parts = [p.strip() for p in line.split(",")]
                        if len(parts) >= 2 and parts[0].isdigit():
                            mb = int(float(parts[2])) if len(parts) >= 3 and parts[2].replace(".", "", 1).isdigit() else 0
                            _add_proc(int(parts[0]), parts[1], mb)
            except Exception:
                pass
            try:
                rp = subprocess.run(
                    [smi, "pmon", "-c", "1", "-s", "m"],
                    capture_output=True, text=True, timeout=1.5
                )
                if rp.returncode == 0 and rp.stdout:
                    for line in rp.stdout.splitlines():
                        sline = line.strip()
                        if not sline or sline.startswith("#"):
                            continue
                        cols = sline.split()
                        if len(cols) >= 5 and cols[1].isdigit():
                            pid_v = int(cols[1])
                            fb_mb = int(cols[3]) if cols[3].isdigit() else 0
                            cmd_v = cols[-1]
                            _add_proc(pid_v, cmd_v, fb_mb)
            except Exception:
                pass

        # 3. /proc/<pid>/fd apontando para /dev/nvidia* + metadados (UID/nome)
        try:
            for p in psutil.process_iter(["pid", "name", "uids"]):
                try:
                    pid_v = int(p.info["pid"])
                    if pid_v <= 0 or pid_v == my_pid:
                        continue
                    pname = (p.info.get("name") or "").strip()
                    uids = p.info.get("uids")
                    same_uid = (cur_uid is None) or (uids is not None and getattr(uids, "real", cur_uid) == cur_uid)
                    if pid_v in found_by_pid:
                        if pname:
                            found_by_pid[pid_v]["name"] = pname
                        found_by_pid[pid_v]["same_uid"] = same_uid
                        continue
                    if not same_uid:
                        continue
                    fd_dir = f"/proc/{pid_v}/fd"
                    if os.path.isdir(fd_dir):
                        for fd_name in os.listdir(fd_dir)[:48]:
                            try:
                                target = os.readlink(os.path.join(fd_dir, fd_name))
                                if target.startswith("/dev/nvidia"):
                                    _add_proc(pid_v, pname, 0)
                                    found_by_pid[pid_v]["same_uid"] = True
                                    break
                            except OSError:
                                continue
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        except Exception:
            pass

        processes: List[Dict[str, Any]] = []
        offenders: List[Dict[str, Any]] = []
        for pid_v, entry in found_by_pid.items():
            name_low = entry["name"].lower()
            is_sys = (name_low in system_names) or (entry.get("same_uid") is False)
            row = {
                "pid": pid_v,
                "name": entry["name"],
                "vram_mb": entry["vram_mb"],
                "is_system": bool(is_sys),
            }
            processes.append(row)
            if not is_sys:
                offenders.append(row)

        processes.sort(key=lambda r: (r["is_system"], -r["vram_mb"], r["name"].lower()))
        offenders.sort(key=lambda r: (-r["vram_mb"], r["name"].lower()))

        res = {
            "supported": True,
            "gpu_awake": True,
            "runtime_state": "active",
            "pci_power_control": pci_ctrl,
            "processes": processes,
            "offenders": offenders,
        }
        self._cached_nvidia_wakelocks = res
        self._last_nvidia_wakelock_scan = now
        return res

    def release_nvidia_wakelocks(self, terminate_offenders: bool = True) -> Tuple[bool, str]:
        """Garante PCIe power/control='auto' e opcionalmente fecha apps de usuário segurando a GPU NVIDIA."""
        info = self.get_nvidia_wakelock_processes(force=True)
        closed: List[str] = []
        failed: List[str] = []

        if terminate_offenders:
            for item in info.get("offenders", []):
                pid_v = int(item.get("pid", 0))
                pname = str(item.get("name", pid_v))
                if pid_v <= 0 or pid_v == os.getpid():
                    continue
                try:
                    psutil.Process(pid_v).terminate()
                    closed.append(pname)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    failed.append(pname)
                except Exception:
                    failed.append(pname)

        pm_ok = False
        if self.paths.nvidia_pci_power_control and os.path.exists(self.paths.nvidia_pci_power_control):
            pm_ok, _ = PermissionsManager.write_sysfs_value(
                self.paths.nvidia_pci_power_control, "auto", allow_elevation=False
            )

        self._cached_nvidia_wakelocks = None
        self._last_nvidia_wakelock_scan = 0.0

        parts: List[str] = []
        if closed:
            parts.append(f"Encerrados: {', '.join(closed[:4])}")
        if pm_ok:
            parts.append("PCIe Runtime PM em 'auto' (D3cold liberado)")
        if failed:
            parts.append(f"Não foi possível fechar: {', '.join(failed[:3])}")
        if not parts:
            parts.append("Nenhum processo bloqueador encontrado; GPU pronta para entrar em D3cold.")
        return True, " • ".join(parts)

    # =========================================================================
    # 17. Brilho Automático de Tela (KDE Plasma 6 ScreenBrightness / PowerDevil / GNOME / logind / Sysfs)
    # =========================================================================
    @staticmethod
    def _is_interactive_dbus_session() -> bool:
        plat = (os.environ.get("QT_QPA_PLATFORM") or "").lower()
        return bool(plat not in ("offscreen", "minimal") and os.environ.get("DBUS_SESSION_BUS_ADDRESS"))

    @staticmethod
    def _kde6_find_internal_display_dbus(bus) -> Optional[str]:
        """Retorna object path do display interno no org.kde.ScreenBrightness (Plasma 6.2+)."""
        try:
            root_obj = bus.get_object("org.kde.ScreenBrightness", "/org/kde/ScreenBrightness")
            root_props = bus.get_object  # noop lint guard
            del root_props
            import dbus
            props_iface = dbus.Interface(root_obj, "org.freedesktop.DBus.Properties")
            names = list(props_iface.Get("org.kde.ScreenBrightness", "DisplaysDBusNames"))
            if not names:
                return None
            first_path = None
            for raw_name in names:
                s_name = str(raw_name).strip()
                if not s_name:
                    continue
                d_path = s_name if s_name.startswith("/") else f"/org/kde/ScreenBrightness/{s_name}"
                if first_path is None:
                    first_path = d_path
                try:
                    d_obj = bus.get_object("org.kde.ScreenBrightness", d_path)
                    d_props = dbus.Interface(d_obj, "org.freedesktop.DBus.Properties")
                    if bool(d_props.Get("org.kde.ScreenBrightness.Display", "IsInternal")):
                        return d_path
                except Exception:
                    continue
            return first_path
        except Exception:
            return None

    @staticmethod
    def _kde6_find_internal_display_qdbus(qdbus_bin: str) -> Optional[str]:
        """Versão CLI via qdbus6/qdbus para descobrir display interno no org.kde.ScreenBrightness."""
        try:
            r_names = subprocess.run(
                [
                    qdbus_bin, "org.kde.ScreenBrightness", "/org/kde/ScreenBrightness",
                    "org.kde.ScreenBrightness.DisplaysDBusNames",
                ],
                capture_output=True, text=True, timeout=1.5
            )
            if r_names.returncode != 0 or not r_names.stdout.strip():
                return None
            names = [ln.strip() for ln in r_names.stdout.splitlines() if ln.strip()]
            first_path = None
            for s_name in names:
                d_path = s_name if s_name.startswith("/") else f"/org/kde/ScreenBrightness/{s_name}"
                if first_path is None:
                    first_path = d_path
                try:
                    r_int = subprocess.run(
                        [
                            qdbus_bin, "org.kde.ScreenBrightness", d_path,
                            "org.kde.ScreenBrightness.Display.IsInternal",
                        ],
                        capture_output=True, text=True, timeout=1.0
                    )
                    if r_int.returncode == 0 and r_int.stdout.strip().lower() == "true":
                        return d_path
                except Exception:
                    continue
            return first_path
        except Exception:
            return None

    def get_screen_brightness_pct(self) -> Optional[int]:
        """Lê o brilho atual do painel em porcentagem (0..100), priorizando o daemon gráfico ativo."""
        if self._is_interactive_dbus_session():
            # 1. KDE Plasma 6.2+ (org.kde.ScreenBrightness) via dbus-python
            try:
                import dbus
                bus = dbus.SessionBus()
                d_path = self._kde6_find_internal_display_dbus(bus)
                if d_path:
                    d_obj = bus.get_object("org.kde.ScreenBrightness", d_path)
                    d_props = dbus.Interface(d_obj, "org.freedesktop.DBus.Properties")
                    mx = int(d_props.Get("org.kde.ScreenBrightness.Display", "MaxBrightness"))
                    cur = int(d_props.Get("org.kde.ScreenBrightness.Display", "Brightness"))
                    if mx > 0 and cur >= 0:
                        return max(0, min(100, int(round((cur / float(mx)) * 100.0))))
            except Exception:
                pass

            # 2. KDE Plasma 6.2+ via qdbus6/qdbus
            qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
            if qdbus:
                d_path = self._kde6_find_internal_display_qdbus(qdbus)
                if d_path:
                    try:
                        rmax = subprocess.run(
                            [qdbus, "org.kde.ScreenBrightness", d_path, "org.kde.ScreenBrightness.Display.MaxBrightness"],
                            capture_output=True, text=True, timeout=1.5
                        )
                        rcur = subprocess.run(
                            [qdbus, "org.kde.ScreenBrightness", d_path, "org.kde.ScreenBrightness.Display.Brightness"],
                            capture_output=True, text=True, timeout=1.5
                        )
                        if rmax.returncode == 0 and rcur.returncode == 0:
                            mx = int(rmax.stdout.strip())
                            cur = int(rcur.stdout.strip())
                            if mx > 0 and cur >= 0:
                                return max(0, min(100, int(round((cur / float(mx)) * 100.0))))
                    except Exception:
                        pass

            # 3. KDE PowerDevil legado (org.kde.Solid.PowerManagement)
            try:
                import dbus
                bus = dbus.SessionBus()
                obj = bus.get_object(
                    "org.kde.Solid.PowerManagement",
                    "/org/kde/Solid/PowerManagement/Actions/BrightnessControl",
                )
                iface = dbus.Interface(obj, "org.kde.Solid.PowerManagement.Actions.BrightnessControl")
                mx = int(iface.brightnessMax())
                cur = int(iface.brightness())
                if mx > 0 and cur >= 0:
                    return max(0, min(100, int(round((cur / float(mx)) * 100.0))))
            except Exception:
                pass

            # 4. GNOME Settings Daemon
            try:
                import dbus
                bus = dbus.SessionBus()
                obj = bus.get_object("org.gnome.SettingsDaemon.Power", "/org/gnome/SettingsDaemon/Power")
                props = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
                val = int(props.Get("org.gnome.SettingsDaemon.Power.Screen", "Brightness"))
                if 0 <= val <= 100:
                    return val
            except Exception:
                pass

        # 5. brightnessctl (independente de root via systemd-logind)
        if shutil.which("brightnessctl") and (os.environ.get("QT_QPA_PLATFORM") or "").lower() not in ("offscreen", "minimal"):
            try:
                res = subprocess.run(["brightnessctl", "-m"], capture_output=True, text=True, timeout=1.5)
                if res.returncode == 0 and res.stdout.strip():
                    parts = res.stdout.strip().splitlines()[0].split(",")
                    if len(parts) >= 4 and "%" in parts[3]:
                        return max(0, min(100, int(parts[3].rstrip("%").strip())))
            except Exception:
                pass

        # 6. Fallback sysfs (/sys/class/backlight/*)
        if self.paths.backlight_dir:
            mx = self._read_file_int(self.paths.backlight_max_brightness, default=0)
            cur = self._read_file_int(os.path.join(self.paths.backlight_dir, "actual_brightness"), default=-1)
            if cur < 0:
                cur = self._read_file_int(self.paths.backlight_brightness, default=-1)
            if mx > 0 and cur >= 0:
                return max(0, min(100, int(round((cur / float(mx)) * 100.0))))

        return None

    def set_screen_brightness_pct(self, pct: int, allow_elevation: bool = False) -> Tuple[bool, str]:
        """
        Ajusta o brilho da tela (5..100%) de forma sincronizada com o desktop ativo:
        KDE Plasma 6.2+ ScreenBrightness -> PowerDevil legado -> GNOME -> brightnessctl -> logind -> sysfs.
        """
        target_pct = max(5, min(100, int(pct)))

        if self._is_interactive_dbus_session():
            # 1. KDE Plasma 6.2+ (org.kde.ScreenBrightness) via dbus-python
            try:
                import dbus
                bus = dbus.SessionBus()
                d_path = self._kde6_find_internal_display_dbus(bus)
                if d_path:
                    d_obj = bus.get_object("org.kde.ScreenBrightness", d_path)
                    d_props = dbus.Interface(d_obj, "org.freedesktop.DBus.Properties")
                    mx = int(d_props.Get("org.kde.ScreenBrightness.Display", "MaxBrightness"))
                    if mx > 0:
                        raw_val = max(1, min(mx, int(round((target_pct / 100.0) * mx))))
                        d_iface = dbus.Interface(d_obj, "org.kde.ScreenBrightness.Display")
                        d_iface.SetBrightness(dbus.Int32(raw_val), dbus.UInt32(0))
                        return True, f"Brilho da tela ajustado para {target_pct}%."
            except Exception:
                pass

            # 2. KDE Plasma 6.2+ via qdbus6/qdbus
            qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
            if qdbus:
                d_path = self._kde6_find_internal_display_qdbus(qdbus)
                if d_path:
                    try:
                        rmax = subprocess.run(
                            [qdbus, "org.kde.ScreenBrightness", d_path, "org.kde.ScreenBrightness.Display.MaxBrightness"],
                            capture_output=True, text=True, timeout=1.5
                        )
                        if rmax.returncode == 0 and rmax.stdout.strip().isdigit():
                            mx = int(rmax.stdout.strip())
                            if mx > 0:
                                raw_val = max(1, min(mx, int(round((target_pct / 100.0) * mx))))
                                rset = subprocess.run(
                                    [
                                        qdbus, "org.kde.ScreenBrightness", d_path,
                                        "org.kde.ScreenBrightness.Display.SetBrightness", str(raw_val), "0",
                                    ],
                                    capture_output=True, text=True, timeout=1.5
                                )
                                if rset.returncode == 0:
                                    return True, f"Brilho da tela ajustado para {target_pct}%."
                    except Exception:
                        pass

            # 3. KDE PowerDevil legado (prefere setBrightness ao invés de setBrightnessSilent para não travar o slider)
            try:
                import dbus
                bus = dbus.SessionBus()
                obj = bus.get_object(
                    "org.kde.Solid.PowerManagement",
                    "/org/kde/Solid/PowerManagement/Actions/BrightnessControl",
                )
                iface = dbus.Interface(obj, "org.kde.Solid.PowerManagement.Actions.BrightnessControl")
                mx = int(iface.brightnessMax())
                if mx > 0:
                    raw_val = max(1, min(mx, int(round((target_pct / 100.0) * mx))))
                    try:
                        iface.setBrightness(raw_val)
                    except Exception:
                        iface.setBrightnessSilent(raw_val)
                    return True, f"Brilho da tela ajustado para {target_pct}%."
            except Exception:
                pass

            if qdbus:
                try:
                    rmax = subprocess.run(
                        [
                            qdbus, "org.kde.Solid.PowerManagement",
                            "/org/kde/Solid/PowerManagement/Actions/BrightnessControl",
                            "brightnessMax",
                        ],
                        capture_output=True, text=True, timeout=1.5
                    )
                    if rmax.returncode == 0 and rmax.stdout.strip().isdigit():
                        mx = int(rmax.stdout.strip())
                        if mx > 0:
                            raw_val = max(1, min(mx, int(round((target_pct / 100.0) * mx))))
                            rset = subprocess.run(
                                [
                                    qdbus, "org.kde.Solid.PowerManagement",
                                    "/org/kde/Solid/PowerManagement/Actions/BrightnessControl",
                                    "setBrightness", str(raw_val),
                                ],
                                capture_output=True, text=True, timeout=1.5
                            )
                            if rset.returncode == 0:
                                return True, f"Brilho da tela ajustado para {target_pct}%."
                except Exception:
                    pass

            # 4. GNOME Settings Daemon
            try:
                import dbus
                bus = dbus.SessionBus()
                obj = bus.get_object("org.gnome.SettingsDaemon.Power", "/org/gnome/SettingsDaemon/Power")
                props = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
                props.Set("org.gnome.SettingsDaemon.Power.Screen", "Brightness", dbus.Int32(target_pct))
                return True, f"Brilho da tela ajustado para {target_pct}%."
            except Exception:
                pass

        # 5. brightnessctl
        if shutil.which("brightnessctl") and (os.environ.get("QT_QPA_PLATFORM") or "").lower() not in ("offscreen", "minimal"):
            try:
                res = subprocess.run(["brightnessctl", "set", f"{target_pct}%"], capture_output=True, text=True, timeout=1.5)
                if res.returncode == 0:
                    return True, f"Brilho da tela ajustado para {target_pct}%."
            except Exception:
                pass

        # 6. systemd-logind Session.SetBrightness (sem precisar de regra UDEV)
        if self.paths.backlight_dir and self.paths.backlight_max_brightness and (os.environ.get("QT_QPA_PLATFORM") or "").lower() not in ("offscreen", "minimal"):
            mx = self._read_file_int(self.paths.backlight_max_brightness, default=0)
            if mx > 0:
                raw_val = max(1, min(mx, int(round((target_pct / 100.0) * mx))))
                bl_name = os.path.basename(self.paths.backlight_dir)
                try:
                    import dbus
                    sys_bus = dbus.SystemBus()
                    sess_obj = sys_bus.get_object("org.freedesktop.login1", "/org/freedesktop/login1/session/auto")
                    sess_iface = dbus.Interface(sess_obj, "org.freedesktop.login1.Session")
                    sess_iface.SetBrightness("backlight", bl_name, dbus.UInt32(raw_val))
                    return True, f"Brilho da tela ajustado para {target_pct}%."
                except Exception:
                    pass

        # 7. Sysfs direto (/sys/class/backlight/*/brightness)
        if self.paths.backlight_brightness and self.paths.backlight_max_brightness:
            mx = self._read_file_int(self.paths.backlight_max_brightness, default=0)
            if mx > 0:
                raw_val = max(1, min(mx, int(round((target_pct / 100.0) * mx))))
                ok, msg = PermissionsManager.write_sysfs_value(
                    self.paths.backlight_brightness, str(raw_val), allow_elevation=allow_elevation
                )
                if ok:
                    return True, f"Brilho da tela ajustado para {target_pct}%."
                return False, msg

        return False, "Controle de brilho de tela indisponível neste ambiente."

    def get_brightness_automation_config(self) -> Dict[str, Any]:
        return {
            "supported": bool(self.features.screen_brightness),
            "eco_dim_enabled": bool(self.settings.get("eco_dim_brightness_enabled", True)),
            "eco_brightness_pct": max(5, min(100, int(self.settings.get("eco_brightness_pct", 40) or 40))),
        }

    def set_brightness_automation_config(
        self,
        eco_dim_enabled: bool = True,
        eco_brightness_pct: int = 40,
    ) -> None:
        self.settings.set("eco_dim_brightness_enabled", bool(eco_dim_enabled))
        self.settings.set("eco_brightness_pct", max(5, min(100, int(eco_brightness_pct))))

    # =========================================================================
    # 18. Saúde e Vida Útil do SSD NVMe (UDisks2 / SMART / Sysfs)
    # =========================================================================
    @staticmethod
    def _parse_udisks_nvme_smart_dict(
        smart_attrs: Dict[str, Any],
        power_on_hours: int = 0,
        smart_temp_k: int = 0,
    ) -> Dict[str, Any]:
        """Normaliza o dicionário de SmartGetAttributes (UDisks2) em métricas legíveis."""
        def _as_int(key: str, default: int = 0) -> int:
            v = smart_attrs.get(key, default)
            try:
                return int(v)
            except Exception:
                return default

        percent_used = max(0, min(100, _as_int("percent_used", -1)))
        avail_spare = max(0, min(100, _as_int("avail_spare", 100)))
        spare_thresh = max(0, min(100, _as_int("spare_thresh", 10)))
        written_bytes = _as_int("total_data_written", 0)
        read_bytes = _as_int("total_data_read", 0)
        cycles = _as_int("power_cycles", 0)
        unsafe = _as_int("unsafe_shutdowns", 0)
        media_err = _as_int("media_errors", 0)

        temp_c = 0.0
        temps = smart_attrs.get("temp_sensors")
        if isinstance(temps, (list, tuple)) and temps:
            try:
                first_k = int(temps[0])
                if first_k > 150:
                    temp_c = round(first_k - 273.15, 1)
            except Exception:
                pass
        if temp_c <= 0.0 and smart_temp_k > 150:
            temp_c = round(smart_temp_k - 273.15, 1)

        health_pct = max(0, 100 - percent_used) if percent_used >= 0 else None
        return {
            "smart_available": True,
            "health_percent": health_pct,
            "wear_percent": percent_used if percent_used >= 0 else None,
            "avail_spare_percent": avail_spare,
            "spare_thresh_percent": spare_thresh,
            "tbw_tb": round(written_bytes / 1e12, 2) if written_bytes > 0 else 0.0,
            "tbr_tb": round(read_bytes / 1e12, 2) if read_bytes > 0 else 0.0,
            "power_on_hours": int(power_on_hours or 0),
            "power_cycles": cycles,
            "unsafe_shutdowns": unsafe,
            "media_errors": media_err,
            "temp_c": temp_c,
        }

    def get_nvme_health_info(self, force: bool = False) -> List[Dict[str, Any]]:
        """Coleta saúde (wear %), TBW, horas de uso, ciclos e temperatura de SSDs NVMe sem root."""
        now = time.time()
        cached = getattr(self, "_cached_nvme_health", None)
        last_t = getattr(self, "_last_nvme_health_scan", 0.0)
        if not force and cached is not None and (now - last_t < 30.0):
            return cached

        udisks_by_ctrl: Dict[str, Dict[str, Any]] = {}
        try:
            import dbus
            bus = dbus.SystemBus()
            mgr_obj = bus.get_object("org.freedesktop.UDisks2", "/org/freedesktop/UDisks2")
            mgr = dbus.Interface(mgr_obj, "org.freedesktop.DBus.ObjectManager")
            objs = mgr.GetManagedObjects()

            block_by_drive: Dict[str, str] = {}
            for path, ifaces in objs.items():
                blk = ifaces.get("org.freedesktop.UDisks2.Block")
                if blk:
                    drv_p = str(blk.get("Drive", ""))
                    dev_p = bytes(blk.get("Device", b"")).rstrip(b"\x00").decode("utf-8", errors="ignore")
                    if drv_p and re.fullmatch(r"/dev/nvme\d+n\d+", dev_p):
                        ctrl_name = re.sub(r"n\d+$", "", os.path.basename(dev_p))
                        block_by_drive[drv_p] = ctrl_name

            for path, ifaces in objs.items():
                nv_ctrl = ifaces.get("org.freedesktop.UDisks2.NVMe.Controller")
                if not nv_ctrl:
                    continue
                ctrl_name = block_by_drive.get(str(path), "")
                smart_raw: Dict[str, Any] = {}
                try:
                    drv_obj = bus.get_object("org.freedesktop.UDisks2", path)
                    ctrl_iface = dbus.Interface(drv_obj, "org.freedesktop.UDisks2.NVMe.Controller")
                    smart_raw = dict(ctrl_iface.SmartGetAttributes({}))
                except Exception:
                    smart_raw = {}
                parsed = self._parse_udisks_nvme_smart_dict(
                    smart_raw,
                    power_on_hours=int(nv_ctrl.get("SmartPowerOnHours", 0) or 0),
                    smart_temp_k=int(nv_ctrl.get("SmartTemperature", 0) or 0),
                )
                crit = nv_ctrl.get("SmartCriticalWarning")
                parsed["critical_warning"] = ", ".join(str(x) for x in crit) if crit else ""
                if ctrl_name:
                    udisks_by_ctrl[ctrl_name] = parsed
                udisks_by_ctrl.setdefault("__first__", parsed)
        except Exception:
            pass

        results: List[Dict[str, Any]] = []
        ctrl_dirs = sorted(glob.glob("/sys/class/nvme/nvme*"))
        if not ctrl_dirs:
            for blk_dir in sorted(glob.glob("/sys/block/nvme*n*")):
                c_name = re.sub(r"n\d+$", "", os.path.basename(blk_dir))
                if c_name not in [os.path.basename(x) for x in ctrl_dirs]:
                    ctrl_dirs.append(os.path.join("/sys/class/nvme", c_name))

        for c_dir in ctrl_dirs:
            c_name = os.path.basename(c_dir)
            model = (self._read_file_text(os.path.join(c_dir, "model")) or "").strip()
            if not model:
                model = (self._read_file_text(f"/sys/block/{c_name}n1/device/model") or "SSD NVMe").strip()
            fw = (self._read_file_text(os.path.join(c_dir, "firmware_rev")) or "--").strip()

            temp_c = 0.0
            hw_temps = sorted(glob.glob(os.path.join(c_dir, "hwmon*", "temp1_input")))
            if hw_temps:
                temp_c = round(self._read_file_int(hw_temps[0], 0) / 1000.0, 1)
            elif self.paths.nvme_temp_input and len(results) == 0:
                temp_c = round(self._read_file_int(self.paths.nvme_temp_input, 0) / 1000.0, 1)

            smart = udisks_by_ctrl.get(c_name) or (udisks_by_ctrl.get("__first__") if len(ctrl_dirs) == 1 else None) or {}
            if not smart and shutil.which("smartctl"):
                dev_node = f"/dev/{c_name}n1"
                if os.path.exists(dev_node):
                    try:
                        r_sc = subprocess.run(
                            ["smartctl", "-j", "-A", "-n", "standby", dev_node],
                            capture_output=True, text=True, timeout=1.5
                        )
                        if r_sc.stdout.strip().startswith("{"):
                            jdata = json.loads(r_sc.stdout)
                            nv_log = jdata.get("nvme_smart_health_information_log") or {}
                            if nv_log:
                                pct_used = int(nv_log.get("percentage_used", 0))
                                d_written = int(nv_log.get("data_units_written", 0)) * 512000
                                d_read = int(nv_log.get("data_units_read", 0)) * 512000
                                smart = {
                                    "smart_available": True,
                                    "health_percent": max(0, 100 - pct_used),
                                    "wear_percent": pct_used,
                                    "avail_spare_percent": int(nv_log.get("available_spare", 100)),
                                    "spare_thresh_percent": int(nv_log.get("available_spare_threshold", 10)),
                                    "tbw_tb": round(d_written / 1e12, 2),
                                    "tbr_tb": round(d_read / 1e12, 2),
                                    "power_on_hours": int(nv_log.get("power_on_hours", 0)),
                                    "power_cycles": int(nv_log.get("power_cycles", 0)),
                                    "unsafe_shutdowns": int(nv_log.get("unsafe_shutdowns", 0)),
                                    "media_errors": int(nv_log.get("media_errors", 0)),
                                    "temp_c": float(nv_log.get("temperature", temp_c) or temp_c),
                                    "critical_warning": str(nv_log.get("critical_warning") or ""),
                                }
                    except Exception:
                        pass

            eff_temp = round(float(temp_c or smart.get("temp_c", 0.0) or 0.0), 1)
            health_pct = smart.get("health_percent")
            media_err = int(smart.get("media_errors", 0) or 0)
            crit_warn = str(smart.get("critical_warning", "") or "")
            thr_temp = float(self.settings.get("nvme_temp_alert_c", 68.0) or 68.0)

            if media_err > 0 or crit_warn:
                badge, color = "ALERTA SMART", "#ff3b30"
            elif eff_temp >= thr_temp:
                badge, color = f"QUENTE ({eff_temp:.0f}°C)", "#ff9f0a"
            elif health_pct is None:
                badge, color = "ATIVO (SYSFS)", "#2ec5eb"
            elif health_pct >= 85:
                badge, color = "EXCELENTE", "#2fe08c"
            elif health_pct >= 65:
                badge, color = "SAUDÁVEL", "#00d2ff"
            elif health_pct >= 40:
                badge, color = "ATENÇÃO", "#ff9f0a"
            else:
                badge, color = "DESGASTE ALTO", "#ff3b30"

            results.append({
                "device": c_name,
                "model": model,
                "firmware": fw,
                "temp_c": eff_temp,
                "smart_available": bool(smart.get("smart_available", False)),
                "health_percent": health_pct,
                "wear_percent": smart.get("wear_percent"),
                "avail_spare_percent": smart.get("avail_spare_percent"),
                "tbw_tb": smart.get("tbw_tb", 0.0),
                "tbr_tb": smart.get("tbr_tb", 0.0),
                "power_on_hours": smart.get("power_on_hours", 0),
                "power_cycles": smart.get("power_cycles", 0),
                "unsafe_shutdowns": smart.get("unsafe_shutdowns", 0),
                "media_errors": media_err,
                "critical_warning": crit_warn,
                "badge": badge,
                "color": color,
            })

        self._cached_nvme_health = results
        self._last_nvme_health_scan = now
        return results

    def check_nvme_thermal_alert(self) -> Optional[Dict[str, str]]:
        """Dispara alerta térmico quando algum SSD NVMe atinge temperatura crítica (>= 68°C)."""
        if not self.features.nvme_health:
            return None
        thr = float(self.settings.get("nvme_temp_alert_c", 68.0) or 68.0)
        now = time.time()
        if (now - float(getattr(self, "_last_nvme_temp_alert_ts", 0.0))) < 300.0:
            return None
        for d in self.get_nvme_health_info(force=False):
            t = float(d.get("temp_c", 0.0) or 0.0)
            if t >= thr:
                self._last_nvme_temp_alert_ts = now
                return {
                    "title": f"Alerta Térmico do SSD ({t:.0f}°C)",
                    "message": (
                        f"O SSD {d['model'][:28]} ({d['device']}) atingiu {t:.1f}°C "
                        f"(Limite: {thr:.0f}°C). Verifique o fluxo de ar ou eleve a curva de ventoinhas."
                    ),
                    "urgency": "critical",
                }
        return None
