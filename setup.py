#!/usr/bin/env python3
"""
Setup e instalador de pacote Python para o Ducksvantage (setup.py).
Gerencia dependências (PyQt6, psutil, nvidia-ml-py/pynvml) e instala automaticamente
o ícone vetorial, o atalho .desktop e as regras UDEV em /etc/udev/rules.d/ quando
executado com privilégios de sistema.
"""

import os
import sys
import glob
import subprocess
from setuptools import setup, find_packages
from setuptools.command.install import install


def get_asset_files():
    """Coleta ícones SVG, estilos QSS, atalho .desktop e regras UDEV para instalação."""
    data_files = [
        ("share/applications", ["packaging/ducksvantage.desktop"]),
        ("share/icons/hicolor/scalable/apps", ["assets/app_icon.svg"]),
        ("share/ducksvantage", ["styles.qss"]),
        ("share/ducksvantage/assets", ["assets/app_icon.svg"]),
        ("share/ducksvantage/assets/icons", glob.glob("assets/icons/*.svg")),
        ("share/ducksvantage/packaging", ["packaging/99-ducksvantage.rules", "packaging/ducksvantage.desktop"]),
    ]
    # Se estiver instalando como root ou construindo pacote DEB/RPM/Arch (com --root / DESTDIR)
    if os.geteuid() == 0 or any("--root" in arg for arg in sys.argv):
        data_files.append(("/etc/udev/rules.d", ["packaging/99-ducksvantage.rules"]))
    return data_files


class PostInstallCommand(install):
    """Executa a ativação automática das regras UDEV no sistema pós-instalação."""

    def run(self):
        super().run()
        if os.geteuid() == 0 and not self.root:
            try:
                # Renomear ícone instalado para ducksvantage.svg no tema hicolor
                icon_dir = "/usr/share/icons/hicolor/scalable/apps"
                src_icon = os.path.join(icon_dir, "app_icon.svg")
                dst_icon = os.path.join(icon_dir, "ducksvantage.svg")
                if os.path.exists(src_icon):
                    os.replace(src_icon, dst_icon)
                subprocess.run(["udevadm", "control", "--reload-rules"], check=False)
                subprocess.run(["udevadm", "trigger"], check=False)
            except Exception as e:
                print(f"[Aviso] Não foi possível recarregar o udevadm automaticamente: {e}")


setup(
    name="ducksvantage",
    version="2.0.0",
    description="Substituto universal do Lenovo Vantage para Linux (Legion, LOQ, IdeaPad e Yoga)",
    py_modules=["main", "ui_main", "test_backend"],
    packages=find_packages(include=["core", "core.*", "ui", "ui.*"]),
    install_requires=[
        "PyQt6>=6.4.0",
        "psutil>=5.9.0",
        "nvidia-ml-py>=12.0.0",
    ],
    entry_points={
        "console_scripts": [
            "ducksvantage=main:main",
        ],
    },
    data_files=get_asset_files(),
    cmdclass={
        "install": PostInstallCommand,
    },
    python_requires=">=3.9",
)

