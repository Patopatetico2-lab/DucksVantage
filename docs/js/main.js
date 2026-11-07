/**
 * DucksVantage - Interatividade Oficial da Landing Page (js/main.js)
 * Simulação interativa do Dashboard, Perfis Térmicos, OSD Fn+Q,
 * Switches Edge, Terminal CLI e Tabs de Instalação.
 */

document.addEventListener("DOMContentLoaded", () => {
  initNavbar();
  initSimulator();
  initInstallTabs();
  initTerminalShowcase();
  initFaqAccordion();
  initCopyButtons();
});

/* ====================================================================
   1. NAVBAR & MOBILE MENU
   ==================================================================== */
function initNavbar() {
  const toggleBtn = document.querySelector(".mobile-toggle");
  const navLinks = document.querySelector(".nav-links");

  if (toggleBtn && navLinks) {
    toggleBtn.addEventListener("click", () => {
      const isVisible = navLinks.style.display === "flex";
      navLinks.style.display = isVisible ? "none" : "flex";
      navLinks.style.flexDirection = "column";
      navLinks.style.position = "absolute";
      navLinks.style.top = "72px";
      navLinks.style.left = "0";
      navLinks.style.right = "0";
      navLinks.style.background = "rgba(17, 25, 44, 0.98)";
      navLinks.style.padding = "20px";
      navLinks.style.borderBottom = "1px solid var(--border-default)";
    });
  }

  // Efeito de sombra ao rolar a página
  window.addEventListener("scroll", () => {
    const navbar = document.querySelector(".navbar");
    if (navbar) {
      if (window.scrollY > 30) {
        navbar.style.borderBottomColor = "var(--border-cyan)";
        navbar.style.boxShadow = "0 8px 30px rgba(0, 0, 0, 0.5)";
      } else {
        navbar.style.borderBottomColor = "var(--border-default)";
        navbar.style.boxShadow = "none";
      }
    }
  });
}

/* ====================================================================
   2. SIMULADOR DO DASHBOARD DUCKSVANTAGE (O CORAÇÃO DO SITE)
   ==================================================================== */
function initSimulator() {
  // Elementos dos gauges
  const cpuVal = document.getElementById("sim-cpu-val");
  const cpuClock = document.getElementById("sim-cpu-clock");
  const cpuTemp = document.getElementById("sim-cpu-temp");
  const cpuCircle = document.getElementById("sim-cpu-circle");

  const gpuVal = document.getElementById("sim-gpu-val");
  const gpuWatt = document.getElementById("sim-gpu-watt");
  const gpuTemp = document.getElementById("sim-gpu-temp");
  const gpuCircle = document.getElementById("sim-gpu-circle");

  const ramVal = document.getElementById("sim-ram-val");
  const ramCircle = document.getElementById("sim-ram-circle");

  // Elementos do OSD Pop-up
  const osdOverlay = document.getElementById("sim-osd");
  const osdTitle = document.getElementById("osd-title");
  const osdDesc = document.getElementById("osd-desc");
  const osdIcon = document.getElementById("osd-icon");

  let osdTimeout = null;

  // Dados dos Modos Térmicos
  const thermalProfiles = {
    quiet: {
      name: "Modo Silencioso",
      desc: "Perfil de Baixo Ruído & Consumo (Quiet)",
      icon: "assets/icons/thermal_quiet.svg",
      activeClass: "active-quiet",
      cpu: { val: 8, clock: "2.1 GHz", temp: "42°C", offset: 230 },
      gpu: { val: 0, watt: "0W (D3cold)", temp: "38°C", offset: 275 },
      ram: { val: 4.8, offset: 195 },
      glowColor: "var(--cyan)",
    },
    balanced: {
      name: "Modo Equilibrado",
      desc: "Equilíbrio Dinâmico Inteligente (Balanced)",
      icon: "assets/icons/thermal_balanced.svg",
      activeClass: "active-balanced",
      cpu: { val: 24, clock: "3.8 GHz", temp: "52°C", offset: 180 },
      gpu: { val: 32, watt: "45W", temp: "54°C", offset: 160 },
      ram: { val: 6.2, offset: 170 },
      glowColor: "#2ec5eb",
    },
    performance: {
      name: "Modo Desempenho",
      desc: "Perfil de Alta Potência Legion (Performance)",
      icon: "assets/icons/thermal_performance.svg",
      activeClass: "active-performance",
      cpu: { val: 68, clock: "4.7 GHz", temp: "68°C", offset: 95 },
      gpu: { val: 82, watt: "105W", temp: "71°C", offset: 60 },
      ram: { val: 9.8, offset: 120 },
      glowColor: "var(--legion-red)",
    },
    "max-power": {
      name: "Desempenho Máximo",
      desc: "Teto de Potência Extremo + Ventoinhas a 100% (Max-Power)",
      icon: "assets/icons/thermal_max_power.svg",
      activeClass: "active-max-power",
      cpu: { val: 94, clock: "5.1 GHz", temp: "78°C", offset: 35 },
      gpu: { val: 98, watt: "115W (TGP Max)", temp: "74°C", offset: 25 },
      ram: { val: 12.4, offset: 80 },
      glowColor: "var(--max-power)",
    },
  };

  // Botões de perfil térmico
  const thermalBtns = document.querySelectorAll(".thermal-btn");
  thermalBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const mode = btn.getAttribute("data-mode");
      setThermalMode(mode);
    });
  });

  function setThermalMode(mode) {
    const data = thermalProfiles[mode];
    if (!data) return;

    // Atualiza estados dos botões
    thermalBtns.forEach((b) => {
      b.className = "thermal-btn";
    });
    const targetBtn = document.querySelector(`.thermal-btn[data-mode="${mode}"]`);
    if (targetBtn) {
      targetBtn.classList.add(data.activeClass);
    }

    // Atualiza os gauges animados
    if (cpuVal) cpuVal.textContent = data.cpu.val + "%";
    if (cpuClock) cpuClock.textContent = data.cpu.clock;
    if (cpuTemp) cpuTemp.textContent = data.cpu.temp;
    if (cpuCircle) cpuCircle.style.strokeDashoffset = data.cpu.offset;

    if (gpuVal) gpuVal.textContent = data.gpu.val + "%";
    if (gpuWatt) gpuWatt.textContent = data.gpu.watt;
    if (gpuTemp) gpuTemp.textContent = data.gpu.temp;
    if (gpuCircle) gpuCircle.style.strokeDashoffset = data.gpu.offset;

    if (ramVal) ramVal.textContent = data.ram.val + " GB";
    if (ramCircle) ramCircle.style.strokeDashoffset = data.ram.offset;

    // Dispara o OSD pop-up simulando o atalho Fn + Q
    showOsd(data.name, data.desc, data.icon, data.glowColor);
  }

  function showOsd(title, desc, iconSrc, glowColor) {
    if (!osdOverlay) return;

    if (osdTitle) osdTitle.textContent = title;
    if (osdDesc) osdDesc.textContent = desc;
    if (osdIcon) osdIcon.src = iconSrc;

    osdOverlay.style.borderColor = glowColor;
    osdOverlay.style.boxShadow = `0 15px 40px rgba(0,0,0,0.7), 0 0 25px ${glowColor}`;

    osdOverlay.classList.add("show");

    if (osdTimeout) clearTimeout(osdTimeout);
    osdTimeout = setTimeout(() => {
      osdOverlay.classList.remove("show");
    }, 2800);
  }

  // Switches Edge com Regras de Negócio Reais
  const conservationToggle = document.getElementById("toggle-conservation");
  const rapidToggle = document.getElementById("toggle-rapid");
  const cameraToggle = document.getElementById("toggle-camera");
  const touchpadToggle = document.getElementById("toggle-touchpad");
  const copilotToggle = document.getElementById("toggle-copilot");
  const ecoToggle = document.getElementById("toggle-eco");

  // Exclusão Mútua: Modo Conservação vs Carga Rápida
  if (conservationToggle && rapidToggle) {
    conservationToggle.addEventListener("change", (e) => {
      if (e.target.checked) {
        rapidToggle.checked = false;
        showToast("🔋 Modo Conservação: Limite fixado em 80% (Proteção de Bateria)");
      } else {
        showToast("Bateria livre para carregar até 100%");
      }
    });

    rapidToggle.addEventListener("change", (e) => {
      if (e.target.checked) {
        conservationToggle.checked = false;
        showToast("⚡ Carga Rápida (Rapid Charge) ativada via ACPI");
      }
    });
  }

  if (cameraToggle) {
    cameraToggle.addEventListener("change", (e) => {
      showToast(e.target.checked ? "📷 Obturador da Câmera: Aberto" : "🔒 E-Shutter: Alimentação física cortada via ACPI");
    });
  }

  if (touchpadToggle) {
    touchpadToggle.addEventListener("change", (e) => {
      showToast(e.target.checked ? "🖱️ Touchpad Desativado (Modo Gamer)" : "🖱️ Touchpad Habilitado");
    });
  }

  if (copilotToggle) {
    copilotToggle.addEventListener("change", (e) => {
      showToast(e.target.checked ? "⌨️ Tecla Copilot (F23) remapeada para 'Mudo PipeWire'" : "⌨️ Tecla Copilot em modo padrão");
    });
  }

  // Modo Viagem (Eco Travel): 1-Click Battery Saver
  if (ecoToggle) {
    ecoToggle.addEventListener("change", (e) => {
      if (e.target.checked) {
        setThermalMode("quiet");
        if (conservationToggle) conservationToggle.checked = true;
        if (rapidToggle) rapidToggle.checked = false;
        showToast("🧳 Modo Viagem Ativado: GPU em D3cold, Turbo OFF e TDP em 15W");
      } else {
        setThermalMode("balanced");
        showToast("Modo Viagem Desativado");
      }
    });
  }

  // Micro-oscilações realistas para simular sensores vivos em tempo real
  setInterval(() => {
    const activeBtn = document.querySelector(".thermal-btn[class*='active-']");
    if (!activeBtn) return;
    const mode = activeBtn.getAttribute("data-mode");
    const base = thermalProfiles[mode];
    if (!base) return;

    // Pequena variação aleatória de +/- 2%
    const jitter = Math.floor(Math.random() * 5) - 2;
    const currentVal = Math.max(2, Math.min(99, base.cpu.val + jitter));
    if (cpuVal) cpuVal.textContent = currentVal + "%";
  }, 2500);
}

/* ====================================================================
   3. ABAS DE INSTALAÇÃO MULTI-DISTRO
   ==================================================================== */
function initInstallTabs() {
  const tabs = document.querySelectorAll(".install-tab-btn");
  const panes = document.querySelectorAll(".install-pane");

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const targetId = tab.getAttribute("data-target");

      tabs.forEach((t) => t.classList.remove("active"));
      panes.forEach((p) => p.classList.remove("active"));

      tab.classList.add("active");
      const targetPane = document.getElementById(targetId);
      if (targetPane) {
        targetPane.classList.add("active");
      }
    });
  });
}

/* ====================================================================
   4. TERMINAL CLI SHOWCASE INTERATIVO
   ==================================================================== */
function initTerminalShowcase() {
  const tabs = document.querySelectorAll(".terminal-tab-btn");
  const termContent = document.getElementById("terminal-screen");

  const terminalOutputs = {
    status: `
<span class="t-dim">$ ducksvantage --status</span>
<span class="t-cyan">===============================================================</span>
<span class="t-cyan">       DUCKSVANTAGE v2.0 - DIAGNÓSTICO DO SISTEMA & ACPI       </span>
<span class="t-cyan">===============================================================</span>
<span class="t-green">✔ Hardware Detectado:</span> Lenovo Legion Pro 5 16ARX8
<span class="t-green">✔ Driver ACPI Ativo:</span>  ideapad_acpi + lenovo-wmi-gamezone
<span class="t-green">✔ Perfis Disponíveis:</span> quiet, balanced, performance, <span class="t-purple">max-power</span>
<span class="t-yellow">⚡ Perfil Térmico:</span>    <span class="t-purple">[max-power]</span> (Potência EC desbloqueada)
<span class="t-green">✔ CPU Detectada:</span>      AMD Ryzen 7 7745HX (16 threads @ 5.10 GHz, 58°C)
<span class="t-green">✔ GPU Dedicada:</span>       NVIDIA GeForce RTX 4060 Laptop (115W, 62°C)
<span class="t-green">✔ Modo de Conservação:</span> <span class="t-cyan">ATIVO [80%]</span> (Bateria protegida)
<span class="t-green">✔ Regras UDEV:</span>        Instaladas em /etc/udev/rules.d/ (Sem sudo)
<span class="t-green">✔ Pop-up OSD Fn+Q:</span>    Wayland / X11 Ativo (Sem roubar foco)
    `.trim(),

    profile: `
<span class="t-dim">$ ducksvantage --profile max-power</span>
<span class="t-purple">[ACPI]</span> Escrevendo 'max-power' em /sys/firmware/acpi/platform_profile...
<span class="t-green">[RAPL]</span> Desbloqueando teto de potência PL1 (85W) e PL2 (115W)...
<span class="t-cyan">[FANS]</span> Curva de rotação máxima acionada no EC (4800 RPM).
<span class="t-yellow">[OSD]</span>  Enviando sinal para overlay translúcido na tela...
<span class="t-green">✔ Perfil 'max-power' ativado com sucesso!</span>
    `.trim(),

    conservation: `
<span class="t-dim">$ ducksvantage --conservation on</span>
<span class="t-cyan">[BATTERY]</span> Escrevendo '1' em /sys/bus/platform/drivers/ideapad_acpi/VPC2004:00/conservation_mode...
<span class="t-green">[ACPI]</span>   Limite de carregamento travado em 80%.
<span class="t-yellow">[INFO]</span>   Rapid Charge desativado automaticamente (exclusão mútua).
<span class="t-green">✔ Modo de Conservação ativado. Vida útil da bateria preservada!</span>
    `.trim(),
  };

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");

      const cmd = tab.getAttribute("data-cmd");
      if (termContent && terminalOutputs[cmd]) {
        termContent.innerHTML = terminalOutputs[cmd];
      }
    });
  });
}

/* ====================================================================
   5. ACCORDION FAQ
   ==================================================================== */
function initFaqAccordion() {
  const faqItems = document.querySelectorAll(".faq-item");

  faqItems.forEach((item) => {
    const question = item.querySelector(".faq-question");
    if (question) {
      question.addEventListener("click", () => {
        const isOpen = item.classList.contains("open");

        // Fecha outros itens
        faqItems.forEach((other) => other.classList.remove("open"));

        if (!isOpen) {
          item.classList.add("open");
        }
      });
    }
  });
}

/* ====================================================================
   6. BOTÕES DE COPIAR COM TOAST FEEDBACK
   ==================================================================== */
function initCopyButtons() {
  const copyButtons = document.querySelectorAll(".btn-copy, .btn-copy-code");

  copyButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const codeText = btn.getAttribute("data-clipboard") || 
        (btn.parentElement.querySelector("code, pre") ? btn.parentElement.querySelector("code, pre").innerText : "");

      if (codeText) {
        navigator.clipboard.writeText(codeText.trim()).then(() => {
          const originalText = btn.innerHTML;
          btn.innerHTML = `<span>✓ Copiado!</span>`;
          btn.classList.add("copied");

          showToast("📋 Comando copiado para a área de transferência!");

          setTimeout(() => {
            btn.innerHTML = originalText;
            btn.classList.remove("copied");
          }, 2200);
        });
      }
    });
  });
}

/* ====================================================================
   UTILITÁRIO: TOAST NOTIFICATION GLOBAL
   ==================================================================== */
let toastTimer = null;
function showToast(msg) {
  let toast = document.querySelector(".toast-notice");
  if (!toast) {
    toast = document.createElement("div");
    toast.className = "toast-notice";
    document.body.appendChild(toast);
  }

  toast.innerHTML = `<span>${msg}</span>`;
  toast.classList.add("show");

  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.classList.remove("show");
  }, 3200);
}
