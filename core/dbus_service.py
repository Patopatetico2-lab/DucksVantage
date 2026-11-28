"""
Serviço D-Bus de Sessão & Integração KRunner (core/dbus_service.py).
Expõe `org.ducksvantage.Control` para automação no KDE Plasma 6 e busca direta no KRunner (Alt+Espaço).
"""

import json
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    HAS_DBUS_SERVICE = True
except ImportError:
    dbus = None
    dbus_service = None
    DBusGMainLoop = None
    HAS_DBUS_SERVICE = False


DBUS_BUS_NAME = "org.ducksvantage.Control"
DBUS_CONTROL_PATH = "/org/ducksvantage/Control"
DBUS_CONTROL_IFACE = "org.ducksvantage.Control"
DBUS_KRUNNER_PATH = "/KRunner"
DBUS_KRUNNER_IFACE = "org.kde.krunner1"


class DucksvantageCommandRouter:
    """Roteador puro (agnóstico de D-Bus) para comandos remotos, status JSON e consultas KRunner."""

    def __init__(self, backend, ui_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None):
        self.backend = backend
        self.ui_callback = ui_callback

    def _notify_ui(self, event_name: str, payload: Dict[str, Any]) -> None:
        if callable(self.ui_callback):
            try:
                self.ui_callback(event_name, payload)
            except Exception:
                pass

    def get_status_dict(self) -> Dict[str, Any]:
        """Retorna telemetria resumida atual compatível com Plasma/KRunner/scripts."""
        cpu = self.backend.get_cpu_metrics()
        gpu = self.backend.get_gpu_metrics()
        bat = self.backend.get_battery_info()
        ref = self.backend.get_display_refresh_info()
        return {
            "model": self.backend.system_info.display_model_name,
            "profile": self.backend.get_platform_profile(),
            "active_game": self.backend.get_active_game(),
            "eco_mode": self.backend.get_eco_travel_mode(),
            "cpu": {"temp_c": cpu.temperature_c, "freq_mhz": cpu.frequency_mhz, "governor": cpu.governor},
            "gpu": {"available": gpu.available, "temp_c": gpu.temperature_c, "power_w": gpu.power_draw_w, "state": gpu.runtime_state},
            "battery": {
                "available": bat.available,
                "percent": bat.capacity_percent,
                "status": bat.status,
                "ac": bat.ac_connected,
                "one_time_full_charge": self.backend.get_one_time_full_charge_status()["active"],
            },
            "display": {"available": ref.available, "hz": ref.current_hz, "vrr": ref.vrr_policy},
        }

    def execute_command(self, cmd_id: str) -> Tuple[bool, str]:
        """Executa ação nomeada (`profile:X`, `preset:X`, `cycle_profile`, `cycle_hz`, `eco_toggle`, etc.)."""
        cmd = str(cmd_id or "").strip()
        low = cmd.lower()

        if low.startswith("profile:"):
            prof = low.split(":", 1)[1].strip()
            ok, msg = self.backend.set_platform_profile(prof, allow_elevation=False)
            if ok:
                self._notify_ui("profile", {"profile": self.backend.get_platform_profile()})
            return ok, msg

        if low.startswith("preset:"):
            pid = cmd.split(":", 1)[1].strip()
            presets = self.backend.get_user_presets()
            p_obj = next((p for p in presets if p.get("id") == pid), None)
            pname = p_obj["name"] if p_obj else pid
            ok, msg = self.backend.apply_user_preset(pid, allow_elevation=False)
            if ok:
                self._notify_ui("preset", {"id": pid, "name": pname, "summary": msg})
            return ok, msg

        if low == "cycle_profile":
            ok, new_prof = self.backend.cycle_next_profile()
            if ok:
                self._notify_ui("profile", {"profile": new_prof})
            return ok, f"Perfil: {new_prof}"

        if low == "cycle_hz":
            ok, hz, msg = self.backend.cycle_refresh_rate()
            if ok:
                self._notify_ui("refresh_rate", {"hz": hz})
            return ok, msg

        if low == "eco_toggle":
            new_st = not self.backend.get_eco_travel_mode()
            ok, msg = self.backend.set_eco_travel_mode(new_st)
            if ok:
                self._notify_ui("eco", {"enabled": new_st})
            return ok, msg

        if low == "full_charge_once":
            st = self.backend.get_one_time_full_charge_status()
            if st["active"]:
                ok, msg = self.backend.cancel_one_time_full_charge(restore_conservation=True)
                if ok:
                    self._notify_ui("full_charge_once", {"active": False, "message": msg})
                return ok, msg
            ok, msg = self.backend.start_one_time_full_charge()
            if ok:
                self._notify_ui("full_charge_once", {"active": True, "message": msg})
            return ok, msg

        if low == "show_window":
            self._notify_ui("show_window", {})
            return True, "Janela aberta."

        return False, f"Comando desconhecido: {cmd_id}"

    def krunner_match(self, query: str) -> List[Tuple[str, str, str, int, float, Dict[str, Any]]]:
        """Gera correspondências para o KRunner (`Alt+Espaço` no KDE Plasma 6)."""
        q = str(query or "").strip().lower()
        if len(q) < 2:
            return []

        status = self.get_status_dict()
        cpu_t = status["cpu"]["temp_c"]
        gpu_obj = status["gpu"]
        gpu_txt = f"{gpu_obj['temp_c']:.0f}°C" if gpu_obj["available"] else gpu_obj["state"]
        prof_u = str(status["profile"]).upper()
        bat_obj = status["battery"]
        bat_txt = f" | Bat {bat_obj['percent']}%" if bat_obj["available"] else ""

        feat = self.backend.features
        supported_profs = set(self.backend.get_supported_canonical_profiles()) if feat.platform_profile else set()
        catalog: List[Tuple[str, str, str, str, List[str], float]] = [
            (
                "show_window",
                f"Ducksvantage: {prof_u} • CPU {cpu_t:.0f}°C | GPU {gpu_txt}{bat_txt}",
                "Abrir painel principal do Ducksvantage",
                "ducksvantage",
                ["dv", "duck", "ducksvantage", "vantage", "temp", "cpu", "gpu", "status"],
                0.95,
            ),
        ]
        if "low-power" in supported_profs:
            catalog.append((
                "profile:low-power",
                "Ducksvantage: Modo Silencioso (Low-Power)",
                "Reduz ruído das ventoinhas e economiza bateria",
                "ducksvantage",
                ["dv", "silencioso", "quiet", "low-power", "bateria", "silent"],
                0.85,
            ))
        if "balanced" in supported_profs:
            catalog.append((
                "profile:balanced",
                "Ducksvantage: Modo Equilibrado (Balanced)",
                "Ajuste automático pelo Embedded Controller Lenovo",
                "ducksvantage",
                ["dv", "equilibrado", "balanced", "normal"],
                0.82,
            ))
        if "performance" in supported_profs:
            catalog.append((
                "profile:performance",
                "Ducksvantage: Modo Desempenho (Performance)",
                "Libera envelope térmico para jogos e trabalho pesado",
                "ducksvantage",
                ["dv", "desempenho", "performance", "jogo", "game"],
                0.86,
            ))
        if "max-power" in supported_profs or feat.max_power_profile:
            catalog.append((
                "profile:max-power",
                "Ducksvantage: Desempenho Máximo (Max-Power)",
                "Potência máxima sustentada + ventoinhas no máximo",
                "ducksvantage",
                ["dv", "max", "max-power", "extremo", "turbo"],
                0.88,
            ))
        if feat.eco_travel:
            catalog.append((
                "eco_toggle",
                f"Ducksvantage: Alternar Modo Viagem ({'Ativo' if status['eco_mode'] else 'Desativado'})",
                "Eco-Mode Extremo 1-Clique",
                "ducksvantage",
                ["dv", "eco", "viagem", "travel"],
                0.84,
            ))
        if feat.refresh_rate and status["display"].get("available"):
            catalog.append((
                "cycle_hz",
                f"Ducksvantage: Alternar Taxa de Tela (Atual: {status['display']['hz']} Hz)",
                "Alterna frequência do painel",
                "ducksvantage",
                ["dv", "hz", "refresh", "tela", "60", "144", "display"],
                0.80,
            ))

        if self.backend.features.conservation_mode:
            ot_active = self.backend.get_one_time_full_charge_status()["active"]
            catalog.append((
                "full_charge_once",
                f"Ducksvantage: {'Cancelar Carga 100% Única' if ot_active else 'Carregar até 100% Só Hoje'}",
                "Desativa Conservação 80% temporariamente e reativa ao completar",
                "ducksvantage",
                ["dv", "100", "carga", "bateria", "full", "hoje"],
                0.83,
            ))

        for preset in self.backend.get_user_presets():
            pid = str(preset.get("id", ""))
            pname = str(preset.get("name", pid))
            summary = self.backend.format_user_preset_summary(preset)
            catalog.append((
                f"preset:{pid}",
                f"Ducksvantage Preset: {pname}",
                summary,
                "ducksvantage",
                ["dv", "preset", pname.lower(), pid.lower()],
                0.90,
            ))

        results: List[Tuple[str, str, str, int, float, Dict[str, Any]]] = []
        for cid, title, subtext, icon_name, kws, base_rel in catalog:
            matched = any(q in k for k in kws) or (q in title.lower()) or (q in subtext.lower())
            if not matched:
                continue
            exact = any(q == k for k in kws)
            m_type = 100 if exact else 50
            rel = min(1.0, base_rel + (0.05 if exact else 0.0))
            results.append((
                cid,
                title,
                icon_name,
                m_type,
                rel,
                {"subtext": subtext, "category": "Ducksvantage"},
            ))
        results.sort(key=lambda item: item[4], reverse=True)
        return results[:8]

    def krunner_run(self, match_id: str, action_id: str = "") -> Tuple[bool, str]:
        return self.execute_command(match_id)


if HAS_DBUS_SERVICE:

    class _ControlDBusObject(dbus.service.Object):
        def __init__(self, bus_name_obj, router: DucksvantageCommandRouter):
            super().__init__(bus_name_obj, DBUS_CONTROL_PATH)
            self.router = router

        @dbus.service.method(DBUS_CONTROL_IFACE, in_signature="", out_signature="s")
        def GetStatusJson(self) -> str:
            return json.dumps(self.router.get_status_dict(), ensure_ascii=False)

        @dbus.service.method(DBUS_CONTROL_IFACE, in_signature="s", out_signature="bs")
        def SetProfile(self, profile: str):
            ok, msg = self.router.execute_command(f"profile:{profile}")
            return bool(ok), str(msg)

        @dbus.service.method(DBUS_CONTROL_IFACE, in_signature="", out_signature="bs")
        def CycleProfile(self):
            ok, msg = self.router.execute_command("cycle_profile")
            return bool(ok), str(msg)

        @dbus.service.method(DBUS_CONTROL_IFACE, in_signature="s", out_signature="bs")
        def RunCommand(self, cmd_id: str):
            ok, msg = self.router.execute_command(cmd_id)
            return bool(ok), str(msg)

    class _KRunnerDBusObject(dbus.service.Object):
        def __init__(self, bus_name_obj, router: DucksvantageCommandRouter):
            super().__init__(bus_name_obj, DBUS_KRUNNER_PATH)
            self.router = router

        @dbus.service.method(DBUS_KRUNNER_IFACE, in_signature="", out_signature="a(sss)")
        def Actions(self):
            return dbus.Array([], signature="(sss)")

        @dbus.service.method(DBUS_KRUNNER_IFACE, in_signature="s", out_signature="a(sssida{sv})")
        def Match(self, query: str):
            out = []
            for cid, text, icon, mtype, rel, props in self.router.krunner_match(query):
                d_props = dbus.Dictionary(
                    {str(k): str(v) for k, v in props.items()},
                    signature="sv",
                )
                out.append((str(cid), str(text), str(icon), int(mtype), float(rel), d_props))
            return dbus.Array(out, signature="(sssida{sv})")

        @dbus.service.method(DBUS_KRUNNER_IFACE, in_signature="ss", out_signature="")
        def Run(self, match_id: str, action_id: str):
            self.router.krunner_run(str(match_id), str(action_id))

        @dbus.service.method(DBUS_KRUNNER_IFACE, in_signature="s", out_signature="")
        def SetActivationToken(self, _token: str):
            pass

        @dbus.service.method(DBUS_KRUNNER_IFACE, in_signature="", out_signature="a{sv}")
        def Config(self):
            return dbus.Dictionary({}, signature="sv")

        @dbus.service.method(DBUS_KRUNNER_IFACE, in_signature="", out_signature="")
        def Teardown(self):
            pass


class DucksvantageDBusService:
    """Gerencia o registro do serviço D-Bus de sessão sem quebrar ambientes headless/sem D-Bus."""

    def __init__(self, backend, ui_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None):
        self.router = DucksvantageCommandRouter(backend, ui_callback=ui_callback)
        self.active = False
        self._bus_name = None
        self._ctrl_obj = None
        self._krunner_obj = None

    def start(self) -> bool:
        plat = (os.environ.get("QT_QPA_PLATFORM") or "").lower()
        if plat in ("offscreen", "minimal"):
            return False
        if not HAS_DBUS_SERVICE or not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
            return False
        try:
            DBusGMainLoop(set_as_default=True)
            bus = dbus.SessionBus()
            self._bus_name = dbus.service.BusName(DBUS_BUS_NAME, bus=bus)
            self._ctrl_obj = _ControlDBusObject(self._bus_name, self.router)
            self._krunner_obj = _KRunnerDBusObject(self._bus_name, self.router)
            self.active = True
            return True
        except Exception:
            self.active = False
            return False

    def stop(self) -> None:
        for obj in (self._ctrl_obj, self._krunner_obj):
            if obj is not None:
                try:
                    obj.remove_from_connection()
                except Exception:
                    pass
        self._ctrl_obj = None
        self._krunner_obj = None
        self._bus_name = None
        self.active = False
