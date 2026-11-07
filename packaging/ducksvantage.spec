Name:           ducksvantage
Version:        2.0.0
Release:        1%{?dist}
Summary:        Universal Lenovo Vantage replacement for Linux (Legion, LOQ, IdeaPad & Yoga)
License:        MIT
URL:            https://github.com/Patopatetico2-lab/DucksVantage
BuildArch:      noarch
Requires:       python3, python3-pyqt6, python3-psutil

%description
Ducksvantage is a lightweight, universal Linux control center for Lenovo Legion,
LOQ, IdeaPad Gaming, IdeaPad, and Yoga laptops, providing thermal profile control
(Quiet, Balanced, Performance, Max-Power), Battery Conservation Mode (~80%),
Custom TDP (PL1/PL2), Game Auto-Switching, and non-intrusive OSD notifications.

%install
mkdir -p %{buildroot}/opt/ducksvantage
cp -r main.py ui_main.py test_backend.py styles.qss core ui assets packaging %{buildroot}/opt/ducksvantage/

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
chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/conservation_mode 2>/dev/null || :
chmod 0666 /sys/class/powercap/intel-rapl*/constraint_*_power_limit_uw 2>/dev/null || :

%files
/opt/ducksvantage
/usr/bin/ducksvantage
/usr/share/icons/hicolor/scalable/apps/ducksvantage.svg
/usr/share/applications/ducksvantage.desktop
/etc/udev/rules.d/99-ducksvantage.rules

