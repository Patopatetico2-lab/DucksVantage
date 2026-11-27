<p align="center">
  <img src="assets/app_icon.svg" width="110" height="110" alt="Ducksvantage">
</p>

<h1 align="center">DucksVantage</h1>

<p align="center">
  Lightweight native Linux power, thermal profile, fan & chassis controller for <b>Lenovo (Legion, LOQ, IdeaPad Gaming, IdeaPad & Yoga)</b>.<br>
  Built with Python + PyQt6 — ~35 MB RAM, zero telemetry, direct <code>/sys/</code> & WMI integration.<br><br>
  <a href="README.md">Português (BR)</a> • <a href="https://github.com/Patopatetico2-lab/DucksVantage/releases/latest">Download Releases</a> • <a href="https://patopatetico2-lab.github.io/DucksVantage/">Project Website</a>
</p>

---

## Key Features

- **Hardware Telemetry without waking dGPU:** Checks PCI Runtime PM before touching NVML/`nvidia-smi` so NVIDIA RTX GPUs stay asleep in `D3cold` on battery. Reads CPU/RAM temps (`coretemp`, `k10temp`, DDR5 `spd5118`).
- **ACPI Thermal Profiles & `max-power`:** Dynamically reads `/sys/firmware/acpi/platform_profile_choices` and `lenovo-wmi-gamezone`, supporting Quiet, Balanced, Performance, Max-Power, and Custom modes.
- **Easy Fan & Thermal Control:** 1-click cooling modes (*Quiet*, *Auto*, *Cooler*, *Max Turbo*) backed by EC profiles and Lenovo WMI `cpu_temp`/`gpu_temp` thermal triggers, plus full PWM/RPM fan curve & Intel RAPL PL1/PL2 tuning in **Advanced Mode**.
- **Battery Care:** 80% Conservation Mode, Rapid Charge mutual exclusion, One-Time 100% Charge, real battery thermistor thermal alerts, and genuine capacity wear history.
- **Wayland / X11 Non-Intrusive OSD:** Shows translucent `Fn + Q` / `Fn + R` overlays without stealing window focus from fullscreen games.
- **Game Auto-Switching, Eco-Mode & Copilot Key Remapper:** Detects Steam/Proton/Heroic/Wine/Gamescope sessions, toggles customizable Travel/Eco mode (restoring brightness via KDE Plasma 6 D-Bus or sysfs), and remaps `F23` / `Fn + R` keys.
- **KDE Plasma 6 Plasmoid & D-Bus:** Optional panel widget and `org.ducksvantage.Control` D-Bus service.

---

## Download Ready-Made Installers (`v2.3.0`)

Grab the package for your distro from [**GitHub Releases**](https://github.com/Patopatetico2-lab/DucksVantage/releases/latest):

| Distribution | Package | Install command |
| :--- | :--- | :--- |
| **Ubuntu / Debian / Pop!_OS / Mint** | `ducksvantage_2.3.0_all.deb` | `sudo apt install ./ducksvantage_2.3.0_all.deb` |
| **Fedora / Nobara / openSUSE** | `ducksvantage-2.3.0-1.noarch.rpm` | `sudo dnf install ./ducksvantage-2.3.0-1.noarch.rpm` |
| **Arch Linux / CachyOS / Manjaro** | `ducksvantage-2.3.0-1-any.pkg.tar.zst` | `sudo pacman -U ./ducksvantage-2.3.0-1-any.pkg.tar.zst` |
| **Any Linux (Portable)** | `DucksVantage-2.3.0-x86_64.AppImage` | `chmod +x DucksVantage-2.3.0-x86_64.AppImage && ./DucksVantage-2.3.0-x86_64.AppImage` |

`.deb`, `.rpm`, and `.pkg.tar.zst` packages automatically install UDEV rules (`/etc/udev/rules.d/99-ducksvantage.rules`) for passwordless operation. On `.AppImage`, click **"Configurar Acesso Sem Senha"** in the System/About tab on first launch.

### Source Installation (`install.sh`)

```bash
git clone https://github.com/Patopatetico2-lab/DucksVantage.git
cd DucksVantage
sudo ./install.sh
```

## CLI Usage

```bash
ducksvantage --status --json
ducksvantage --profile max-power
ducksvantage --conservation on
ducksvantage --eco toggle
ducksvantage --diagnostic
```
