"""
Mixin de Recursos Inteligentes & Integração KDE Plasma 6 (core/mixins/smart_features.py):
- Bloqueio de Wake-on-USB (/sys/bus/usb/devices/*/power/wakeup)
- Detector de Thermal / Power Throttling em Tempo Real (CPU sysfs + NVIDIA)
- Modo Cinema / Apresentação (Inibidor de Suspensão + Não Perturbe KDE + Teclado Off)
- Presets de Áudio & Filtro de Ruído PipeWire (Normal / Call & Voz / Privacidade Total)
- Checkup Térmico Rápido (Baseline de 20s com comparação histórica)
- Regras Automáticas por Rede Wi-Fi (SSID)
- Perfil Noturno / Agendamento por Horário
- Top 5 Processos Consumidores de Energia / CPU
- Instalação do Widget KDE Plasma 6 (Plasmoid) e Plugin KRunner D-Bus
"""

import datetime
import glob
import os
import re
import shutil
import subprocess
import sys
import time
import psutil
from typing import Any, Dict, List, Optional, Tuple
from core.permissions import PermissionsManager


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
    # 7. Modo Cinema / Apresentação (Inibidor de Suspensão + DND KDE + Teclado Off)
    # =========================================================================
    def _set_kde_notifications_inhibited(self, inhibit: bool) -> None:
        plat = (os.environ.get("QT_QPA_PLATFORM") or "").lower()
        if plat in ("offscreen", "minimal"):
            return
        if not (os.environ.get("DBUS_SESSION_BUS_ADDRESS") and (shutil.which("qdbus6") or shutil.which("qdbus"))):
            return
        qdbus_bin = "qdbus6" if shutil.which("qdbus6") else "qdbus"
        if inhibit:
            if getattr(self, "_cinema_dnd_cookie", None):
                return
            try:
                res = subprocess.run(
                    [
                        qdbus_bin,
                        "org.freedesktop.Notifications",
                        "/org/freedesktop/Notifications",
                        "org.freedesktop.Notifications.Inhibit",
                        "ducksvantage",
                        "Modo Cinema / Apresentacao",
                        "{}",
                    ],
                    capture_output=True, text=True, timeout=1.5
                )
                if res.returncode == 0 and res.stdout.strip().isdigit():
                    self._cinema_dnd_cookie = int(res.stdout.strip())
            except Exception:
                pass
        else:
            cookie = getattr(self, "_cinema_dnd_cookie", None)
            if not cookie:
                return
            self._cinema_dnd_cookie = None
            try:
                subprocess.run(
                    [
                        qdbus_bin,
                        "org.freedesktop.Notifications",
                        "/org/freedesktop/Notifications",
                        "org.freedesktop.Notifications.UnInhibit",
                        str(cookie),
                    ],
                    capture_output=True, text=True, timeout=1.5
                )
            except Exception:
                pass

    def get_cinema_mode(self) -> bool:
        return bool(getattr(self, "_cinema_mode_active", False))

    def set_cinema_mode(self, enable: bool) -> Tuple[bool, str]:
        """Ativa/desativa o Modo Cinema (impede descanso de tela/suspensão, ativa DND e apaga teclado)."""
        target = bool(enable)
        if target:
            proc = getattr(self, "_cinema_inhibit_proc", None)
            if proc is None or proc.poll() is not None:
                plat = (os.environ.get("QT_QPA_PLATFORM") or "").lower()
                if plat not in ("offscreen", "minimal"):
                    cmd = None
                    if shutil.which("kde-inhibit"):
                        cmd = ["kde-inhibit", "--power", "--screenSaver", "sleep", "infinity"]
                    elif shutil.which("systemd-inhibit"):
                        cmd = [
                            "systemd-inhibit",
                            "--what=idle:sleep",
                            "--who=Ducksvantage",
                            "--why=Modo Cinema / Apresentacao",
                            "sleep", "infinity",
                        ]
                    if cmd:
                        try:
                            self._cinema_inhibit_proc = subprocess.Popen(
                                cmd,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                start_new_session=True,
                            )
                        except Exception:
                            self._cinema_inhibit_proc = None

            self._set_kde_notifications_inhibited(True)

            if self.features.kbd_backlight:
                cur_kbd = self.get_kbd_backlight()
                self._pre_cinema_kbd = cur_kbd
                if cur_kbd > 0:
                    self.set_kbd_backlight(0)

            self._cinema_mode_active = True
            self.settings.set("cinema_mode_active", True)
            return True, "Modo Cinema ativado: tela mantida acesa, notificações silenciadas (DND) e teclado apagado."

        proc = getattr(self, "_cinema_inhibit_proc", None)
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=1.5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            self._cinema_inhibit_proc = None

        self._set_kde_notifications_inhibited(False)

        prev_kbd = getattr(self, "_pre_cinema_kbd", None)
        self._pre_cinema_kbd = None
        if prev_kbd is not None and prev_kbd > 0 and self.features.kbd_backlight:
            self.set_kbd_backlight(int(prev_kbd))

        self._cinema_mode_active = False
        self.settings.set("cinema_mode_active", False)
        return True, "Modo Cinema desativado e estado padrão restaurado."

    # =========================================================================
    # 8. Presets de Áudio & Filtro de Ruído PipeWire (wpctl / pactl)
    # =========================================================================
    def _unload_pipewire_echo_cancel(self) -> None:
        mod_id = getattr(self, "_pw_echo_module_id", None)
        if mod_id is not None and shutil.which("pactl"):
            try:
                subprocess.run(
                    ["pactl", "unload-module", str(mod_id)],
                    capture_output=True, text=True, timeout=2
                )
            except Exception:
                pass
        self._pw_echo_module_id = None

    def get_audio_preset(self) -> str:
        val = str(self.settings.get("audio_preset", "normal") or "normal").strip().lower()
        return val if val in ("normal", "voice_call", "privacy_mute") else "normal"

    def set_audio_preset(self, preset_id: str) -> Tuple[bool, str]:
        """
        Aplica preset de áudio PipeWire/PulseAudio:
        - 'normal': desmuta áudio e microfone, desativa módulo echo-cancel temporário e restaura câmera.
        - 'voice_call': desmuta, ajusta ganho do mic (85%) e carrega cancelamento de eco/ruído WebRTC se disponível.
        - 'privacy_mute': silencia microfone + alto-falantes e fecha obturador eletrônico da câmera se suportado.
        """
        pid = str(preset_id or "normal").strip().lower()
        if pid not in ("normal", "voice_call", "privacy_mute"):
            return False, f"Preset de áudio inválido: {preset_id}"

        wpctl = shutil.which("wpctl")
        pactl = shutil.which("pactl")
        if not (wpctl or pactl):
            return False, "Utilitário de áudio PipeWire (wpctl / pactl) não encontrado."

        prev_preset = self.get_audio_preset()
        if prev_preset == "privacy_mute" and pid != "privacy_mute":
            prev_cam = getattr(self, "_pre_privacy_camera", None)
            self._pre_privacy_camera = None
            if prev_cam is True and self.features.camera_power:
                self.set_camera_power(True)

        if pid != "voice_call":
            self._unload_pipewire_echo_cancel()

        ok_any = False
        if pid == "normal":
            if wpctl:
                r1 = subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"], capture_output=True, timeout=2)
                r2 = subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "0"], capture_output=True, timeout=2)
                ok_any = (r1.returncode == 0 or r2.returncode == 0)
            elif pactl:
                r1 = subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], capture_output=True, timeout=2)
                r2 = subprocess.run(["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "0"], capture_output=True, timeout=2)
                ok_any = (r1.returncode == 0 or r2.returncode == 0)
            self.settings.set("audio_preset", "normal")
            return (True, "Áudio Padrão: alto-falantes e microfone ativos.") if ok_any else (False, "Falha ao comunicar com PipeWire.")

        if pid == "voice_call":
            if wpctl:
                r1 = subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"], capture_output=True, timeout=2)
                r2 = subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "0"], capture_output=True, timeout=2)
                subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SOURCE@", "0.85"], capture_output=True, timeout=2)
                ok_any = (r1.returncode == 0 or r2.returncode == 0)
            elif pactl:
                r1 = subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], capture_output=True, timeout=2)
                r2 = subprocess.run(["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "0"], capture_output=True, timeout=2)
                ok_any = (r1.returncode == 0 or r2.returncode == 0)

            echo_note = ""
            if pactl and getattr(self, "_pw_echo_module_id", None) is None:
                try:
                    res_ec = subprocess.run(
                        ["pactl", "load-module", "module-echo-cancel", "aec_method=webrtc", "source_name=ducksvantage_clean_mic"],
                        capture_output=True, text=True, timeout=2
                    )
                    if res_ec.returncode == 0 and res_ec.stdout.strip().isdigit():
                        self._pw_echo_module_id = int(res_ec.stdout.strip())
                        echo_note = " + Filtro Anti-Eco ativo"
                except Exception:
                    pass
            self.settings.set("audio_preset", "voice_call")
            return (True, f"Call / Voz: mic calibrado em 85%{echo_note}.") if ok_any else (False, "Falha ao aplicar perfil Call / Voz.")

        # privacy_mute
        if self.features.camera_power:
            self._pre_privacy_camera = self.get_camera_power()
            if self._pre_privacy_camera:
                self.set_camera_power(False)

        if wpctl:
            r1 = subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"], capture_output=True, timeout=2)
            r2 = subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "1"], capture_output=True, timeout=2)
            ok_any = (r1.returncode == 0 or r2.returncode == 0)
        elif pactl:
            r1 = subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"], capture_output=True, timeout=2)
            r2 = subprocess.run(["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "1"], capture_output=True, timeout=2)
            ok_any = (r1.returncode == 0 or r2.returncode == 0)

        self.settings.set("audio_preset", "privacy_mute")
        cam_note = " + Câmera bloqueada" if self.features.camera_power else ""
        return (True, f"Silêncio & Privacidade: áudio e mic mutados{cam_note}.") if ok_any else (False, "Falha ao mutar dispositivos no PipeWire.")

    def cycle_audio_preset(self) -> Tuple[bool, str, str]:
        """Cicla entre Padrão -> Call & Voz -> Privacidade Total."""
        order = ("normal", "voice_call", "privacy_mute")
        cur = self.get_audio_preset()
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "voice_call"
        ok, msg = self.set_audio_preset(nxt)
        return ok, nxt, msg

    # =========================================================================
    # 9. Checkup Térmico Rápido (Baseline de 20s para Ventoinhas & Pasta Térmica)
    # =========================================================================
    def get_thermal_checkup_history(self) -> List[Dict[str, Any]]:
        raw = self.settings.get("thermal_checkup_history", [])
        if not isinstance(raw, list):
            return []
        return [dict(item) for item in raw if isinstance(item, dict)]

    def clear_thermal_checkup_history(self) -> None:
        self.settings.set("thermal_checkup_history", [])

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

    def start_thermal_checkup(self, duration_sec: int = 20, spawn_load: bool = True) -> Tuple[bool, str]:
        """Inicia um mini stress controlado de 20s para medir e comparar eficiência térmica."""
        self.cancel_thermal_checkup()
        dur = max(5, min(60, int(duration_sec)))
        cpu_m = self.get_cpu_metrics()
        self._read_rapl_package_watts()

        procs: List[Any] = []
        if spawn_load:
            workers = min(4, max(1, (os.cpu_count() or 2) // 2 or 1))
            code_snippet = (
                f"import time; end=time.time()+{dur + 2}\n"
                "x=0\n"
                "while time.time()<end:\n"
                "    x=(x+1)*3 % 1000003\n"
            )
            for _ in range(workers):
                try:
                    p = subprocess.Popen(
                        [sys.executable, "-c", code_snippet],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    procs.append(p)
                except Exception:
                    pass

        self._checkup_procs = procs
        self._checkup_state = {
            "running": True,
            "start_ts": time.time(),
            "duration_sec": dur,
            "start_temp_c": float(cpu_m.temperature_c),
            "profile": self.get_platform_profile(),
            "samples": [],
        }
        return True, f"Checkup térmico iniciado ({dur}s, {len(procs)} threads de carga)."

    def cancel_thermal_checkup(self) -> None:
        """Encerra processos do checkup térmico imediatamente sem registrar histórico."""
        procs = list(getattr(self, "_checkup_procs", []) or [])
        for p in procs:
            try:
                p.terminate()
                p.wait(timeout=1.0)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        self._checkup_procs = []
        st = getattr(self, "_checkup_state", None)
        if isinstance(st, dict):
            st["running"] = False

    def poll_thermal_checkup(self) -> Dict[str, Any]:
        """Coleta amostra instantânea do checkup ativo ou conclui comparando com a Baseline."""
        st = getattr(self, "_checkup_state", None)
        if not isinstance(st, dict) or not st.get("running"):
            return {"running": False, "completed": False}

        now = time.time()
        elapsed = max(0.0, now - float(st["start_ts"]))
        dur = int(st["duration_sec"])

        cpu = self.get_cpu_metrics()
        fan = self.get_fan_metrics()
        watts = self._read_rapl_package_watts()
        if watts <= 0.0:
            watts = round(max(5.0, float(cpu.pl1_w) * (max(10.0, cpu.usage_percent) / 100.0)), 1)

        sample = {
            "temp_c": float(cpu.temperature_c),
            "power_w": float(watts),
            "fan_rpm": int(max(fan.rpm, fan.second_rpm)),
        }
        samples: List[Dict[str, Any]] = st["samples"]
        samples.append(sample)

        temps = [s["temp_c"] for s in samples if s["temp_c"] > 0] or [cpu.temperature_c]
        powers = [s["power_w"] for s in samples if s["power_w"] > 0] or [watts]
        rpms = [s["fan_rpm"] for s in samples if s["fan_rpm"] > 0]

        peak_temp = round(max(temps), 1)
        avg_temp = round(sum(temps) / len(temps), 1)
        avg_power = round(sum(powers) / len(powers), 1)
        max_rpm = int(max(rpms)) if rpms else 0

        if elapsed < dur:
            pct = int(min(99, max(1, (elapsed / float(dur)) * 100.0)))
            return {
                "running": True,
                "completed": False,
                "progress_pct": pct,
                "elapsed_sec": round(elapsed, 1),
                "duration_sec": dur,
                "current_temp_c": round(cpu.temperature_c, 1),
                "peak_temp_c": peak_temp,
                "avg_power_w": avg_power,
                "max_fan_rpm": max_rpm,
            }

        # Checkup finalizado: para carga e compara contra Baseline histórica
        self.cancel_thermal_checkup()
        history = self.get_thermal_checkup_history()
        baseline = history[0] if history else None

        delta_temp = 0.0
        if baseline:
            delta_temp = round(peak_temp - float(baseline.get("peak_temp_c", peak_temp)), 1)
            if delta_temp <= 4.0:
                verdict = "REFRIGERAÇÃO SAUDÁVEL"
                summary = f"Pico {peak_temp:.1f}°C ({delta_temp:+.1f}°C vs baseline {baseline['peak_temp_c']:.1f}°C) • Dissipação dentro do esperado."
            elif delta_temp <= 7.5:
                verdict = "ATENÇÃO • LEVE PERDA"
                summary = f"Pico {peak_temp:.1f}°C (+{delta_temp:.1f}°C acima da baseline) • Observe fluxo de ar / poeira nas entradas."
            else:
                verdict = "LIMPEZA / PASTA RECOMENDADA"
                summary = f"Pico {peak_temp:.1f}°C (+{delta_temp:.1f}°C acima da baseline) • Possível acúmulo de poeira ou ressecamento térmico."
        else:
            verdict = "BASELINE REGISTRADA"
            summary = f"Referência inicial salva: Pico {peak_temp:.1f}°C @ {avg_power:.1f}W ({max_rpm} RPM)."

        entry = {
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "profile": str(st.get("profile", "balanced")),
            "duration_sec": dur,
            "start_temp_c": round(float(st.get("start_temp_c", 0.0)), 1),
            "avg_temp_c": avg_temp,
            "peak_temp_c": peak_temp,
            "avg_power_w": avg_power,
            "max_fan_rpm": max_rpm,
            "delta_vs_baseline_c": delta_temp,
            "verdict": verdict,
        }
        history.append(entry)
        history = history[-15:]
        self.settings.set("thermal_checkup_history", history)

        return {
            "running": False,
            "completed": True,
            "progress_pct": 100,
            "elapsed_sec": dur,
            "duration_sec": dur,
            "current_temp_c": round(cpu.temperature_c, 1),
            "peak_temp_c": peak_temp,
            "avg_temp_c": avg_temp,
            "avg_power_w": avg_power,
            "max_fan_rpm": max_rpm,
            "baseline_temp_c": float(baseline["peak_temp_c"]) if baseline else peak_temp,
            "delta_temp_c": delta_temp,
            "verdict": verdict,
            "summary": summary,
            "entry": entry,
        }

    # =========================================================================
    # 10. Regras Automáticas por Rede Wi-Fi (SSID)
    # =========================================================================
    def get_current_wifi_ssid(self, force: bool = False) -> str:
        """Retorna o SSID Wi-Fi conectado atualmente via nmcli ou iwgetid (cache 6s)."""
        now = time.time()
        last_t = getattr(self, "_last_wifi_ssid_scan", 0.0)
        cached = getattr(self, "_cached_wifi_ssid", None)
        if not force and cached is not None and (now - last_t < 6.0):
            return cached

        ssid = ""
        if shutil.which("nmcli"):
            try:
                res = subprocess.run(
                    ["nmcli", "-t", "-f", "TYPE,NAME", "connection", "show", "--active"],
                    capture_output=True, text=True, timeout=1.5
                )
                if res.returncode == 0 and res.stdout:
                    for line in res.stdout.splitlines():
                        if ":" in line:
                            ctype, cname = line.split(":", 1)
                            if "wireless" in ctype.lower() or "wifi" in ctype.lower():
                                ssid = cname.strip()
                                break
            except Exception:
                pass

        if not ssid and shutil.which("iwgetid"):
            try:
                res = subprocess.run(["iwgetid", "-r"], capture_output=True, text=True, timeout=1.0)
                if res.returncode == 0 and res.stdout.strip():
                    ssid = res.stdout.strip()
            except Exception:
                pass

        self._cached_wifi_ssid = ssid
        self._last_wifi_ssid_scan = now
        return ssid

    def get_wifi_power_rules(self) -> List[Dict[str, Any]]:
        raw = self.settings.get("wifi_power_rules", [])
        if not isinstance(raw, list):
            return []
        return [dict(item) for item in raw if isinstance(item, dict) and item.get("ssid")]

    def add_wifi_power_rule(
        self,
        ssid: str,
        profile: str = "balanced",
        eco_mode: bool = False,
        refresh_hz: int = 0,
    ) -> Tuple[bool, str]:
        clean_ssid = str(ssid or "").strip()
        if not clean_ssid:
            return False, "Informe o nome (SSID) da rede Wi-Fi."
        norm_prof = self.normalize_profile(profile)
        rules = self.get_wifi_power_rules()
        updated = False
        for item in rules:
            if str(item.get("ssid", "")).strip().lower() == clean_ssid.lower():
                item["ssid"] = clean_ssid
                item["profile"] = norm_prof
                item["eco_mode"] = bool(eco_mode)
                item["refresh_hz"] = int(refresh_hz or 0)
                item["enabled"] = True
                updated = True
                break
        if not updated:
            rules.append({
                "ssid": clean_ssid,
                "profile": norm_prof,
                "eco_mode": bool(eco_mode),
                "refresh_hz": int(refresh_hz or 0),
                "enabled": True,
            })
        self.settings.set("wifi_power_rules", rules)
        self._last_applied_wifi_ssid = None
        return True, f"Regra Wi-Fi '{clean_ssid}' {'atualizada' if updated else 'salva'}."

    def remove_wifi_power_rule(self, ssid: str) -> Tuple[bool, str]:
        clean = str(ssid or "").strip().lower()
        rules = [r for r in self.get_wifi_power_rules() if str(r.get("ssid", "")).strip().lower() != clean]
        self.settings.set("wifi_power_rules", rules)
        if (getattr(self, "_last_applied_wifi_ssid", "") or "").lower() == clean:
            self._last_applied_wifi_ssid = None
        return True, f"Regra Wi-Fi '{ssid}' removida."

    def toggle_wifi_power_rule(self, ssid: str, enabled: bool) -> None:
        clean = str(ssid or "").strip().lower()
        rules = self.get_wifi_power_rules()
        for r in rules:
            if str(r.get("ssid", "")).strip().lower() == clean:
                r["enabled"] = bool(enabled)
                break
        self.settings.set("wifi_power_rules", rules)
        self._last_applied_wifi_ssid = None

    def check_wifi_ssid_rules(self) -> Optional[Dict[str, Any]]:
        """Detecta mudança de SSID Wi-Fi e aplica automaticamente a regra associada (se sem jogo ativo)."""
        rules = [r for r in self.get_wifi_power_rules() if r.get("enabled", True)]
        if not rules:
            return None
        if self.get_active_game():
            return None

        cur_ssid = self.get_current_wifi_ssid()
        if not cur_ssid:
            self._last_applied_wifi_ssid = None
            return None

        last_ssid = getattr(self, "_last_applied_wifi_ssid", None)
        if last_ssid and last_ssid.lower() == cur_ssid.lower():
            return None

        match = next((r for r in rules if str(r.get("ssid", "")).strip().lower() == cur_ssid.lower()), None)
        self._last_applied_wifi_ssid = cur_ssid
        if not match:
            return None

        applied_parts: List[str] = []
        if match.get("eco_mode") and self.features.eco_travel:
            ok_eco, _ = self.set_eco_travel_mode(True)
            if ok_eco:
                applied_parts.append("Eco-Mode")
        elif self.features.platform_profile:
            prof = self.normalize_profile(str(match.get("profile", "balanced")))
            ok_p, _ = self.set_platform_profile(prof, allow_elevation=False)
            if ok_p:
                applied_parts.append(prof.upper())

        req_hz = int(match.get("refresh_hz", 0) or 0)
        if req_hz > 0 and self.features.refresh_rate:
            ok_hz, _ = self.set_refresh_rate(req_hz)
            if ok_hz:
                applied_parts.append(f"{req_hz} Hz")

        if not applied_parts:
            return None

        return {
            "type": "wifi_rule_applied",
            "ssid": cur_ssid,
            "summary": " • ".join(applied_parts),
        }

    # =========================================================================
    # 13. Perfil Noturno / Agendamento por Horário
    # =========================================================================
    def get_night_schedule_config(self) -> Dict[str, Any]:
        return {
            "enabled": bool(self.settings.get("night_schedule_enabled", False)),
            "start_time": str(self.settings.get("night_start_time", "23:00") or "23:00"),
            "end_time": str(self.settings.get("night_end_time", "07:00") or "07:00"),
            "profile": self.normalize_profile(str(self.settings.get("night_profile", "low-power") or "low-power")),
            "kbd_off": bool(self.settings.get("night_kbd_off", True)),
            "conservation": bool(self.settings.get("night_conservation", True)),
        }

    def set_night_schedule_config(
        self,
        enabled: bool,
        start_time: str = "23:00",
        end_time: str = "07:00",
        profile: str = "low-power",
        kbd_off: bool = True,
        conservation: bool = True,
    ) -> None:
        self.settings.set("night_schedule_enabled", bool(enabled))
        self.settings.set("night_start_time", str(start_time or "23:00"))
        self.settings.set("night_end_time", str(end_time or "07:00"))
        self.settings.set("night_profile", self.normalize_profile(profile))
        self.settings.set("night_kbd_off", bool(kbd_off))
        self.settings.set("night_conservation", bool(conservation))
        if not enabled:
            self._night_mode_active = False

    @staticmethod
    def is_time_in_night_window(now_hm: Tuple[int, int], start_str: str, end_str: str) -> bool:
        """Verifica se (hora, min) está na janela [start, end), inclusive cruzando a meia-noite."""
        def _to_mins(s: str, default_m: int) -> int:
            try:
                hh, mm = s.strip().split(":", 1)
                return (int(hh) % 24) * 60 + (int(mm) % 60)
            except Exception:
                return default_m

        cur_m = (int(now_hm[0]) % 24) * 60 + (int(now_hm[1]) % 60)
        s_m = _to_mins(start_str, 23 * 60)
        e_m = _to_mins(end_str, 7 * 60)
        if s_m == e_m:
            return False
        if s_m < e_m:
            return s_m <= cur_m < e_m
        return cur_m >= s_m or cur_m < e_m

    def check_night_schedule(self, now_dt: Optional[datetime.datetime] = None) -> Optional[Dict[str, Any]]:
        """Alterna automaticamente para o Perfil Noturno dentro do horário agendado."""
        cfg = self.get_night_schedule_config()
        if not cfg["enabled"] or not self.features.platform_profile:
            return None
        if self.get_active_game():
            return None

        now_obj = now_dt or datetime.datetime.now()
        in_window = self.is_time_in_night_window((now_obj.hour, now_obj.minute), cfg["start_time"], cfg["end_time"])
        currently_active = bool(getattr(self, "_night_mode_active", False))

        if in_window and not currently_active:
            self._pre_night_profile = self.get_platform_profile()
            self._pre_night_kbd = self.get_kbd_backlight() if self.features.kbd_backlight else None
            self._night_mode_active = True

            notes: List[str] = []
            ok_p, _ = self.set_platform_profile(cfg["profile"], allow_elevation=False)
            if ok_p:
                notes.append(cfg["profile"].upper())
            if cfg["kbd_off"] and self.features.kbd_backlight:
                if self.set_kbd_backlight(0)[0]:
                    notes.append("Teclado Off")
            if cfg["conservation"] and self.features.conservation_mode:
                if not self.get_conservation_mode() and self.set_conservation_mode(True)[0]:
                    notes.append("Conservação 80%")

            return {
                "type": "night_mode_entered",
                "profile": cfg["profile"],
                "summary": " • ".join(notes) if notes else cfg["profile"].upper(),
            }

        if not in_window and currently_active:
            self._night_mode_active = False
            prev_p = getattr(self, "_pre_night_profile", "balanced") or "balanced"
            self.set_platform_profile(prev_p, allow_elevation=False)
            prev_kbd = getattr(self, "_pre_night_kbd", None)
            self._pre_night_kbd = None
            if prev_kbd is not None and prev_kbd > 0 and self.features.kbd_backlight:
                self.set_kbd_backlight(int(prev_kbd))
            return {
                "type": "night_mode_exited",
                "profile": prev_p,
                "summary": f"Perfil restaurado: {prev_p.upper()}",
            }

        return None

    # =========================================================================
    # 14. Top 5 Processos Drenando Bateria / CPU
    # =========================================================================
    def get_top_power_processes(self, limit: int = 5, force: bool = False) -> List[Dict[str, Any]]:
        """Retorna os processos com maior consumo de CPU e estimativa proporcional em Watts."""
        now = time.time()
        last_t = getattr(self, "_last_top_procs_scan", 0.0)
        cached = getattr(self, "_cached_top_procs", None)
        if not force and cached is not None and (now - last_t < 4.0):
            return cached[:limit]

        proc_map: Dict[int, psutil.Process] = getattr(self, "_proc_cpu_map", None)
        if proc_map is None:
            proc_map = {}
            self._proc_cpu_map = proc_map

        ncores = max(1, psutil.cpu_count(logical=True) or 1)
        seen_pids = set()
        rows: List[Dict[str, Any]] = []

        try:
            for p in psutil.process_iter(["pid", "name", "memory_info"]):
                try:
                    pid = int(p.info["pid"])
                    pname = (p.info.get("name") or "").strip()
                    if not pname or pname.startswith("kworker") or pid == 0:
                        continue
                    seen_pids.add(pid)
                    tracked = proc_map.get(pid)
                    if tracked is None:
                        p.cpu_percent(interval=None)
                        proc_map[pid] = p
                        continue
                    raw_cpu = float(tracked.cpu_percent(interval=None) or 0.0)
                    cpu_pct = round(min(100.0, raw_cpu / float(ncores)), 1)
                    mem_info = p.info.get("memory_info")
                    ram_mb = round((mem_info.rss / (1024.0 * 1024.0)) if mem_info else 0.0, 0)
                    if cpu_pct <= 0.1 and ram_mb < 30.0:
                        continue
                    rows.append({
                        "pid": pid,
                        "name": pname,
                        "cpu_percent": cpu_pct,
                        "ram_mb": int(ram_mb),
                        "est_watts": 0.0,
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        except Exception:
            pass

        for old_pid in list(proc_map.keys()):
            if old_pid not in seen_pids:
                proc_map.pop(old_pid, None)

        rows.sort(key=lambda r: (r["cpu_percent"], r["ram_mb"]), reverse=True)
        top_rows = rows[:max(1, int(limit))]

        bat_w = 0.0
        try:
            bat = self.get_battery_info()
            if bat.available and not bat.ac_connected and bat.power_draw_w > 0:
                bat_w = float(bat.power_draw_w)
        except Exception:
            pass

        total_cpu = sum(r["cpu_percent"] for r in top_rows) or 1.0
        for r in top_rows:
            if bat_w > 0 and r["cpu_percent"] > 0:
                r["est_watts"] = round(bat_w * (r["cpu_percent"] / total_cpu) * 0.65, 1)
            else:
                r["est_watts"] = round(r["cpu_percent"] * 0.35, 1)

        self._cached_top_procs = top_rows
        self._last_top_procs_scan = now
        return top_rows

    # =========================================================================
    # 11 & 12. Instaladores KDE Plasma 6 (Plasmoid & KRunner D-Bus)
    # =========================================================================
    @staticmethod
    def get_plasmoid_source_dir() -> str:
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(repo_root, "plasmoid", "org.ducksvantage.plasmoid")

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
            "Comment=Perfis térmicos, Hz, Eco-Mode, Cinema e temperaturas no Lenovo\n"
            "Comment[pt_BR]=Perfis térmicos, Hz, Eco-Mode, Cinema e temperaturas no Lenovo\n"
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
        service_content = (
            "[D-BUS Service]\n"
            "Name=org.ducksvantage.Control\n"
            f"Exec={py_bin} {main_py} --minimized\n"
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
            return True, "Plugin KRunner ativado! Pressione Alt+Espaço e digite 'dv', 'max', 'eco' ou 'cinema'."
        except Exception as e:
            return False, f"Falha ao registrar plugin KRunner: {e}"
