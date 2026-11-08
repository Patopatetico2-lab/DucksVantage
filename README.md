<p align="center">
  <img src="assets/app_icon.svg" width="128" height="128" alt="Ducksvantage Logo">
</p>

<h1 align="center">Ducksvantage</h1>

<p align="center">
  Controle de hardware e energia para notebooks <b>Lenovo Legion, LOQ, IdeaPad Gaming, IdeaPad e Yoga</b> no Linux.<br>
  Feito em Python + PyQt6, conversando direto com <code>/sys/</code>, ACPI, <code>ideapad_acpi</code>, <code>lenovo-wmi-gamezone</code>, RAPL e <code>hwmon</code>.
</p>

<p align="center">
  <a href="https://patopatetico2-lab.github.io/DucksVantage/"><img src="https://img.shields.io/badge/🌐_Landing_Page-Visitar_Site_Oficial-00d2ff?style=for-the-badge" alt="Landing Page"></a>
  <img src="https://img.shields.io/badge/Python-3.9+-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3">
  <img src="https://img.shields.io/badge/PyQt6-Native-2cd283?style=for-the-badge" alt="PyQt6">
  <img src="https://img.shields.io/badge/Linux_Kernel-6.x-orange?style=for-the-badge&logo=linux&logoColor=white" alt="Linux">
  <img src="https://img.shields.io/badge/License-MIT-purple?style=for-the-badge" alt="License MIT">
</p>

---

Quem usa um Lenovo Legion, LOQ ou IdeaPad no Linux conhece o problema: o Lenovo Vantage do Windows é pesado e cheio de telemetria, mas sem ele você perde o acesso rápido aos modos térmicos, limite de carga de 80%, controle do obturador da câmera e feedback visual do `Fn + Q`.

O **Ducksvantage** resolve isso sem depender de daemons inchados ou serviços em Electron. Ele lê as interfaces reais que o kernel Linux expõe para a sua máquina, adapta a interface ao que o seu modelo específico suporta (seja Intel ou AMD, com GPU dedicada NVIDIA, Radeon ou integrada) e fica residente na bandeja do sistema consumindo o mínimo de RAM.

---

## O que o Ducksvantage faz

### 1. Medidores Circulares em Tempo Real (`QPainter`)
No topo do Dashboard ficam 3 medidores vetoriais desenhados em `QPainter` com animação fluida:
- **CPU:** uso percentual, frequência atual em MHz/GHz, temperatura em °C (`coretemp` / `k10temp`) e estado do Turbo Boost.
- **GPU:** detecção automática do modelo real (ex: RTX 3050, RTX 4060, Radeon, Intel Iris). Em GPUs NVIDIA, usa `pynvml` / `nvidia-smi` para ler temperatura, clock, consumo em Watts e VRAM, mas **verifica antes o estado PCI Runtime PM** — se a placa dedicada estiver dormindo em `D3cold`, o app não acorda a GPU à toa.
- **RAM:** uso percentual, GB alocados vs. livres e leitura de temperatura para pentes DDR5 (`spd5118`) quando disponível.

### 2. Perfis Térmicos do Kernel + Suporte Nativo ao `max-power`
Em vez de assumir perfis fixos, o backend lê `/sys/firmware/acpi/platform_profile_choices` na inicialização:
- Suporta os modos **Silencioso** (`low-power` / `quiet`), **Equilibrado** (`balanced`) e **Desempenho** (`performance`).
- Se o driver do kernel (como o `lenovo-wmi-gamezone` no CachyOS / Linux 6.12+) expuser o perfil **`max-power`** (*Desempenho Máximo*), o Ducksvantage habilita automaticamente o quarto card e o inclui na rotação do atalho `Fn + Q`, acionando a curva máxima de rotação das ventoinhas e o teto de potência do EC.
- Inclui ajuste manual de **TDP (PL1 / PL2 em Watts)** via Intel RAPL (`/sys/class/powercap/intel-rapl:0`), chave de CPU Turbo Boost, seletor de *Scaling Governor* (`powersave` / `performance`) e gráfico ao vivo da curva de ventoinhas (°C vs RPM).

### 3. Painel Rápido Edge (LOQ / Legion / Lenovo Edge)
Inspirado na coluna lateral do Vantage original, agrupa os controles de chassi que o driver `ideapad_acpi` disponibiliza na sua máquina:
- **Modo de Conservação (~80%):** trava o carregamento em 75–80% para evitar estresse químico quando o notebook fica direto na tomada.
- **Carregamento Rápido (Rapid Charge):** acelera a corrente de carga (com exclusão mútua automática em relação ao Modo de Conservação).
- **Fn-Lock:** alterna o comportamento padrão de `F1–F12` entre teclas de função e atalhos multimídia.
- **Obturador da Câmera (E-Shutter):** corta ou libera a alimentação física da webcam via ACPI.
- **Always-On USB Charging:** mantém as portas USB energizadas mesmo com o notebook em suspensão (exibido apenas se o firmware suportar).
- **Trava do Touchpad:** bloqueia o touchpad durante partidas.
- **Transição Automática AC / Bateria:** muda o perfil térmico sozinho quando você tira ou coloca o carregador na tomada.
- **Luz do Teclado:** controle direto dos níveis de brilho (`Desligado`, `Baixo`, `Alto`) em `/sys/class/leds/*kbd_backlight*/brightness`.

### 4. Pop-up OSD para `Fn + Q` (Sem Roubar Foco no Wayland / KDE Plasma)
Um loop leve de 200ms monitora mudanças diretas feitas pelo controlador embarcado (EC) quando você aperta `Fn + Q`, `Fn + Espaço` ou conecta o carregador.
- Exibe um overlay translúcido na parte inferior da tela indicando o modo ativo (**Modo Silencioso**, **Modo Equilibrado**, **Modo Desempenho** ou **Desempenho Máximo (Max-Power)**).
- Configurado com flags `WindowDoesNotAcceptFocus | WindowTransparentForInput | Tool`: o OSD aparece por cima do jogo em tela cheia sem minimizar a janela e sem roubar o cursor ou o teclado.

### 5. Auto-Switching Inteligente por Jogo (Steam & Heroic)
O backend monitora processos de jogos abertos via **Steam (Proton / Reaper)**, **Heroic Games Launcher**, **Lutris**, **Wine** e **Gamescope**:
- Abriu um jogo: muda o perfil ACPI para `max-power` (ou `performance`) e passa o *CPU governor* para `performance`, avisando pelo OSD.
- Fechou o jogo: devolve o notebook para o perfil anterior (`balanced` na tomada ou `low-power` na bateria) e restaura o governor `powersave`.

### 6. Battery Health Historian (Gráfico de Degradação da Bateria)
Na aba de Alimentação & Bateria, além da leitura elétrica em tempo real (Watts, Voltagem, Ciclos e Temperatura), o app salva snapshots da capacidade máxima atual (`energy_full`) comparada à capacidade de projeto de fábrica (`energy_full_design` em Wh) e plota um gráfico histórico da saúde da bateria.

### 7. Remapeador de Teclas (Aproveitamento da Tecla Copilot `F23`)
Notebooks Lenovo recentes vêm com a tecla dedicada do Copilot no lugar do `Ctrl` direito ou `Menu`, que no Linux apenas dispara `F23` ou `Meta+Shift+F23` sem função útil.
- O remapeador captura `F23`, `F24` ou qualquer atalho (via Qt e leitura não-bloqueante em `/dev/input`) e permite associar ações diretas: ciclar modos térmicos, ligar/desligar o `Max-Power`, ativar o Modo Viagem, mutar o microfone via PipeWire (`wpctl`), travar o touchpad ou rodar um script próprio.

### 8. Modo Viagem (Eco-Mode em 1 Clique)
Um único botão pensado para quando você precisa tirar o máximo de horas fora da tomada. Ao ativar:
1. Liga o Modo de Conservação (80%).
2. Força a GPU dedicada NVIDIA para suspensão `D3cold` (`power/control = auto`).
3. Desativa o CPU Turbo Boost.
4. Muda o perfil ACPI para `low-power` e o governor para `powersave`.
5. Reduz os limites de potência PL1/PL2 para 15W / 25W.
6. Apaga a iluminação do teclado.

---

## Instalação

### CachyOS / Arch Linux (via `pacman` + script instalador)
Instale as dependências do sistema e rode o instalador (que já copia o app, o ícone vetorial, o atalho `.desktop` do menu de aplicativos e aplica as regras UDEV):

```bash
sudo pacman -S python-pyqt6 python-psutil python-pynvml
sudo ./install.sh
```

Se quiser construir e instalar como pacote nativo do Arch/CachyOS (`makepkg`):

```bash
cd packaging
makepkg -si
```

### Ubuntu / Debian / Pop!_OS / Linux Mint
```bash
sudo apt update
sudo apt install python3-pyqt6 python3-psutil python3-pynvml policykit-1
sudo ./install.sh
```

### Fedora / RHEL / openSUSE
```bash
sudo dnf install python3-pyqt6 python3-psutil python3-pynvml polkit
sudo ./install.sh
```

---

## Uso Rápido (GUI e Terminal)

Depois de instalado, procure por **Ducksvantage** no menu de aplicativos do KDE Plasma (ou outra DE) ou execute no terminal:

```bash
# Abrir a interface gráfica
ducksvantage
# ou direto da pasta do repositório:
python3 main.py

# Iniciar silenciosamente na bandeja do sistema (System Tray / Autostart)
python3 main.py --minimized
```

Você também pode controlar os perfis e verificar sensores pela linha de comando (útil para scripts ou keybinds do Hyprland / KWin):

```bash
# Exibir diagnóstico completo do hardware, sensores e recursos detectados
python3 main.py --status

# Definir o perfil térmico manualmente
python3 main.py --profile quiet
python3 main.py --profile balanced
python3 main.py --profile performance
python3 main.py --profile max-power

# Ativar ou desativar o limite de carga em 80% (Modo de Conservação)
python3 main.py --conservation on
python3 main.py --conservation off

# Ativar ou desativar a inicialização automática com o sistema (XDG Autostart)
python3 main.py --autostart on
python3 main.py --autostart off

# Instalar/reparar as regras UDEV para operar sem pedir senha sudo/polkit
python3 main.py --install-udev
```

---

## Estrutura do Projeto

```text
ducksvantage/
├── main.py                        # Entrada principal (GUI, CLI e controle de instância única)
├── ui_main.py                     # Janela principal, header dinâmico, sidebar e ciclo de timers
├── backend.py                     # Re-exportação direta do backend e dicionários ACPI
├── styles.qss                     # Folha de estilos escura inspirada no Lenovo Vantage
├── install.sh                     # Instalador multi-distro + configuração automática do UDEV
├── setup_udev.sh                  # Script rápido para aplicar regras UDEV avulsas
├── test_backend.py                # Diagnóstico de sensores e ACPI pelo terminal
├── pyproject.toml / setup.py      # Metadados de empacotamento Python (PEP 621)
├── assets/
│   ├── app_icon.svg               # Ícone vetorial oficial do Ducksvantage
│   └── icons/                     # Ícones SVG (thermal_max_power, copilot_key, eco_travel, etc.)
├── core/
│   ├── backend.py                 # Comunicação com /sys/, ACPI, hwmon, RAPL, DRM, NVML e evdev
│   ├── models.py                  # Dataclasses de telemetria e capacidades do sistema
│   ├── permissions.py             # Escrita em sysfs e instalador de regras UDEV via pkexec
│   ├── qt_compat.py               # Compatibilidade transparente PyQt6 / PySide6
│   └── settings.py                # Persistência de configurações e histórico em ~/.config/ducksvantage/
├── ui/
│   ├── theme_tokens.py            # Paleta de cores hexadecimais e tokens visuais
│   ├── components.py              # ToggleSwitch, ProfileCard, StatusBadge e widgets base
│   ├── gauges.py                  # Medidores circulares QPainter (CPU, GPU e RAM)
│   ├── osd_overlay.py             # Pop-up OSD não-intrusivo para Fn+Q e eventos
│   ├── dashboard.py               # Layout de 2 colunas (65% telemetria / 35% painel Edge)
│   ├── tray_icon.py               # Gerenciador de bandeja do sistema (System Tray)
│   └── tabs/
│       ├── performance_tab.py     # Perfis ACPI, Max-Power, TDP PL1/PL2, Curva de Fans e Remapper
│       ├── battery_tab.py         # Telemetria elétrica e gráfico Battery Health Historian
│       └── about_tab.py           # Dados de DMI/BIOS e diagnóstico de permissões UDEV
└── packaging/
    ├── ducksvantage.desktop       # Atalho padrão FreeDesktop para KDE Plasma / GNOME
    ├── 99-ducksvantage.rules      # Regras UDEV para escrita em sysfs sem root
    ├── PKGBUILD                   # Receita de pacote para Arch Linux / CachyOS
    ├── ducksvantage.spec          # Receita de pacote RPM (Fedora / openSUSE)
    └── debian/postinst            # Hook pós-instalação para pacotes DEB
```

---

## Como funcionam as permissões (Zero `sudo` no dia a dia)

Por padrão no Linux, arquivos como `/sys/firmware/acpi/platform_profile` e `/sys/bus/platform/drivers/ideapad_acpi/*/conservation_mode` pertencem ao `root`.

Para que o atalho `Fn + Q`, o Auto-Switch de jogos e os botões da interface funcionem instantaneamente sem abrir janelas de senha toda vez, o arquivo [`packaging/99-ducksvantage.rules`](packaging/99-ducksvantage.rules) libera permissão de escrita (`chmod 0666`) apenas nos nós sysfs de gerenciamento térmico, bateria, iluminação do teclado e limites RAPL durante o boot. Se você ainda não tiver rodado o `install.sh`, pode aplicar as regras com um clique diretamente na aba **Sobre o Dispositivo** dentro do aplicativo.

---

## 🌐 Site Oficial & GitHub Pages

O projeto inclui uma **landing page de propaganda moderna e interativa** pronta para publicação no GitHub Pages.

### Como ativar no seu repositório GitHub:
1. No seu repositório no GitHub, acesse **Settings** (Configurações) > **Pages**.
2. Em **Build and deployment** > **Source**, selecione **Deploy from a branch**.
3. Em **Branch**, selecione `main` (ou `master`) e escolha a pasta `/` (root) ou `/docs`.
4. Clique em **Save**. Em instantes seu site estará no ar em: `https://patopatetico2-lab.github.io/DucksVantage/`!

