"""
Gerenciamento de Permissões e Regras UDEV para o Ducksvantage (core/permissions.py).
Permite que o usuário aplique configurações de hardware (/sys/) em qualquer notebook Lenovo
sem precisar de senha root contínua (incluindo Custom TDP PL1/PL2, Eco-Mode D3cold e Copilot Key).
"""

import os
import glob
import shutil
import subprocess
from typing import Tuple, List

UDEV_RULE_PATH = "/etc/udev/rules.d/99-ducksvantage.rules"
LEGACY_UDEV_RULE_PATH = "/etc/udev/rules.d/99-lenovo-loq-control.rules"

UDEV_RULE_CONTENT = """# ====================================================================
# Ducksvantage - Regras UDEV Universais Lenovo (Legion, LOQ, IdeaPad, Yoga)
# Permite escrita nos nós de ACPI, CPU, TDP, GPU D3cold, Teclado e Bateria
# ====================================================================

# 1. Perfil de Plataforma ACPI (Quiet, Balanced, Performance, Max-Power)
ACTION=="add|change", SUBSYSTEM=="acpi", RUN+="/bin/sh -c 'chmod 0666 /sys/firmware/acpi/platform_profile 2>/dev/null || true'"
ACTION=="add|change", SUBSYSTEM=="platform", RUN+="/bin/sh -c 'chmod 0666 /sys/firmware/acpi/platform_profile 2>/dev/null || true'"

# 2. Driver Universal Lenovo Ideapad ACPI (VPC*)
ACTION=="add|change", SUBSYSTEM=="platform", KERNEL=="VPC*", RUN+="/bin/sh -c 'chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/conservation_mode /sys/bus/platform/drivers/ideapad_acpi/VPC*/fn_lock /sys/bus/platform/drivers/ideapad_acpi/VPC*/camera_power /sys/bus/platform/drivers/ideapad_acpi/VPC*/usb_charging /sys/bus/platform/drivers/ideapad_acpi/VPC*/fan_mode 2>/dev/null || true'"

# 3. Modos de Carregamento da Bateria (Rapid Charge / Long Life)
ACTION=="add|change", SUBSYSTEM=="power_supply", RUN+="/bin/sh -c 'chmod 0666 /sys/class/power_supply/BAT*/charge_types 2>/dev/null || true'"

# 4. Retroiluminação do Teclado (Kbd Backlight)
ACTION=="add|change", SUBSYSTEM=="leds", RUN+="/bin/sh -c 'chmod 0666 /sys/class/leds/*kbd_backlight*/brightness 2>/dev/null || true'"

# 5. Controle de CPU Turbo Boost (Intel P-State / AMD CPUFreq) e Scaling Governor
ACTION=="add|change", SUBSYSTEM=="cpu", RUN+="/bin/sh -c 'chmod 0666 /sys/devices/system/cpu/intel_pstate/no_turbo /sys/devices/system/cpu/cpufreq/boost /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor 2>/dev/null || true'"

# 6. Limites de TDP Customizados (Intel RAPL PL1 / PL2) e Suspensão D3cold PCI
ACTION=="add|change", SUBSYSTEM=="powercap", RUN+="/bin/sh -c 'chmod 0666 /sys/class/powercap/intel-rapl*/constraint_*_power_limit_uw 2>/dev/null || true'"
ACTION=="add|change", SUBSYSTEM=="pci", RUN+="/bin/sh -c 'chmod 0666 /sys/bus/pci/devices/*/power/control 2>/dev/null || true'"

# 7. Leitura de Eventos de Teclas Especiais (Tecla Copilot F23 / WMI Hotkeys)
ACTION=="add|change", SUBSYSTEM=="input", RUN+="/bin/sh -c 'chmod 0644 /dev/input/by-path/*kbd* /dev/input/by-path/*VPC* 2>/dev/null || true'"

# 8. Atributos Térmicos e de Potência Lenovo WMI Other (CPU/GPU Temp Limits, AC Offset, PPT) e Hwmon PWM
ACTION=="add|change", SUBSYSTEM=="firmware-attributes", RUN+="/bin/sh -c 'chmod 0666 /sys/class/firmware-attributes/lenovo-wmi-other-*/attributes/*/current_value 2>/dev/null || true'"
ACTION=="add|change", SUBSYSTEM=="hwmon", RUN+="/bin/sh -c 'chmod 0666 /sys/class/hwmon/hwmon*/pwm* /sys/class/hwmon/hwmon*/fan*_target 2>/dev/null || true'"

# 9. Controle de Economia de Energia de Rede (Wi-Fi / Ethernet PCIe Runtime PM)
ACTION=="add|change", SUBSYSTEM=="net", RUN+="/bin/sh -c 'chmod 0666 /sys/class/net/*/device/power/control 2>/dev/null || true'"
"""


class PermissionsManager:
    """Gerencia checagem de permissões e instalação de regras udev do Ducksvantage."""

    @staticmethod
    def is_writable(path: str) -> bool:
        if not path or not os.path.exists(path):
            return False
        return os.access(path, os.W_OK)

    @staticmethod
    def check_system_permissions(paths: List[str]) -> Tuple[bool, List[str]]:
        missing = []
        for p in paths:
            if p and os.path.exists(p) and not os.access(p, os.W_OK):
                missing.append(p)
        return (len(missing) == 0, missing)

    @staticmethod
    def is_udev_rule_installed() -> bool:
        return os.path.exists(UDEV_RULE_PATH) or os.path.exists(LEGACY_UDEV_RULE_PATH)

    @staticmethod
    def get_udev_rule_content() -> str:
        return UDEV_RULE_CONTENT

    @staticmethod
    def install_udev_rules(custom_paths: List[str] = None) -> Tuple[bool, str]:
        temp_file = "/tmp/99-ducksvantage.rules"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(UDEV_RULE_CONTENT)
        except Exception as e:
            return False, f"Falha ao criar arquivo temporário: {e}"

        cmd_parts = [
            f"cp {temp_file} {UDEV_RULE_PATH}",
            f"chmod 644 {UDEV_RULE_PATH}",
            "udevadm control --reload-rules",
            "udevadm trigger",
            "chmod 0666 /sys/firmware/acpi/platform_profile 2>/dev/null || true",
            "chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/conservation_mode 2>/dev/null || true",
            "chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/fn_lock 2>/dev/null || true",
            "chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/camera_power 2>/dev/null || true",
            "chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/usb_charging 2>/dev/null || true",
            "chmod 0666 /sys/class/power_supply/BAT*/charge_types 2>/dev/null || true",
            "chmod 0666 /sys/class/leds/*kbd_backlight*/brightness 2>/dev/null || true",
            "chmod 0666 /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null || true",
            "chmod 0666 /sys/devices/system/cpu/cpufreq/boost 2>/dev/null || true",
            "chmod 0666 /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor 2>/dev/null || true",
            "chmod 0666 /sys/class/powercap/intel-rapl*/constraint_*_power_limit_uw 2>/dev/null || true",
            "chmod 0666 /sys/bus/pci/devices/*/power/control 2>/dev/null || true",
            "chmod 0644 /dev/input/by-path/*kbd* /dev/input/by-path/*VPC* 2>/dev/null || true",
        ]

        if custom_paths:
            for p in custom_paths:
                if p:
                    cmd_parts.append(f"chmod 0666 '{p}' 2>/dev/null || true")

        full_cmd = " && ".join(cmd_parts)

        runner = None
        if shutil.which("pkexec"):
            runner = ["pkexec", "sh", "-c", full_cmd]
        elif shutil.which("kdesu"):
            runner = ["kdesu", "-c", full_cmd]
        else:
            return False, "Nenhum gerenciador de privilégios gráficos (pkexec ou kdesu) encontrado."

        try:
            res = subprocess.run(runner, capture_output=True, text=True, timeout=60)
            if res.returncode == 0:
                return True, "Regras UDEV instaladas e permissões liberadas imediatamente!"
            return False, f"Erro ao aplicar regras (código {res.returncode}): {res.stderr or res.stdout}"
        except Exception as e:
            return False, f"Exceção durante execução do pkexec: {e}"

    @staticmethod
    def write_sysfs_value(path: str, value: str) -> Tuple[bool, str]:
        if not path or not os.path.exists(path):
            return False, f"Caminho sysfs inexistente: {path}"

        clean_val = str(value).strip()

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(clean_val)
            return True, "Aplicado com sucesso."
        except PermissionError:
            pass
        except Exception as e:
            return False, f"Erro de escrita em {path}: {e}"

        if shutil.which("pkexec"):
            try:
                cmd = f"echo '{clean_val}' > '{path}' && chmod 0666 '{path}'"
                res = subprocess.run(["pkexec", "sh", "-c", cmd], capture_output=True, text=True, timeout=30)
                if res.returncode == 0:
                    return True, "Aplicado via elevação Polkit (permissão liberada para a sessão)."
                return False, f"Elevação cancelada ou recusada: {res.stderr.strip()}"
            except Exception as e:
                return False, f"Falha ao executar pkexec: {e}"

        return False, f"Permissão negada em {path}. Clique em 'Reparar Permissões UDEV' na aba Sobre."

    @staticmethod
    def write_multiple_sysfs_values(pairs: List[Tuple[str, str]]) -> Tuple[bool, str]:
        """Escreve múltiplos valores sysfs em uma única operação (ex: PL1 + PL2 RAPL)."""
        valid_pairs = [(p, str(v).strip()) for p, v in pairs if p and os.path.exists(p)]
        if not valid_pairs:
            return False, "Nenhum nó sysfs válido encontrado para escrita."

        need_pkexec = False
        for path, val in valid_pairs:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(val)
            except PermissionError:
                need_pkexec = True
                break
            except Exception as e:
                return False, f"Erro de escrita em {path}: {e}"

        if not need_pkexec:
            return True, "Limites aplicados diretamente no kernel."

        if shutil.which("pkexec"):
            try:
                cmds = [f"echo '{val}' > '{path}' && chmod 0666 '{path}'" for path, val in valid_pairs]
                res = subprocess.run(["pkexec", "sh", "-c", " && ".join(cmds)], capture_output=True, text=True, timeout=30)
                if res.returncode == 0:
                    return True, "Limites aplicados via Polkit e liberados para a sessão."
                return False, f"Elevação recusada: {res.stderr.strip()}"
            except Exception as e:
                return False, f"Falha no pkexec: {e}"

        return False, "Sem permissão de escrita nos nós de potência. Repare as regras UDEV na aba Sobre."

    @staticmethod
    def write_cpu_governor_all(governor: str) -> Tuple[bool, str]:
        gov_files = sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor"))
        if not gov_files:
            return False, "Interface cpufreq/scaling_governor não encontrada neste kernel."

        clean_gov = governor.strip()
        try:
            for gf in gov_files:
                with open(gf, "w", encoding="utf-8") as f:
                    f.write(clean_gov)
            return True, f"Governor '{clean_gov}' aplicado em {len(gov_files)} threads."
        except PermissionError:
            pass
        except Exception as e:
            return False, f"Erro ao alterar governor: {e}"

        if shutil.which("pkexec"):
            try:
                cmd = (
                    f"for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do "
                    f"echo '{clean_gov}' > \"$f\"; chmod 0666 \"$f\"; done"
                )
                res = subprocess.run(["pkexec", "sh", "-c", cmd], capture_output=True, text=True, timeout=30)
                if res.returncode == 0:
                    return True, f"Governor '{clean_gov}' aplicado em todos os núcleos."
                return False, f"Elevação cancelada: {res.stderr.strip()}"
            except Exception as e:
                return False, f"Falha no pkexec: {e}"

        return False, "Sem permissão para alterar o CPU Governor. Repare as regras UDEV na aba Sobre."
