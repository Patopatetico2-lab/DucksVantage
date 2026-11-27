<p align="center">
  <img src="assets/app_icon.svg" width="120" height="120" alt="Ducksvantage">
</p>

<h1 align="center">Ducksvantage</h1>

<p align="center">
  Gerenciador de energia, perfis térmicos e controles de chassi para notebooks <b>Lenovo (Legion, LOQ, IdeaPad Gaming, IdeaPad e Yoga)</b> no Linux.<br>
  Escrito em Python + PyQt6. Sem Electron, sem telemetria e direto no <code>/sys/</code>.<br><br>
  <a href="https://github.com/Patopatetico2-lab/DucksVantage/releases/latest">
    <img src="https://img.shields.io/github/v/release/Patopatetico2-lab/DucksVantage?label=Release&color=00d2ff" alt="Release">
  </a>
  <a href="https://github.com/Patopatetico2-lab/DucksVantage/actions/workflows/ci.yml">
    <img src="https://github.com/Patopatetico2-lab/DucksVantage/actions/workflows/ci.yml/badge.svg" alt="CI Tests">
  </a>
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License MIT">
  <img src="https://img.shields.io/badge/Linux-Arch%20%7C%20Debian%20%7C%20Fedora-informational" alt="Linux">
  <br><br>
  <b>Português (BR)</b> • <a href="README.en.md">English Version</a> • <a href="https://patopatetico2-lab.github.io/DucksVantage/">Site Oficial</a>
</p>

---

Se você tem um Lenovo Legion, LOQ ou IdeaPad rodando Linux, provavelmente já passou pela mesma situação: no Windows o Lenovo Vantage é pesado pra caramba e cheio de propaganda, mas quando você formata pro Linux acaba sentindo falta de travar a bateria em 80%, ver qual modo térmico entrou quando aperta `Fn + Q` ou desligar a webcam pelo corte físico da placa.

Eu criei o **Ducksvantage** justamente pra não depender de scripts soltos ou ficar dando `echo 1 | sudo tee ...` no terminal toda vez que tiro o notebook da tomada. O programa lê direto o que o kernel expõe na sua máquina (`ideapad_acpi`, `lenovo-wmi-gamezone`, RAPL, `hwmon` e NVML), monta a interface só com o que o seu modelo realmente tem suporte e fica quieto na bandeja do sistema gastando cerca de 30~35 MB de RAM.

## O que tem nele hoje

**Leitura de hardware sem acordar a GPU dedicada**  
No topo da tela principal ficam os medidores de CPU, GPU e RAM (desenhados direto em `QPainter`). Um detalhe que sempre me incomodou em outros monitores no Linux é que, ao consultar a placa da NVIDIA via `nvidia-smi` ou NVML, eles tiram a GPU do estado de suspensão e drenam a bateria. Aqui o código checa primeiro o status PCI Runtime PM: se a sua RTX estiver dormindo em `D3cold`, ele não cutuca a placa e mantém o consumo zerado. Em memórias DDR5 com sensor `spd5118`, ele também puxa a temperatura dos pentes.

**Modos térmicos, controle fácil de ventoinhas e o perfil `max-power`**  
Em vez de chutar perfis fixos, o app lê `/sys/firmware/acpi/platform_profile_choices`. Além dos clássicos *Silencioso* (`low-power`), *Equilibrado* (`balanced`) e *Desempenho* (`performance`), se você estiver num kernel mais novo (como no CachyOS ou Linux 6.12+ com `lenovo-wmi-gamezone`) que libera o perfil **`max-power`**, o quarto botão aparece sozinho na tela e já entra na rotação do `Fn + Q`. Na aba **CPU & Térmico**, você escolhe em 1 clique entre **Silencioso**, **Automático**, **Mais Frio** (que antecipa a rotação via alvos térmicos WMI no EC) e **Turbo Máximo** — ou abre o **Modo Avançado** para editar curva PWM, alvos térmicos CPU/GPU WMI e limites PL1/PL2 (em Watts via RAPL).

**Controles rápidos de chassi (Painel Edge)**  
Fica na lateral direita do dashboard, parecido com o layout antigo da Lenovo:
- Trava de bateria em ~80% (*Modo de Conservação*) e *Rapid Charge* (se você ligar um, ele já desliga o outro pra não dar conflito no EC).
- Corte de energia da webcam (E-Shutter), trava do touchpad, Fn-Lock e portas USB energizadas com o notebook fechado (*Always-On USB*).
- Troca automática de perfil térmico quando você pluga ou tira o carregador, além do controle de brilho do teclado.

**Aviso na tela (OSD) pro `Fn + Q` que não minimiza o jogo**  
Quando você aperta `Fn + Q` no teclado físico, o controlador embarcado (EC) muda o modo direto no hardware. O Ducksvantage monitora isso a cada 200ms e mostra aquele pop-up translúcido na parte de baixo da tela. A janela usa `WindowDoesNotAcceptFocus` e `WindowTransparentForInput`, então se você estiver jogando em tela cheia no Wayland (KDE Plasma, Hyprland, etc.) ou X11, o aviso aparece por cima do jogo sem roubar o mouse e sem dar alt-tab.

**Detecção de jogos (Steam, Heroic, Lutris)**  
Se a opção de troca automática estiver ligada, o programa vigia quando algum jogo sobe via Proton/Reaper, Wine ou Gamescope. Abriu o jogo, ele joga o perfil pra `max-power` (ou `performance`) e muda o governor da CPU; fechou o jogo, ele devolve pro modo que estava antes.

**Histórico de desgaste da bateria**  
Na aba de bateria dá pra ver quantos Watts estão entrando ou saindo em tempo real, voltagem, temperatura e contagem de ciclos. O app também guarda um histórico comparando o `energy_full` atual com o `energy_full_design` de fábrica (em Wh), então dá pra acompanhar no gráfico se a bateria está perdendo capacidade com os meses.

**Dar utilidade pra tecla Copilot (`F23`)**  
Nos modelos mais novos a Lenovo trocou o `Ctrl` direito ou a tecla de menu por um botão dedicado do Copilot, que no Linux só manda um `F23` (ou `Meta+Shift+F23`) pro nada. Na aba de desempenho tem um remapeador que captura essa tecla e deixa você escolher o que ela faz: girar os modos térmicos, mutar o microfone no PipeWire (`wpctl`), travar o touchpad, ligar o Modo Viagem ou rodar um comando seu.

**Modo Viagem (tudo no mínimo com 1 clique)**  
Útil pra quando você está longe da tomada e precisa fazer a bateria render. Ele ativa a trava de 80%, joga a GPU NVIDIA pra `D3cold`, desliga o Turbo Boost da CPU, passa o perfil pra `low-power` / `powersave`, baixa o PL1/PL2 pra 15W/25W e apaga a luz do teclado de uma vez só.

**Inicialização com o sistema (Autostart)**  
Na aba *Sobre* (ou clicando com o botão direito no ícone da bandeja) tem a chave **"Iniciar com o sistema"**. Ela cria o atalho padrão XDG em `~/.config/autostart/ducksvantage.desktop` passando a flag `--minimized`, então o programa já sobe silencioso no tray quando você faz login no KDE, GNOME ou XFCE.

---

## Como instalar

### Baixar instaladores prontos (`v2.3.0`)

Você pode baixar o pacote pronto para a sua distribuição diretamente na página de [**Releases do GitHub**](https://github.com/Patopatetico2-lab/DucksVantage/releases/latest):

| Distribuição | Pacote | Comando de instalação |
| :--- | :--- | :--- |
| **Ubuntu / Debian / Pop!_OS / Mint** | `ducksvantage_2.3.0_all.deb` | `sudo apt install ./ducksvantage_2.3.0_all.deb` |
| **Fedora / Nobara / openSUSE** | `ducksvantage-2.3.0-1.noarch.rpm` | `sudo dnf install ./ducksvantage-2.3.0-1.noarch.rpm` |
| **Arch Linux / CachyOS / Manjaro** | `ducksvantage-2.3.0-1-any.pkg.tar.zst` | `sudo pacman -U ./ducksvantage-2.3.0-1-any.pkg.tar.zst` |
| **Qualquer Linux (Portátil)** | `DucksVantage-2.3.0-x86_64.AppImage` | `chmod +x DucksVantage-2.3.0-x86_64.AppImage && ./DucksVantage-2.3.0-x86_64.AppImage` |

> **Nota sobre o `.AppImage`:** os pacotes `.deb`, `.rpm` e `.pkg.tar.zst` já instalam automaticamente as regras UDEV em `/etc/udev/rules.d/`. Ao usar o `.AppImage`, clique em **"Configurar Acesso Sem Senha"** na aba *Sobre* na primeira abertura para gravar as permissões no sistema.

### Instalar pelo código-fonte (`install.sh`)

Se preferir clonar o repositório e instalar manualmente, o script `install.sh` copia os arquivos pro sistema, cria o atalho com o ícone no menu de aplicativos e já aplica as regras UDEV pra você não precisar digitar senha de root ao mexer nas configurações:

**Arch Linux / CachyOS / Manjaro:**
```bash
sudo pacman -S python-pyqt6 python-psutil python-pynvml
sudo ./install.sh
```
*(Se preferir gerar um pacote nativo pelo `makepkg`, é só entrar na pasta `packaging/` e rodar `makepkg -si`).*

**Ubuntu / Debian / Pop!_OS / Mint:**
```bash
sudo apt update
sudo apt install python3-pyqt6 python3-psutil python3-pynvml policykit-1
sudo ./install.sh
```

**Fedora / Nobara / openSUSE:**
```bash
sudo dnf install python3-pyqt6 python3-psutil python3-pynvml polkit
sudo ./install.sh
```

---

## Rodando pelo menu ou terminal

Depois de instalado, é só abrir o **Ducksvantage** pelo menu do sistema ou chamar no terminal:

```bash
# Abre a janela normal
ducksvantage

# Ou rodando direto da pasta clonada:
python3 main.py

# Inicia direto oculto na bandeja do sistema (tray)
python3 main.py --minimized
```

Se você usa tiling window manager (Hyprland, Sway, i3) ou quer amarrar comandos em atalhos do sistema sem abrir a interface gráfica:

```bash
# Mostra o resumo completo do hardware e sensores detectados
python3 main.py --status

# Troca o perfil térmico na hora
python3 main.py --profile quiet
python3 main.py --profile balanced
python3 main.py --profile performance
python3 main.py --profile max-power

# Liga ou desliga o limite de carga em 80%
python3 main.py --conservation on
python3 main.py --conservation off

# Ativa ou remove o autostart junto com o sistema
python3 main.py --autostart on
python3 main.py --autostart off

# Reaplica as regras UDEV caso necessário
python3 main.py --install-udev
```

---

## Organização das pastas

```text
ducksvantage/
├── main.py                  # Entrada principal, flags CLI e trava de instância única
├── ui_main.py               # Janela principal (Modo Básico/Avançado), sidebar e timers
├── styles.qss               # Tema escuro da interface
├── install.sh / uninstall.sh# Instalador e desinstalador universal Linux
├── assets/                  # Ícone oficial e SVGs da interface
├── core/
│   ├── backend.py           # Orquestração de hardware (/sys/, ACPI, RAPL, hwmon, NVML, WMI)
│   ├── dbus_service.py      # Serviço D-Bus (org.ducksvantage.Control) e KRunner
│   ├── key_mapper.py        # Sanitização e mapeamento de teclas (Copilot F23 / Fn+R)
│   ├── models.py            # Dataclasses tipadas de sensores e capacidades
│   ├── permissions.py       # Checagem de escrita no sysfs, UDEV e pkexec sob demanda
│   ├── settings.py          # Preferências atômicas e histórico em ~/.config/ducksvantage/
│   └── mixins/              # Módulos térmicos/fan/eco, GPU/MUX, bateria/rede, jogos e extras
├── ui/
│   ├── dashboard.py         # Tela inicial (Gauges, Perfil Térmico, Gráfico Vivo e Painel Edge)
│   ├── gauges.py            # Medidores circulares desenhados via QPainter
│   ├── osd_overlay.py       # Pop-up OSD não-intrusivo do Fn+Q
│   ├── tray_icon.py         # Menu rápido na bandeja do sistema
│   ├── widgets/             # Widgets reutilizáveis (curva de fan, gráfico térmico, captura de teclas)
│   └── tabs/                # Abas: CPU & Térmico, GPU & Tela, Automação, Bateria, RGB e Sistema
├── plasmoid/                # Widget nativo para painel do KDE Plasma 6
├── packaging/               # Builders .deb, .rpm, Arch PKGBUILD, AppImage e regras UDEV
└── tests/                   # Suíte automatizada de testes unitários (Qt offscreen)
```

## Sobre as permissões sem `sudo`

No Linux, arquivos como `/sys/firmware/acpi/platform_profile` e `conservation_mode` só aceitam escrita do `root` por padrão. Pra você não ter que digitar senha toda vez que apertar um botão ou quando um jogo abrir, o arquivo [`packaging/99-ducksvantage.rules`](packaging/99-ducksvantage.rules) aplica permissão de escrita apenas nos caminhos sysfs de energia, bateria, luz do teclado e RAPL durante o boot. Se por algum motivo você rodar o app sem ter passado pelo instalador, dá pra instalar ou reparar essas permissões com um clique direto na aba **Sobre**.
