#!/usr/bin/env python3
"""
Script de Teste e Validação do Backend Universal do Ducksvantage.
Executa a varredura agnóstica do hardware e dos 6 Recursos de Elite sem precisar de interface gráfica.
"""

from core.backend import HardwareBackend
from core.permissions import PermissionsManager


def main():
    print("=" * 72)
    print("   Ducksvantage - Varredura Universal de Hardware Lenovo (Linux)")
    print("=" * 72)

    backend = HardwareBackend()
    sys_info = backend.system_info
    feat = backend.features

    # 1. Identificação Dinâmica DMI / BIOS
    print("\n[+] Identificação Dinâmica (DMI / BIOS):")
    print(f"    - Fabricante / Linha: {sys_info.sys_vendor} ({sys_info.laptop_line})")
    print(f"    - Painel Lateral:     {sys_info.edge_panel_title}")
    print(f"    - Modelo Detectado:   {sys_info.display_model_name} ({sys_info.product_name})")
    print(f"    - Placa-Mãe (Board):  {sys_info.board_name}")
    print(f"    - BIOS (Versão/Data): {sys_info.bios_version} ({sys_info.bios_date})")
    print(f"    - Kernel / OS:        {sys_info.kernel_version} ({sys_info.os_name})")
    print(f"    - Driver Ideapad:     {backend.paths.ideapad_dir}")

    # 2. Perfis Térmicos ACPI & Descoberta Dinâmica de 'max-power'
    current_prof = backend.get_platform_profile()
    choices = backend.get_platform_profile_choices()
    print("\n[+] Perfis Térmicos (ACPI platform_profile):")
    print(f"    - Perfil Ativo:       {current_prof.upper()}")
    print(f"    - Opções do Kernel:   {', '.join(choices)}")
    print(f"    - Suporte Max-Power:  {'SIM (Habilitado dinamicamente)' if feat.max_power_profile else 'NÃO'}")

    # 3. Processador (Intel / AMD), Turbo Boost, Governor e Custom TDP (PL1/PL2)
    cpu = backend.get_cpu_metrics()
    print("\n[+] Processador (CPU), Escalonamento & Limites TDP (RAPL):")
    print(f"    - Modelo ({cpu.vendor}):     {cpu.model_name}")
    print(f"    - Uso / Frequência:   {cpu.usage_percent:.1f}% @ {cpu.frequency_mhz:.0f} MHz ({cpu.cores_count} threads)")
    print(f"    - Temperatura:        {cpu.temperature_c:.1f} °C")
    print(f"    - Turbo Boost:        {'ATIVO' if cpu.turbo_enabled else 'DESATIVADO'} (Suportado: {cpu.turbo_supported})")
    print(f"    - Scaling Governor:   {cpu.governor} (Disponíveis: {', '.join(cpu.available_governors)})")
    print(f"    - Custom TDP (RAPL):  PL1 = {cpu.pl1_w} W (Long-Term) | PL2 = {cpu.pl2_w} W (Short-Term) [Suportado: {cpu.pl_supported}]")

    # 4. Placa Gráfica (NVIDIA / AMD Radeon / Intel)
    gpu = backend.get_gpu_metrics()
    print("\n[+] Placa Gráfica (GPU):")
    print(f"    - Modelo ({gpu.vendor}):    {gpu.name} [{gpu.short_name}]")
    print(f"    - Estado Runtime:     {gpu.runtime_state} ({gpu.pstate})")
    if gpu.available:
        print(f"    - Clock / Uso:        {gpu.clock_mhz} MHz | {gpu.utilization_percent}% uso")
        print(f"    - Temperatura / Pot.: {gpu.temperature_c:.1f} °C | {gpu.power_draw_w:.1f} W")
        print(f"    - VRAM:               {gpu.memory_used_mb} / {gpu.memory_total_mb} MB")

    # 5. Memória RAM e Armazenamento SSD NVMe/SATA
    ram = backend.get_ram_metrics()
    disks = backend.get_storage_devices()
    fan = backend.get_fan_metrics()
    print("\n[+] Memória RAM, Armazenamento & Refrigeração:")
    print(f"    - Memória RAM:        {ram.used_gb:.2f} / {ram.total_gb:.2f} GB ({ram.usage_percent:.1f}%) | Temp: {ram.temperature_c:.1f} °C")
    for d in disks:
        print(f"    - Disco ({d.device_name}):    {d.model} | {d.used_gb:.1f}/{d.total_gb:.1f} GB ({d.usage_percent:.1f}%) | Temp: {d.temperature_c:.1f} °C")
    print(f"    - Ventoinhas:         {fan.status_label}")

    # 6. Bateria, Alimentação e Battery Health Historian
    bat = backend.get_battery_info()
    hist = backend.get_battery_history()
    print("\n[+] Alimentação, Bateria & Battery Health Historian (/sys/class/power_supply/BAT*):")
    if bat.available:
        print(f"    - Carga / Status:     {bat.capacity_percent}% ({bat.status}) | AC: {'Conectado' if bat.ac_connected else 'Desconectado'}")
        print(f"    - Saúde (Full/Des.):  {bat.health_percent:.1f}% ({bat.energy_full_wh:.2f} / {bat.energy_design_wh:.2f} Wh)")
        print(f"    - Energia Atual:      {bat.energy_now_wh:.2f} Wh | Tensão: {bat.voltage_v:.2f} V | Taxa: {bat.power_draw_w:.2f} W")
        print(f"    - Ciclos / Célula:    {bat.cycle_count} ciclos ({bat.manufacturer} {bat.model_name} • {bat.technology})")
        print(f"    - Conservação (~80%): {'ATIVO' if bat.conservation_mode_active else 'DESATIVADO'} (Suportado: {feat.conservation_mode})")
        print(f"    - Rapid Charge:       {'ATIVO' if bat.rapid_charge_active else 'DESATIVADO'} (Suportado: {feat.rapid_charge})")
        print(f"    - Health Historian:   {len(hist)} snapshots registrados (Último: {hist[-1].energy_full_wh:.2f} Wh em {hist[-1].timestamp})")

    # 7. Recursos de Elite (Auto-Switch Jogos, Modo Viagem, Remapper Copilot)
    print("\n[+] Recursos Exclusivos de Elite:")
    print(f"    - Auto-Switch Jogos:  {'ATIVO' if backend.get_game_auto_switch() else 'DESATIVADO'} (Jogo em execução: {backend.detect_running_game() or 'Nenhum'})")
    print(f"    - Modo Viagem (Eco):  {'ATIVO' if backend.get_eco_travel_mode() else 'INATIVO'}")
    mappings = backend.get_key_mappings()
    for slot_id, cfg in mappings.items():
        print(f"    - Remapper [{slot_id}]: Tecla '{cfg.get('qt_shortcut')}' -> Ação '{cfg.get('action')}' (Ativo: {cfg.get('enabled')})")

    # 8. Feature Discovery & UDEV
    print("\n[+] Feature Discovery & Permissões UDEV:")
    print(f"    - Fn-Lock: {feat.fn_lock} | Camera Power: {feat.camera_power} | USB Charging: {feat.usb_charging} | Kbd Backlight: {feat.kbd_backlight}")
    print(f"    - Regra UDEV Ativa:   {'SIM' if PermissionsManager.is_udev_rule_installed() else 'NÃO'}")
    print(f"    - Escrita Direta:     {'LIBERADA' if backend.has_full_write_permissions() else 'REQUER REPARO UDEV'}")
    print("=" * 72)


if __name__ == "__main__":
    main()
