Name:           ducksvantage
Version:        %{?_app_version}%{!?_app_version:2.3.0}
Release:        1
Summary:        Universal Lenovo Vantage replacement for Linux (Legion, LOQ, IdeaPad & Yoga)
License:        MIT
URL:            https://github.com/Patopatetico2-lab/DucksVantage
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch
Requires:       python3, python3-pyqt6, python3-psutil

%description
Ducksvantage is a lightweight, universal Linux control center for Lenovo Legion,
LOQ, IdeaPad Gaming, IdeaPad, and Yoga laptops, providing thermal profile control
(Quiet, Balanced, Performance, Max-Power), Battery Conservation Mode (~80%),
Custom TDP (PL1/PL2), Game Auto-Switching, Eco-Mode, KDE Plasma 6 Plasmoid,
and non-intrusive OSD notifications.

%prep
%setup -q

%install
mkdir -p %{buildroot}/opt/ducksvantage
cp -r main.py ui_main.py test_backend.py styles.qss setup_udev.sh uninstall.sh core ui assets packaging plasmoid %{buildroot}/opt/ducksvantage/
find %{buildroot}/opt/ducksvantage -name "__pycache__" -prune -exec rm -rf {} +
find %{buildroot}/opt/ducksvantage -name "*.pyc" -delete

mkdir -p %{buildroot}/usr/bin
cat << 'EOF' > %{buildroot}/usr/bin/ducksvantage
#!/usr/bin/env bash
cd /opt/ducksvantage
exec python3 /opt/ducksvantage/main.py "$@"
EOF
chmod 0755 %{buildroot}/usr/bin/ducksvantage

install -Dm644 assets/app_icon.svg %{buildroot}/usr/share/icons/hicolor/scalable/apps/ducksvantage.svg
install -Dm644 packaging/ducksvantage.desktop %{buildroot}/usr/share/applications/ducksvantage.desktop
install -Dm644 packaging/99-ducksvantage.rules %{buildroot}/etc/udev/rules.d/99-ducksvantage.rules

%post
udevadm control --reload-rules >/dev/null 2>&1 || :
udevadm trigger >/dev/null 2>&1 || :
chmod 0666 /sys/firmware/acpi/platform_profile 2>/dev/null || :
chmod 0666 /sys/class/platform-profile/*/profile 2>/dev/null || :
chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/conservation_mode 2>/dev/null || :
chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/rapid_charge 2>/dev/null || :
chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/fn_lock 2>/dev/null || :
chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/camera_power 2>/dev/null || :
chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/usb_charging 2>/dev/null || :
chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/touchpad 2>/dev/null || :
chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/fan_mode 2>/dev/null || :
chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/lcd_overdrive 2>/dev/null || :
chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/gpu_mode 2>/dev/null || :
chmod 0666 /sys/class/leds/*kbd_backlight*/brightness 2>/dev/null || :
chmod 0666 /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null || :
chmod 0666 /sys/devices/system/cpu/cpufreq/boost 2>/dev/null || :
chmod 0666 /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor 2>/dev/null || :
chmod 0666 /sys/devices/system/cpu/cpu*/cpufreq/energy_performance_preference 2>/dev/null || :
chmod 0666 /sys/class/powercap/intel-rapl*/constraint_*_power_limit_uw 2>/dev/null || :
chmod 0666 /sys/bus/pci/devices/*/power/control 2>/dev/null || :
chmod 0666 /sys/class/power_supply/BAT*/charge_types 2>/dev/null || :
chmod 0666 /sys/class/firmware-attributes/*/attributes/*/current_value 2>/dev/null || :
chmod 0666 /sys/class/hwmon/hwmon*/pwm* /sys/class/hwmon/hwmon*/fan*_target 2>/dev/null || :
chmod 0666 /sys/class/net/*/device/power/control 2>/dev/null || :
chmod 0666 /sys/class/backlight/*/brightness 2>/dev/null || :
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications >/dev/null 2>&1 || :
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || :
fi

%postun
udevadm control --reload-rules >/dev/null 2>&1 || :
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications >/dev/null 2>&1 || :
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || :
fi

%files
/opt/ducksvantage
/usr/bin/ducksvantage
/usr/share/icons/hicolor/scalable/apps/ducksvantage.svg
/usr/share/applications/ducksvantage.desktop
/etc/udev/rules.d/99-ducksvantage.rules
