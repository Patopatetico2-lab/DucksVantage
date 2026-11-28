"""Mixin de Auto-Switching por Jogo, VRR, Histórico de Sessões e Regras por Aplicativo."""

import datetime
import json
import os
import re
import shutil
import subprocess
import time
import psutil
from typing import Any, Dict, List, Optional, Tuple
from core.settings import DEFAULT_APP_POWER_RULES


class GamingAutoSwitchMixin:
    """Detecção de jogos, sessões de jogo, App Rules e daemon de auto-switch."""

    # =========================================================================
    # ELITE 2: Auto-Switching Inteligente por Jogo (Steam / Heroic / Proton)
    # =========================================================================
    def get_game_auto_switch(self) -> bool:
        return bool(self.settings.get("game_auto_switch", True))

    def set_game_auto_switch(self, enable: bool) -> None:
        self.settings.set("game_auto_switch", bool(enable))
        if not enable:
            if self._active_game_name:
                self._restore_active_game_side_effects()
            self._active_game_name = None
            self._active_rule_exec = None
            self._pre_game_refresh_hz = None
            self._pre_game_turbo = None
            self._pre_game_tdp = None
            self._pre_game_fan_curve = None
            self._pre_game_vrr_policy = None
            self._game_changed_refresh = False
            self._game_changed_turbo = False
            self._game_changed_tdp = False
            self._game_changed_fan_curve = False
            self._game_changed_vrr = False
            self._game_changed_wifi = False
            self._pre_game_wifi_ps = None
            self._game_locked_touchpad = False
            self._game_session_start_ts = 0.0
            self._game_peak_cpu_c = 0.0
            self._game_peak_gpu_c = 0.0
            self._game_power_sum_w = 0.0
            self._game_power_samples = 0

    def _restore_active_game_side_effects(self) -> Tuple[bool, List[str]]:
        """Restaura perfil, governor e ajustes extras aplicados durante jogo/regra ativa."""
        restore_prof = self._pre_game_profile or "balanced"
        if restore_prof in ("performance", "max-power"):
            restore_prof = "balanced" if self._get_ac_online() == 1 else "low-power"

        ok_restore, _ = self.set_platform_profile(restore_prof, allow_elevation=False)
        if self.features.cpu_governor:
            avail_g = self.get_available_cpu_governors()
            prev_gov = getattr(self, "_pre_game_governor", "") or "powersave"
            if prev_gov not in avail_g:
                prev_gov = "powersave" if "powersave" in avail_g else (avail_g[0] if avail_g else "powersave")
            self.set_cpu_governor(prev_gov, allow_elevation=False)

        extras: List[str] = []
        if self._game_changed_turbo:
            prev_tb = self._pre_game_turbo
            self._game_changed_turbo = False
            self._pre_game_turbo = None
            if prev_tb is not None and self.features.turbo_boost:
                self.set_cpu_turbo(prev_tb, allow_elevation=False)

        if self._game_changed_tdp:
            prev_tdp = self._pre_game_tdp
            self._game_changed_tdp = False
            self._pre_game_tdp = None
            if prev_tdp is not None and self.features.custom_tdp:
                self.set_cpu_tdp_limits(prev_tdp[0], prev_tdp[1], allow_elevation=False)

        if getattr(self, "_game_changed_fan_curve", False):
            prev_fc = getattr(self, "_pre_game_fan_curve", None)
            self._game_changed_fan_curve = False
            self._pre_game_fan_curve = None
            if isinstance(prev_fc, dict) and self.features.fan_control:
                self.set_custom_fan_curve(
                    prev_fc.get("points", []),
                    bool(prev_fc.get("enabled", False)),
                    prev_fc.get("cpu_temp_limit"),
                    prev_fc.get("gpu_temp_limit"),
                )

        if self._game_changed_refresh:
            prev_hz = self._pre_game_refresh_hz
            self._game_changed_refresh = False
            self._pre_game_refresh_hz = None
            if prev_hz:
                try:
                    ok_rhz, _ = self.set_refresh_rate(prev_hz)
                    if ok_rhz:
                        extras.append(f"{prev_hz} Hz")
                except Exception:
                    pass

        if self._game_locked_touchpad:
            self._game_locked_touchpad = False
            try:
                ok_rtp, _ = self.set_touchpad_status(False, allow_elevation=False)
                if ok_rtp:
                    extras.append("Touchpad Liberado")
            except Exception:
                pass

        if getattr(self, "_game_changed_vrr", False):
            prev_vrr = getattr(self, "_pre_game_vrr_policy", None)
            self._game_changed_vrr = False
            self._pre_game_vrr_policy = None
            if prev_vrr:
                try:
                    self.set_vrr_policy(prev_vrr)
                except Exception:
                    pass

        if getattr(self, "_game_changed_wifi", False):
            prev_wifi_ps = getattr(self, "_pre_game_wifi_ps", None)
            self._game_changed_wifi = False
            self._pre_game_wifi_ps = None
            if prev_wifi_ps is not None:
                try:
                    ok_rwf, _ = self.set_wifi_power_saving(bool(prev_wifi_ps), allow_elevation=False)
                    if ok_rwf:
                        extras.append("Wi-Fi Eco")
                except Exception:
                    pass

        return ok_restore, extras

    def get_game_target_profile(self) -> str:
        """Retorna o perfil térmico preferido ao detectar jogos ('performance' ou 'max-power')."""
        raw = str(self.settings.get("game_target_profile", "max-power") or "max-power")
        norm = self.normalize_profile(raw)
        supported = self.get_supported_canonical_profiles()
        if supported:
            if norm in supported:
                return norm
            if "performance" in supported:
                return "performance"
            if "max-power" in supported:
                return "max-power"
            return supported[-1]
        return norm if norm in ("performance", "max-power") else "performance"

    def set_game_target_profile(self, profile: str) -> None:
        norm = self.normalize_profile(profile)
        if norm not in ("performance", "max-power"):
            norm = "performance"
        self.settings.set("game_target_profile", norm)

    def get_game_auto_refresh_max(self) -> bool:
        return bool(self.settings.get("game_auto_refresh_max", False))

    def set_game_auto_refresh_max(self, enable: bool) -> None:
        self.settings.set("game_auto_refresh_max", bool(enable))

    def get_game_auto_lock_touchpad(self) -> bool:
        return bool(self.settings.get("game_auto_lock_touchpad", False))

    def set_game_auto_lock_touchpad(self, enable: bool) -> None:
        self.settings.set("game_auto_lock_touchpad", bool(enable))

    def get_game_auto_wifi_low_latency(self) -> bool:
        return bool(self.settings.get("game_auto_wifi_low_latency", False))

    def set_game_auto_wifi_low_latency(self, enable: bool) -> None:
        self.settings.set("game_auto_wifi_low_latency", bool(enable))

    def get_game_target_preset_id(self) -> str:
        return str(self.settings.get("game_target_preset_id", "") or "").strip()

    def set_game_target_preset_id(self, preset_id: str) -> None:
        self.settings.set("game_target_preset_id", str(preset_id or "").strip())

    # -------------------------------------------------------------------------
    # VRR em Jogos & Histórico Persistente de Sessões
    # -------------------------------------------------------------------------
    def get_game_vrr_policy(self) -> str:
        val = str(self.settings.get("game_vrr_policy", "keep") or "keep").strip().lower()
        return val if val in ("keep", "automatic", "always", "never") else "keep"

    def set_game_vrr_policy(self, policy: str) -> None:
        val = str(policy or "keep").strip().lower()
        if val not in ("keep", "automatic", "always", "never"):
            val = "keep"
        self.settings.set("game_vrr_policy", val)

    def get_game_session_history(self) -> List[Dict[str, Any]]:
        """Retorna o histórico persistente das últimas sessões de jogo registradas."""
        raw = self.settings.get("game_session_history", [])
        if not isinstance(raw, list):
            return []
        return [dict(item) for item in raw if isinstance(item, dict)]

    def clear_game_session_history(self) -> None:
        self.settings.set("game_session_history", [])

    def get_game_ignore_list(self) -> List[str]:
        raw = self.settings.get("game_ignore_list", [])
        if not isinstance(raw, list):
            return []
        return [str(x).strip().lower() for x in raw if str(x).strip()]

    def add_game_ignore_item(self, name: str) -> Tuple[bool, str]:
        clean = " ".join((name or "").split()).strip().lower()
        if not clean:
            return False, "Informe o executável ou termo a ignorar (ex: launcher.exe, java)."
        items = self.get_game_ignore_list()
        if clean in items:
            return False, f"'{clean}' já está na lista de exclusões."
        items.append(clean)
        self.settings.set("game_ignore_list", items)
        self._cached_running_game = None
        self._last_game_scan_time = 0.0
        return True, f"'{clean}' adicionado às exclusões."

    def remove_game_ignore_item(self, name: str) -> Tuple[bool, str]:
        clean = (name or "").strip().lower()
        items = [x for x in self.get_game_ignore_list() if x != clean]
        self.settings.set("game_ignore_list", items)
        self._cached_running_game = None
        self._last_game_scan_time = 0.0
        return True, f"'{clean}' removido das exclusões."

    def update_game_session_peaks(self, cpu_temp: float, gpu_temp: float, power_w: float = 0.0) -> None:
        """Atualiza os picos térmicos e consumo médio registrados durante a sessão de jogo ativa."""
        if not self._active_game_name or self._active_rule_exec or self._game_session_start_ts <= 0:
            return
        if cpu_temp > self._game_peak_cpu_c:
            self._game_peak_cpu_c = float(cpu_temp)
        if gpu_temp > self._game_peak_gpu_c:
            self._game_peak_gpu_c = float(gpu_temp)
        if power_w > 0:
            self._game_power_sum_w = float(getattr(self, "_game_power_sum_w", 0.0)) + float(power_w)
            self._game_power_samples = int(getattr(self, "_game_power_samples", 0)) + 1

    def detect_running_game(self, force: bool = False) -> Optional[str]:
        """
        Monitora processos ativos em busca de jogos abertos via Steam (Proton/Nativo),
        Heroic Games Launcher, Lutris, Wine/UMU, Sober (Roblox), Emuladores, Gamescope ou GameMode.
        Aplica cache seguro de 4s para evitar micro-travamentos (stutters) na interface.
        """
        now = time.time()
        if not force and (now - self._last_game_scan_time < 4.0):
            return self._cached_running_game

        ignored_bins = {
            "steam", "steamwebhelper", "steamservice", "steam-runtime",
            "steam-runtime-launch-client", "steam-runtime-launcher-service",
            "steam-runtime-launcher-interface-0", "steam-runtime-supervisor",
            "steam-launch-wrapper", "_v2-entry-point", "srt-logger",
            "heroic", "lutris", "wineserver", "services.exe", "winedevice.exe",
            "explorer.exe", "plugplay.exe", "svchost.exe", "rpcss.exe",
            "lsass.exe", "csrss.exe", "smss.exe", "wininit.exe", "winlogon.exe",
            "spoolsv.exe", "dwm.exe", "fontdrvhost.exe", "sihost.exe",
            "taskhostw.exe", "ctfmon.exe", "dllhost.exe", "audiodg.exe",
            "searchindexer.exe", "wmiprvse.exe",
            "vcredist_x64.exe", "vcredist_x86.exe", "vc_redist.x64.exe", "vc_redist.x86.exe",
            "dxsetup.exe", "dotnetfx35.exe",
            "tabtip.exe", "conhost.exe", "start.exe", "wineboot.exe",
            "rundll32.exe", "msiexec.exe", "regsvr32.exe", "regedit.exe",
            "cmd.exe", "taskmgr.exe", "steam.exe", "steamwebhelper.exe",
            "epicgameslauncher.exe", "epicwebhelper.exe", "eadesktop.exe",
            "ealauncher.exe", "eabackgroundservice.exe", "upc.exe",
            "ubisoftconnect.exe", "battle.net.exe", "agent.exe",
            "galaxyclient.exe", "crashhandler", "crashhandler64",
            "crashhandler.exe", "crashhandler64.exe",
            "unitycrashhandler64.exe", "ue4prereqsetup_x64.exe",
            "pressure-vessel", "bwrap", "srt-bwrap", "xdg-dbus-proxy",
            "fossilize_replay", "gamemoded", "proton", "umu-run",
            "python", "python3", "bash", "sh", "zsh", "fish",
        }
        user_ignored = set(self.get_game_ignore_list())
        ignored_bins.update(user_ignored)

        def _is_ignored_bin(bin_low: str) -> bool:
            return (
                bin_low in ignored_bins
                or bin_low.startswith(("_v2-entry", "steam-runtime-", "srt-", "pv-", "pressure-vessel"))
            )

        runtime_wrappers = {
            "wine", "wine64", "wine-preloader", "wine64-preloader",
            "sniper", "soldier", "pv-adverb", "pressure-vessel-wrap",
            "reaper",
        }
        native_games = {
            "rpcs3", "pcsx2", "pcsx2-qt", "dolphin-emu", "yuzu", "ryujinx",
            "cemu", "retroarch", "cs2", "dota2", "hl2_linux", "factorio",
            "stardewvalley", "terraria", "celeste", "osu!", "veloren-voxygen",
            "supertuxkart", "xonotic-linux64-glx",
        }
        lib_markers = (
            "/steamapps/common/", "/games/heroic/", "/heroic/prefixes/",
            "/games/", "/lutris/", "/epic games/", "/gog games/", "/compatdata/",
        )

        found_game = None
        saw_gamemoded = False
        try:
            for proc in psutil.process_iter(["name", "exe", "cmdline", "cwd"]):
                try:
                    pname = (proc.info.get("name") or "").strip()
                    p_low = pname.lower()
                    if p_low == "gamemoded":
                        saw_gamemoded = True
                    if not pname or _is_ignored_bin(p_low):
                        continue

                    exe_str = (proc.info.get("exe") or "").strip()
                    exe_low = exe_str.lower()
                    cwd_str = (proc.info.get("cwd") or "").strip()
                    cmdline = proc.info.get("cmdline") or []
                    cmd_str = " ".join(cmdline)
                    cmd_low = cmd_str.lower()

                    # 1. Steam Reaper com AppId (ex: reaper SteamLaunch AppId=... -- .../_v2-entry-point -- .../Game.exe)
                    if p_low == "reaper" and "appid=" in cmd_low:
                        m = re.search(r"appid=(\d+)", cmd_low)
                        app_id = m.group(1) if m else "Steam"
                        tail_args = cmdline[cmdline.index("--") + 1:] if "--" in cmdline else cmdline
                        wrapper_tokens = {"waitforexitandrun", "run", "run-in-container", "verb", "--"}
                        best_bin = None
                        for raw_a in reversed(tail_args):
                            norm_a = raw_a.replace("\\", "/").strip()
                            if not norm_a or norm_a.startswith("-") or "=" in norm_a:
                                continue
                            if "/windows/system32/" in norm_a.lower() or "/windows/syswow64/" in norm_a.lower():
                                continue
                            cand_b = os.path.basename(norm_a)
                            c_low = cand_b.lower()
                            if (
                                not cand_b
                                or c_low in wrapper_tokens
                                or c_low in runtime_wrappers
                                or _is_ignored_bin(c_low)
                            ):
                                continue
                            if c_low.endswith((".exe", ".x86_64", ".bin")) or ("/" in norm_a):
                                best_bin = cand_b
                                break
                        if best_bin:
                            found_game = f"{best_bin} (Steam #{app_id})"
                        else:
                            found_game = f"Steam Game (AppID {app_id})"
                        break

                    # 2. Gamescope ou GameModeRun ativo
                    if p_low in ("gamescope", "gamemoderun"):
                        found_game = f"Sessão {pname}"
                        break

                    # 3. Jogos Flatpak (Sober/Roblox), Minecraft e Emuladores/Nativos conhecidos
                    if p_low == "sober" or "/app/bin/sober" in cmd_low or exe_low.endswith("/sober"):
                        found_game = "Roblox (Sober)"
                        break
                    if p_low in ("java", "javaw") and any(k in cmd_low for k in ("net.minecraft", "minecraft", "prismlauncher", "mojang", "fabricmc")):
                        found_game = "Minecraft"
                        break
                    if p_low in native_games:
                        found_game = pname
                        break

                    # 4. Executáveis rodando a partir de bibliotecas de jogos (Steam, Heroic, Lutris, ~/Games, etc.)
                    exe_norm = exe_str.replace("\\", "/").lower()
                    cmd_norm = cmd_str.replace("\\", "/").lower()
                    cwd_norm = cwd_str.replace("\\", "/").lower()
                    if any(m in txt for m in lib_markers for txt in (cmd_norm, exe_norm, cwd_norm)):
                        for arg in reversed(cmdline):
                            arg_norm = arg.replace("\\", "/")
                            if "/windows/system32/" in arg_norm.lower() or "/windows/syswow64/" in arg_norm.lower():
                                continue
                            clean_arg = os.path.basename(arg_norm)
                            c_low = clean_arg.lower()
                            if c_low.endswith((".exe", ".x86_64", ".bin")) and not _is_ignored_bin(c_low) and c_low not in runtime_wrappers:
                                found_game = clean_arg
                                break
                        if not found_game and p_low not in runtime_wrappers:
                            cand_bin = os.path.basename(exe_norm) if exe_str else pname
                            if not _is_ignored_bin(cand_bin.lower()) and cand_bin.lower() not in runtime_wrappers:
                                found_game = os.path.basename(exe_str.replace("\\", "/")) or pname
                        if found_game:
                            break

                    # 5. Executável Windows .exe rodando via Wine / Proton / UMU (ex: C:\Games\...)
                    is_wine_proc = p_low.endswith(".exe") or "wine" in p_low or "wine" in exe_low or "proton" in cmd_low or "umu" in cmd_low
                    if is_wine_proc:
                        cmd_norm_w = cmd_low.replace("\\", "/")
                        for arg in reversed(cmdline):
                            arg_norm = arg.replace("\\", "/")
                            arg_low = arg_norm.lower()
                            if "/windows/system32/" in arg_low or "/windows/syswow64/" in arg_low:
                                continue
                            clean_arg = os.path.basename(arg_norm)
                            c_low = clean_arg.lower()
                            if c_low.endswith(".exe") and not _is_ignored_bin(c_low) and c_low not in runtime_wrappers:
                                found_game = clean_arg
                                break
                        if (
                            not found_game
                            and p_low.endswith(".exe")
                            and not _is_ignored_bin(p_low)
                            and "/windows/system32/" not in cmd_norm_w
                            and "/windows/syswow64/" not in cmd_norm_w
                        ):
                            found_game = pname
                        if found_game:
                            break
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        except Exception:
            pass

        # 6. Fallback Feral GameMode via D-Bus (caso gamemoded esteja ativo com algum cliente)
        if not found_game and saw_gamemoded and shutil.which("gdbus"):
            try:
                res = subprocess.run(
                    [
                        "gdbus", "call", "--session",
                        "--dest", "com.feralinteractive.GameMode",
                        "--object-path", "/com/feralinteractive/GameMode",
                        "--method", "org.freedesktop.DBus.Properties.Get",
                        "com.feralinteractive.GameMode", "ClientCount",
                    ],
                    capture_output=True, text=True, timeout=0.5,
                )
                if res.returncode == 0 and res.stdout:
                    m_cnt = re.search(r"(\d+)", res.stdout)
                    if m_cnt and int(m_cnt.group(1)) > 0:
                        found_game = "GameMode (Jogo Ativo)"
            except Exception:
                pass

        if found_game and user_ignored and any(ig in found_game.lower() for ig in user_ignored):
            found_game = None

        self._cached_running_game = found_game
        self._last_game_scan_time = now
        return found_game

    # =========================================================================
    # Gerenciador de Perfis de Energia por Aplicativo (App Rules) + Auto-Switching
    # =========================================================================
    def get_app_power_rules(self) -> List[Dict[str, Any]]:
        """Retorna a lista de regras de perfil de energia por executável/aplicativo."""
        rules = self.settings.get("app_power_rules", DEFAULT_APP_POWER_RULES)
        if not isinstance(rules, list):
            rules = json.loads(json.dumps(DEFAULT_APP_POWER_RULES)) if "json" in globals() else list(DEFAULT_APP_POWER_RULES)
        return rules

    def add_app_power_rule(
        self, executable: str, profile: str, label: str = "", preset_id: str = ""
    ) -> Tuple[bool, str]:
        """Adiciona ou atualiza uma regra de perfil/preset de energia vinculada a um executável."""
        clean_exec = os.path.basename(executable.strip()).lower()
        if not clean_exec:
            return False, "Informe o nome do executável (ex: blender, resolve, firefox)."
        norm_prof = self.normalize_profile(profile)
        clean_preset = str(preset_id or "").strip()
        target_desc = self.get_profile_info(norm_prof)["short_title"]
        if clean_preset:
            p_obj = next((p for p in self.get_user_presets() if p.get("id") == clean_preset), None)
            if p_obj:
                target_desc = f"Preset: {p_obj['name']}"
                if p_obj.get("profile"):
                    norm_prof = self.normalize_profile(str(p_obj["profile"]))
        clean_label = label.strip() or f"{clean_exec} ({target_desc})"
        rules = list(self.get_app_power_rules())
        updated = False
        for item in rules:
            if str(item.get("executable", "")).lower() == clean_exec:
                item["profile"] = norm_prof
                item["preset_id"] = clean_preset
                item["label"] = clean_label
                item["enabled"] = True
                updated = True
                break
        if not updated:
            rules.append({
                "executable": clean_exec,
                "label": clean_label,
                "profile": norm_prof,
                "preset_id": clean_preset,
                "enabled": True,
            })
        self.settings.set("app_power_rules", rules)
        return True, f"Regra '{clean_exec}' -> {target_desc} salva com sucesso."

    def remove_app_power_rule(self, executable: str) -> Tuple[bool, str]:
        clean_exec = os.path.basename(executable.strip()).lower()
        rules = [r for r in self.get_app_power_rules() if str(r.get("executable", "")).lower() != clean_exec]
        self.settings.set("app_power_rules", rules)
        if self._active_rule_exec == clean_exec:
            self._active_rule_exec = None
            self._active_game_name = None
        return True, f"Regra '{clean_exec}' removida."

    def toggle_app_power_rule(self, executable: str, enabled: bool) -> Tuple[bool, str]:
        clean_exec = os.path.basename(executable.strip()).lower()
        rules = list(self.get_app_power_rules())
        for item in rules:
            if str(item.get("executable", "")).lower() == clean_exec:
                item["enabled"] = bool(enabled)
                break
        self.settings.set("app_power_rules", rules)
        if not enabled and self._active_rule_exec == clean_exec:
            self._active_rule_exec = None
            self._active_game_name = None
        return True, f"Regra '{clean_exec}' {'ativada' if enabled else 'desativada'}."

    def get_running_user_processes(self) -> List[str]:
        """Lista executáveis de usuário em execução para facilitar o preenchimento na UI."""
        system_ignore = {
            "systemd", "kthreadd", "init", "bash", "sh", "zsh", "fish", "python", "python3",
            "dbus-daemon", "kwin_wayland", "kwin_x11", "plasmashell", "xwayland", "pipewire",
            "wireplumber", "xdg-desktop-portal", "polkitd", "udev", "agetty", "sudo", "pkexec"
        }
        found = set()
        try:
            uid = os.getuid()
            for proc in psutil.process_iter(["name", "uids"]):
                try:
                    uids = proc.info.get("uids")
                    if uids and uids.real != uid:
                        continue
                    pname = (proc.info.get("name") or "").strip()
                    if pname and len(pname) >= 3 and pname.lower() not in system_ignore and not pname.startswith("kworker"):
                        found.add(pname)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        except Exception:
            pass
        return sorted(found)[:40]

    def detect_running_app_rule(self, force: bool = False) -> Optional[Dict[str, str]]:
        """Verifica se algum processo em execução corresponde a uma regra ativa de App Rules com cache seguro de 4s."""
        now = time.time()
        if not force and (now - self._last_app_rule_scan_time < 4.0):
            return self._cached_running_app_rule

        rules = [r for r in self.get_app_power_rules() if r.get("enabled", True) and r.get("executable")]
        if not rules:
            self._cached_running_app_rule = None
            self._last_app_rule_scan_time = now
            return None

        # Priorizar regras de maior desempenho caso múltiplos apps estejam abertos
        priority_order = {"max-power": 4, "performance": 3, "balanced": 2, "low-power": 1}
        rules.sort(key=lambda r: priority_order.get(self.normalize_profile(r.get("profile", "balanced")), 2), reverse=True)

        rule_map = {str(r["executable"]).lower(): r for r in rules}
        matched_rules = []

        try:
            for proc in psutil.process_iter(["name", "exe"]):
                try:
                    pname = (proc.info.get("name") or "").strip().lower()
                    exe_base = os.path.basename(proc.info.get("exe") or "").strip().lower()
                    if pname in rule_map:
                        matched_rules.append(rule_map[pname])
                    elif exe_base and exe_base in rule_map:
                        matched_rules.append(rule_map[exe_base])
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        except Exception:
            pass

        if not matched_rules:
            self._cached_running_app_rule = None
            self._last_app_rule_scan_time = now
            return None

        best = max(
            matched_rules,
            key=lambda r: priority_order.get(self.normalize_profile(r.get("profile", "balanced")), 2)
        )
        res = {
            "executable": str(best.get("executable", "")).lower(),
            "label": str(best.get("label") or best.get("executable")),
            "profile": self.normalize_profile(str(best.get("profile", "performance"))),
            "preset_id": str(best.get("preset_id", "") or "").strip(),
        }
        self._cached_running_app_rule = res
        self._last_app_rule_scan_time = now
        return res

    def check_game_auto_switch(self) -> Optional[Dict[str, Any]]:
        """
        Verifica se um jogo (Steam/Heroic/Proton) ou um aplicativo mapeado no App Rules
        foi aberto ou fechado e aplica automaticamente o perfil de energia correspondente.
        """
        if not self.get_game_auto_switch() or not self.features.platform_profile:
            return None

        # 1. Verificar Jogos (Steam / Heroic / Proton / Gamescope)
        detected_game = self.detect_running_game()
        detected_rule = None if detected_game else self.detect_running_app_rule()

        target_name: Optional[str] = None
        target_prof: Optional[str] = None
        rule_exec: Optional[str] = None

        target_preset: Optional[Dict[str, Any]] = None
        if detected_game:
            target_name = detected_game
            pref_preset_id = self.get_game_target_preset_id()
            if pref_preset_id:
                target_preset = next((p for p in self.get_user_presets() if p.get("id") == pref_preset_id), None)
            if target_preset and target_preset.get("profile"):
                target_prof = self.normalize_profile(str(target_preset["profile"]))
            else:
                choices = self.get_platform_profile_choices()
                pref_target = self.get_game_target_profile()
                if pref_target in choices:
                    target_prof = pref_target
                elif pref_target == "max-power" and "max-power" in choices:
                    target_prof = "max-power"
                elif "performance" in choices:
                    target_prof = "performance"
                elif "max-power" in choices:
                    target_prof = "max-power"
                else:
                    target_prof = pref_target
        elif detected_rule:
            target_name = f"{detected_rule['label']}"
            target_prof = detected_rule["profile"]
            rule_exec = detected_rule["executable"]
            rule_pid = str(detected_rule.get("preset_id", "") or "").strip()
            if rule_pid:
                target_preset = next((p for p in self.get_user_presets() if p.get("id") == rule_pid), None)
                if target_preset and target_preset.get("profile"):
                    target_prof = self.normalize_profile(str(target_preset["profile"]))

        # Novo jogo ou aplicativo mapeado iniciou (ou mudou de regra ativa)
        if target_name and target_name != self._active_game_name:
            if not self._active_game_name:
                self._pre_game_profile = self.get_platform_profile()
                self._pre_game_governor = self.get_cpu_governor()

            self._active_game_name = target_name
            self._active_rule_exec = rule_exec
            if not rule_exec:
                self._game_session_start_ts = time.time()
                self._game_peak_cpu_c = 0.0
                self._game_peak_gpu_c = 0.0
                self._game_power_sum_w = 0.0
                self._game_power_samples = 0

            extras: List[str] = []
            ok_prof = False

            if target_preset is not None:
                # Salva estados extras antes de aplicar o preset vinculado (Jogo ou App Rule)
                if "turbo_enabled" in target_preset and self.features.turbo_boost and not self._game_changed_turbo:
                    self._pre_game_turbo = self.get_cpu_turbo()
                    self._game_changed_turbo = True
                if "pl1_w" in target_preset and "pl2_w" in target_preset and self.features.custom_tdp and not self._game_changed_tdp:
                    self._pre_game_tdp = self.get_cpu_tdp_limits()
                    self._game_changed_tdp = True
                if "fan_curve_enabled" in target_preset and self.features.fan_control and not getattr(self, "_game_changed_fan_curve", False):
                    self._pre_game_fan_curve = self.get_custom_fan_curve()
                    self._game_changed_fan_curve = True
                if "refresh_hz" in target_preset and self.features.refresh_rate and not self._game_changed_refresh:
                    try:
                        ref_cur = self.get_display_refresh_info()
                        if ref_cur.available and int(target_preset["refresh_hz"]) != ref_cur.current_hz:
                            self._pre_game_refresh_hz = ref_cur.current_hz
                            self._game_changed_refresh = True
                    except Exception:
                        pass

                ok_pre, _ = self.apply_user_preset(str(target_preset["id"]), allow_elevation=False)
                ok_prof = ok_pre
                if not ok_pre:
                    self._game_changed_turbo = False
                    self._pre_game_turbo = None
                    self._game_changed_tdp = False
                    self._pre_game_tdp = None
                    self._game_changed_fan_curve = False
                    self._pre_game_fan_curve = None
                    self._game_changed_refresh = False
                    self._pre_game_refresh_hz = None
                else:
                    extras.append(f"Preset: {target_preset['name']}")
            else:
                ok_prof, _ = self.set_platform_profile(target_prof or "performance", allow_elevation=False)
                if self.features.cpu_governor:
                    gov = "performance" if target_prof in ("performance", "max-power") else "powersave"
                    self.set_cpu_governor(gov, allow_elevation=False)

            if not rule_exec:
                # 1. Eleva taxa de atualização para a máxima suportada ao iniciar jogo (se ainda não alterada pelo preset)
                if self.get_game_auto_refresh_max() and self.features.refresh_rate and not self._game_changed_refresh:
                    try:
                        ref_info = self.get_display_refresh_info()
                        if ref_info.available and len(ref_info.available_rates) > 1:
                            max_hz = max(ref_info.available_rates)
                            if ref_info.current_hz < max_hz:
                                self._pre_game_refresh_hz = ref_info.current_hz
                                ok_hz, _ = self.set_refresh_rate(max_hz)
                                if ok_hz:
                                    self._game_changed_refresh = True
                                    extras.append(f"{max_hz} Hz")
                                else:
                                    self._pre_game_refresh_hz = None
                    except Exception:
                        pass

                # 2. Bloqueia o touchpad durante o jogo (somente se não estava bloqueado antes)
                if self.get_game_auto_lock_touchpad() and self.features.touchpad_control and not self._game_locked_touchpad:
                    try:
                        if not self.get_touchpad_status():
                            ok_tp, _ = self.set_touchpad_status(True, allow_elevation=False)
                            if ok_tp:
                                self._game_locked_touchpad = True
                                extras.append("Touchpad Bloqueado")
                    except Exception:
                        pass

                # 3. VRR (Adaptive Sync) automático durante o jogo
                pref_vrr = self.get_game_vrr_policy()
                if pref_vrr != "keep" and self.features.refresh_rate and not getattr(self, "_game_changed_vrr", False):
                    try:
                        ref_vrr = self.get_display_refresh_info()
                        if ref_vrr.vrr_supported and ref_vrr.vrr_policy != pref_vrr:
                            self._pre_game_vrr_policy = ref_vrr.vrr_policy
                            ok_vrr, _ = self.set_vrr_policy(pref_vrr)
                            if ok_vrr:
                                self._game_changed_vrr = True
                                extras.append(f"VRR:{pref_vrr}")
                            else:
                                self._pre_game_vrr_policy = None
                    except Exception:
                        pass

                # 4. Baixa Latência no Wi-Fi (Power Save OFF) durante jogos sem elevar privilégio
                if (
                    self.get_game_auto_wifi_low_latency()
                    and self.features.wifi_power_save
                    and not getattr(self, "_game_changed_wifi", False)
                ):
                    try:
                        net_st = self.get_network_power_status(force=True)
                        if net_st.wifi_available and net_st.wifi_power_save_on:
                            ok_wf, _ = self.set_wifi_power_saving(False, allow_elevation=False)
                            if ok_wf:
                                self._pre_game_wifi_ps = True
                                self._game_changed_wifi = True
                                extras.append("Wi-Fi Baixa Latência")
                    except Exception:
                        pass

            return {
                "type": "app_rule_started" if rule_exec else "game_started",
                "game": target_name,
                "executable": rule_exec or "",
                "profile": target_prof or "performance",
                "applied": ok_prof,
                "extras": extras,
            }

        # Jogo ou aplicativo mapeado fechou
        if not target_name and self._active_game_name:
            finished_game = self._active_game_name
            was_rule_exec = bool(self._active_rule_exec)
            self._active_game_name = None
            self._active_rule_exec = None

            session_summary = None
            if not was_rule_exec and self._game_session_start_ts > 0:
                dur_s = max(0, int(round(time.time() - self._game_session_start_ts)))
                p_samples = int(getattr(self, "_game_power_samples", 0) or 0)
                p_sum = float(getattr(self, "_game_power_sum_w", 0.0) or 0.0)
                avg_w = round(p_sum / p_samples, 1) if p_samples > 0 else 0.0
                session_summary = {
                    "duration_sec": dur_s,
                    "peak_cpu_c": round(self._game_peak_cpu_c, 1),
                    "peak_gpu_c": round(self._game_peak_gpu_c, 1),
                    "avg_power_w": avg_w,
                }
                if dur_s >= 30:
                    hist = self.get_game_session_history()
                    hist.append({
                        "timestamp": datetime.datetime.now().strftime("%d/%m %H:%M"),
                        "game": finished_game,
                        "duration_sec": dur_s,
                        "peak_cpu_c": round(self._game_peak_cpu_c, 1),
                        "peak_gpu_c": round(self._game_peak_gpu_c, 1),
                        "avg_power_w": avg_w,
                        "profile": str(self.get_platform_profile()),
                    })
                    self.settings.set("game_session_history", hist[-30:])
            self._game_session_start_ts = 0.0
            self._game_peak_cpu_c = 0.0
            self._game_peak_gpu_c = 0.0
            self._game_power_sum_w = 0.0
            self._game_power_samples = 0

            ok_restore, extras = self._restore_active_game_side_effects()
            restore_prof = self.get_platform_profile()

            return {
                "type": "game_stopped",
                "game": finished_game,
                "profile": restore_prof,
                "applied": ok_restore,
                "extras": extras,
                "session_summary": session_summary,
            }

        return None

    def get_active_game(self) -> Optional[str]:
        return self._active_game_name

