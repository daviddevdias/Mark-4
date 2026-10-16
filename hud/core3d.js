// Usa núcleo do HTML enviado
(function initJarvisCore() {
  const canvas = document.getElementById("three-canvas");
  const renderer = new THREE.WebGLRenderer({
    antialias: false,
    powerPreference: "high-performance",
    canvas,
    alpha: false,
  });
  let lastInteraction = 0;
  document.addEventListener(
    "pointermove",
    () => {
      lastInteraction = performance.now();
    },
    { passive: true },
  );
  const targetFps = () =>
    document.body.classList.contains("economy-mode") ||
    matchMedia("(prefers-reduced-motion: reduce)").matches
      ? 30
      : sphereState === "SPEAKING" || performance.now() - lastInteraction < 900
        ? 45
        : 30;
  const gl = renderer.getContext(),
    info = gl.getExtension("WEBGL_debug_renderer_info");
  window.jarvisGpuInfo = {
    renderer: info
      ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL)
      : gl.getParameter(gl.RENDERER),
  };
  let lastFrameTime = null;
  // Ajusta resolução até Full HD
  function ajustarResolucao() {
    const ratio = Math.min(
      window.devicePixelRatio || 1,
      1920 / window.innerWidth,
      1080 / window.innerHeight,
    );
    renderer.setPixelRatio(ratio);
    renderer.setSize(window.innerWidth, window.innerHeight);
  }
  ajustarResolucao();
  renderer.setClearColor(0x0c1016, 1);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(
    48,
    window.innerWidth / window.innerHeight,
    1,
    4000,
  );
  camera.position.set(0, 0, 640);

  // Cria textura das partículas
  function makeParticleTex(size) {
    const c = document.createElement("canvas");
    c.width = c.height = size;
    const ctx = c.getContext("2d");
    const g = ctx.createRadialGradient(
      size / 2,
      size / 2,
      0,
      size / 2,
      size / 2,
      size / 2,
    );
    g.addColorStop(0, "rgba(255,255,255,1)");
    g.addColorStop(0.28, "rgba(255,255,255,0.88)");
    g.addColorStop(0.55, "rgba(255,255,255,0.24)");
    g.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size, size);
    return new THREE.CanvasTexture(c);
  }
  // Cria textura do brilho
  function makeGlowTex(size) {
    const c = document.createElement("canvas");
    c.width = c.height = size;
    const ctx = c.getContext("2d");
    const g = ctx.createRadialGradient(
      size / 2,
      size / 2,
      0,
      size / 2,
      size / 2,
      size / 2,
    );
    g.addColorStop(0, "rgba(255,255,255,0.55)");
    g.addColorStop(0.4, "rgba(255,255,255,0.18)");
    g.addColorStop(0.75, "rgba(255,255,255,0.05)");
    g.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size, size);
    return new THREE.CanvasTexture(c);
  }

  const PT = makeParticleTex(32);
  const GT = makeGlowTex(512);
  const GT2 = makeGlowTex(256);

  const bgGlowMat = new THREE.SpriteMaterial({
    map: GT,
    color: new THREE.Color(0x32165f),
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    opacity: 0.68,
  });
  const bgGlow = new THREE.Sprite(bgGlowMat);
  bgGlow.scale.set(1240, 1240, 1);
  bgGlow.position.z = -160;
  scene.add(bgGlow);

  const goldMat = new THREE.SpriteMaterial({
    map: GT2,
    color: new THREE.Color(0xd247ff),
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    opacity: 0,
  });
  const goldGlow = new THREE.Sprite(goldMat);
  goldGlow.scale.set(720, 720, 1);
  scene.add(goldGlow);

  const sphereGroup = new THREE.Group();
  scene.add(sphereGroup);

  // Alinha esfera ao painel atual
  function alinharNucleoAoPainel() {
    const centro = document.getElementById("center").getBoundingClientRect();
    const diameter =
      (330 * window.innerHeight) /
      (2 * Math.tan((camera.fov * Math.PI) / 360) * camera.position.z);
    sphereGroup.scale.setScalar(
      Math.min(
        1,
        (window.innerWidth * 0.82) / diameter,
        (window.innerHeight * 0.64) / diameter,
        document.body.classList.contains("widget-screen")
          ? (Math.min(centro.width, centro.height) * 0.74) / diameter
          : 1,
      ),
    );
    const altura =
      2 * camera.position.z * Math.tan((camera.fov * Math.PI) / 360);
    sphereGroup.position.x =
      ((centro.left + centro.width / 2 - window.innerWidth / 2) *
        altura *
        camera.aspect) /
      window.innerWidth;
    sphereGroup.position.y =
      (-(centro.top + centro.height / 2 - window.innerHeight / 2) * altura) /
        window.innerHeight +
      34;
    bgGlow.position.x = goldGlow.position.x = sphereGroup.position.x;
    bgGlow.position.y = goldGlow.position.y = sphereGroup.position.y;
  }
  alinharNucleoAoPainel();

  const R = 150;
  const N_SM = 12000;
  const N_BG = 3000;

  // Distribui pontos na esfera
  function fibSphere(n, radius) {
    const pos = new Float32Array(n * 3);
    const golden = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < n; i++) {
      const y = 1 - (i / (n - 1)) * 2;
      const rho = Math.sqrt(Math.max(0, 1 - y * y));
      const th = golden * i;
      pos[i * 3] = Math.cos(th) * rho * radius;
      pos[i * 3 + 1] = y * radius;
      pos[i * 3 + 2] = Math.sin(th) * rho * radius;
    }
    return pos;
  }

  const baseSM = fibSphere(N_SM, R);
  const baseBG = fibSphere(N_BG, R);
  const curSM = baseSM.slice();
  const curBG = baseBG.slice();
  const velSM = new Float32Array(N_SM * 3);
  const velBG = new Float32Array(N_BG * 3);
  const phaseSM = Float32Array.from(
    { length: N_SM },
    () => Math.random() * Math.PI * 2,
  );
  const phaseBG = Float32Array.from(
    { length: N_BG },
    () => Math.random() * Math.PI * 2,
  );

  // Guarda cálculos fixos das ondas
  function prepararFases(base, phase) {
    phase.sin = Float64Array.from(phase, Math.sin);
    phase.cos = Float64Array.from(phase, Math.cos);
    phase.surfaceSin = new Float64Array(phase.length);
    phase.surfaceCos = new Float64Array(phase.length);
    for (let i = 0; i < phase.length; i++) {
      const angle = base[i * 3] * 0.08 + base[i * 3 + 1] * 0.08;
      phase.surfaceSin[i] = Math.sin(angle);
      phase.surfaceCos[i] = Math.cos(angle);
    }
  }
  prepararFases(baseSM, phaseSM);
  prepararFases(baseBG, phaseBG);

  const colSM = new Float32Array(N_SM * 3);
  const colBG = new Float32Array(N_BG * 3);

  // Atualiza a luz das partículas
  function recomputeColors(
    base,
    col,
    N,
    Lx,
    Ly,
    Lz,
    litR,
    litG,
    litB,
    shadR,
    shadG,
    shadB,
  ) {
    for (let i = 0; i < N; i++) {
      const nx = base[i * 3] / R,
        ny = base[i * 3 + 1] / R,
        nz = base[i * 3 + 2] / R;
      const lit = Math.max(0, nx * Lx + ny * Ly + nz * Lz);
      if (veronicaArmed) {
        col[i * 3] = shadR + (litR - shadR) * lit;
        col[i * 3 + 1] = shadG + (litG - shadG) * lit;
        col[i * 3 + 2] = shadB + (litB - shadB) * lit;
        continue;
      }
      // Faixas fluidas ciano e magenta sobre uma base violeta profunda.
      const flow = Math.sin(nx * 4.2 + ny * 3.4 - nz * 2.8);
      const cyan = Math.max(0, flow);
      const magenta = Math.max(0, -flow);
      const ridge = Math.pow(Math.max(0, Math.cos(nx * 7 - ny * 5 + nz * 3)), 12);
      const light = 0.34 + lit * 0.58;
      col[i * 3] = Math.min(1, (0.11 + magenta * 0.32 + cyan * 0.035) * light + ridge * (0.55 + magenta * 0.4));
      col[i * 3 + 1] = Math.min(1, (0.025 + magenta * 0.035 + cyan * 0.42) * light + ridge * (0.24 + cyan * 0.6));
      col[i * 3 + 2] = Math.min(1, (0.34 + magenta * 0.48 + cyan * 0.36) * light + ridge * 0.72);
    }
  }

  const geoSM = new THREE.BufferGeometry();
  const attrPosSM = new THREE.BufferAttribute(curSM, 3);
  const attrColSM = new THREE.BufferAttribute(colSM, 3);
  geoSM.setAttribute("position", attrPosSM);
  geoSM.setAttribute("color", attrColSM);

  const geoBG = new THREE.BufferGeometry();
  const attrPosBG = new THREE.BufferAttribute(curBG, 3);
  const attrColBG = new THREE.BufferAttribute(colBG, 3);
  geoBG.setAttribute("position", attrPosBG);
  geoBG.setAttribute("color", attrColBG);

  const matSM = new THREE.PointsMaterial({
    size: 3.5,
    map: PT,
    vertexColors: true,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    sizeAttenuation: true,
    opacity: 0.95,
  });
  const matBG = new THREE.PointsMaterial({
    size: 8.5,
    map: PT,
    vertexColors: true,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    sizeAttenuation: true,
    opacity: 0.75,
  });

  sphereGroup.add(new THREE.Points(geoSM, matSM));
  sphereGroup.add(new THREE.Points(geoBG, matBG));

  const STATES = {
    IDLE: {
      Lx: -0.5, Ly: 0.68, Lz: 0.54,
      litR: 0.68, litG: 0.48, litB: 0.92,
      shadR: 0.18, shadG: 0.08, shadB: 0.36,
      rotY: 0.0018, bAmp: 0.01, bFreq: 0.38, wAmp: 0.004, wFreq: 0.2,
      goldOp: 0.68, bgCol: 0x4e128b, bgOp: 0.78,
    },
    LISTENING: {
      Lx: -0.42, Ly: 0.78, Lz: 0.42,
      litR: 0.76, litG: 0.63, litB: 0.98,
      shadR: 0.24, shadG: 0.11, shadB: 0.48,
      rotY: 0.0038, bAmp: 0.024, bFreq: 1.8, wAmp: 0.011, wFreq: 0.65,
      goldOp: 0.78, bgCol: 0x6422a3, bgOp: 0.82,
    },
    THINKING: {
      Lx: 0.48, Ly: 0.62, Lz: 0.62,
      litR: 0.68, litG: 0.48, litB: 0.92,
      shadR: 0.18, shadG: 0.07, shadB: 0.38,
      rotY: 0.0105, bAmp: 0.012, bFreq: 1.4, wAmp: 0.008, wFreq: 0.95,
      goldOp: 0.84, bgCol: 0x5a129a, bgOp: 0.78,
    },
    SPEAKING: {
      Lx: 0.0, Ly: 0.8, Lz: 0.8,
      litR: 0.78, litG: 0.64, litB: 0.98,
      shadR: 0.25, shadG: 0.1, shadB: 0.48,
      rotY: 0.006, bAmp: 0.05, bFreq: 5.0, wAmp: 0.02, wFreq: 2.0,
      goldOp: 0.95, bgCol: 0x7320b0, bgOp: 0.86,
    },
  };
  const ARMED_STATES = Object.fromEntries(
    Object.entries(STATES).map(([name, state]) => [
      name,
      {
        ...state,
        litR: 1,
        litG: 0.18,
        litB: 0.2,
        shadR: 0.28,
        shadG: 0.015,
        shadB: 0.025,
        bgCol: 0xd51e32,
      },
    ]),
  );

  const plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
  const _ray = new THREE.Raycaster();
  const m2d = new THREE.Vector2();
  const hit = new THREE.Vector3();
  const worldMouse = new THREE.Vector3(9999, 9999, 9999);
  const localMouse = new THREE.Vector3();
  let mousePending = false;

  const INFLUENCE_R = 115;
  const PUSH_STR = 4.0;
  const SPRING_K = 0.032;
  const DAMPING = 0.93;

  window.addEventListener("mousemove", (e) => {
    m2d.x = (e.clientX / window.innerWidth) * 2 - 1;
    m2d.y = -(e.clientY / window.innerHeight) * 2 + 1;
    mousePending = true;
  });

  window.addEventListener("mouseout", (event) => {
    if (!event.relatedTarget) {
      mousePending = false;
      worldMouse.set(9999, 9999, 9999);
    }
  });
  var sphereState = "IDLE";
  let veronicaArmed = false,
    prevVeronicaArmed = false;
  let animationFrame = null;
  let framesMedidos = 0,
    inicioMedicao = performance.now();
  const threeClock = new THREE.Clock();
  let elapsed = 0;
  let prevState = "";

  // Move partículas com mola e mouse
  function stepParticles(
    base,
    cur,
    vel,
    phase,
    N,
    C,
    t,
    mlx,
    mly,
    mlz,
    breathOff,
    IR2,
    S,
    voiceScale,
  ) {
    const isSpeaking = S === "SPEAKING";

    const currentDamping = isSpeaking ? 0.6 : DAMPING;
    const waveSin = Math.sin(t * C.wFreq),
      waveCos = Math.cos(t * C.wFreq);
    const surfaceSin = Math.sin(t * 25),
      surfaceCos = Math.cos(t * 25);

    for (let i = 0; i < N; i++) {
      const i3 = i * 3;
      const bx = base[i3],
        by = base[i3 + 1],
        bz = base[i3 + 2];

      const surfaceStrength = isSpeaking ? 0.13 : S === "LISTENING" ? 0.08 : 0.045;
      const surfaceDistortion =
        (phase.surfaceSin[i] * surfaceCos +
          phase.surfaceCos[i] * surfaceSin) *
        surfaceStrength;

      const shimmer =
        (phase.sin[i] * waveCos + phase.cos[i] * waveSin) * C.wAmp;

      const r = 1 + breathOff + shimmer + voiceScale + surfaceDistortion;

      const tx = bx * r;
      const ty = by * r;
      const tz = bz * r;

      let fx = (tx - cur[i3]) * SPRING_K;
      let fy = (ty - cur[i3 + 1]) * SPRING_K;
      let fz = (tz - cur[i3 + 2]) * SPRING_K;

      const dx = cur[i3] - mlx,
        dy = cur[i3 + 1] - mly,
        dz = cur[i3 + 2] - mlz;
      const d2 = dx * dx + dy * dy + dz * dz;
      if (d2 < IR2 && d2 > 0.01) {
        const d = Math.sqrt(d2);
        const str = (PUSH_STR * (1 - d / INFLUENCE_R)) / d;
        fx += dx * str;
        fy += dy * str;
        fz += dz * str;
      }

      vel[i3] = (vel[i3] + fx) * currentDamping;
      vel[i3 + 1] = (vel[i3 + 1] + fy) * currentDamping;
      vel[i3 + 2] = (vel[i3 + 2] + fz) * currentDamping;

      cur[i3] += vel[i3];
      cur[i3 + 1] += vel[i3 + 1];
      cur[i3 + 2] += vel[i3 + 2];
    }
  }

  // Confere visibilidade do núcleo
  function coreVisible() {
    return (
      !document.hidden &&
      !["cfg", "modal-open", "chat-expanded", "core-disabled"].some((name) =>
        document.body.classList.contains(name),
      )
    );
  }
  // Pausa animação fora da vista
  function syncAnimation() {
    if (!coreVisible()) {
      if (animationFrame !== null) cancelAnimationFrame(animationFrame);
      animationFrame = null;
      window.jarvisAnimationStats = {
        fps: 0,
        targetFps: targetFps(),
        paused: true,
        width: canvas.width,
        height: canvas.height,
      };
    } else if (animationFrame === null) {
      threeClock.getDelta();
      lastFrameTime = null;
      framesMedidos = 0;
      inicioMedicao = performance.now();
      animationFrame = requestAnimationFrame(animateSphere);
    }
  }
  // Anima esfera e reação ao mouse
  function animateSphere(timestamp) {
    animationFrame = null;
    if (!coreVisible()) return;
    animationFrame = requestAnimationFrame(animateSphere);
    const FRAME_INTERVAL = 1000 / targetFps();
    if (lastFrameTime !== null) {
      const gap = timestamp - lastFrameTime;
      if (gap < FRAME_INTERVAL - 0.25) return;
      lastFrameTime =
        timestamp - (gap >= FRAME_INTERVAL ? gap % FRAME_INTERVAL : 0);
    } else lastFrameTime = timestamp;
    if (mousePending) {
      _ray.setFromCamera(m2d, camera);
      if (_ray.ray.intersectPlane(plane, hit)) worldMouse.copy(hit);
      mousePending = false;
    }
    const dt = Math.min(threeClock.getDelta(), 0.05);
    elapsed += dt;
    const t = elapsed;
    const S = sphereState;
    const C = (veronicaArmed ? ARMED_STATES : STATES)[S] || STATES.IDLE;

    if (S !== prevState || veronicaArmed !== prevVeronicaArmed) {
      recomputeColors(
        baseSM,
        colSM,
        N_SM,
        C.Lx,
        C.Ly,
        C.Lz,
        C.litR,
        C.litG,
        C.litB,
        C.shadR,
        C.shadG,
        C.shadB,
      );
      recomputeColors(
        baseBG,
        colBG,
        N_BG,
        C.Lx,
        C.Ly,
        C.Lz,
        C.litR,
        C.litG,
        C.litB,
        C.shadR,
        C.shadG,
        C.shadB,
      );
      attrColSM.needsUpdate = true;
      attrColBG.needsUpdate = true;
      bgGlowMat.color.set(C.bgCol);
      prevState = S;
      prevVeronicaArmed = veronicaArmed;
    }

    sphereGroup.rotation.y +=
      C.rotY * (window._sphereRotationMultiplier ?? 1.0);

    sphereGroup.updateMatrixWorld(true);
    localMouse.copy(worldMouse);
    sphereGroup.worldToLocal(localMouse);
    const mlx = localMouse.x,
      mly = localMouse.y,
      mlz = localMouse.z;

    const breathOff = Math.sin(t * C.bFreq) * C.bAmp;
    const IR2 = INFLUENCE_R * INFLUENCE_R;

    let voiceScale = 0;
    if (S === "SPEAKING") {
      const wave1 = Math.sin(t * 22.0);
      const wave2 = Math.sin(t * 38.0 + 1.5);
      const wave3 = Math.sin(t * 14.0 + 0.5);
      const combined = wave1 * 0.5 + wave2 * 0.3 + wave3 * 0.2;

      voiceScale = combined > 0 ? combined * 0.45 : combined * 0.15;
    }

    stepParticles(
      baseSM,
      curSM,
      velSM,
      phaseSM,
      N_SM,
      C,
      t,
      mlx,
      mly,
      mlz,
      breathOff,
      IR2,
      S,
      voiceScale,
    );
    stepParticles(
      baseBG,
      curBG,
      velBG,
      phaseBG,
      N_BG,
      C,
      t,
      mlx,
      mly,
      mlz,
      breathOff,
      IR2,
      S,
      voiceScale,
    );

    attrPosSM.needsUpdate = true;
    attrPosBG.needsUpdate = true;

    const pulseGlow = S === "SPEAKING" ? voiceScale * 1.5 : 0;
    bgGlowMat.opacity = Math.min(1, C.bgOp + Math.sin(t * 0.72) * 0.05 + pulseGlow * 0.35);
    goldMat.opacity =
      Math.min(0.95, C.goldOp * (0.72 + 0.12 * Math.sin(t * 2.6)) + pulseGlow * 0.35);

    renderer.render(scene, camera);
    framesMedidos++;
    const agora = performance.now();
    if (agora - inicioMedicao >= 1000) {
      window.jarvisAnimationStats = {
        fps: Math.round((framesMedidos * 1000) / (agora - inicioMedicao)),
        targetFps: targetFps(),
        paused: false,
        width: canvas.width,
        height: canvas.height,
      };
      framesMedidos = 0;
      inicioMedicao = agora;
    }
  }
  document.addEventListener("visibilitychange", syncAnimation);
  new MutationObserver(syncAnimation).observe(document.body, {
    attributes: true,
    attributeFilter: ["class"],
  });
  syncAnimation();

  window.addEventListener("resize", () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    ajustarResolucao();
    alinharNucleoAoPainel();
  });

  window.addEventListener("transitionend", alinharNucleoAoPainel, true);
  if (window.ResizeObserver)
    new ResizeObserver(alinharNucleoAoPainel).observe(
      document.getElementById("center"),
    );
  // Recebe estado real da conversa
  window.setJarvisCoreState = (next) => {
    if (STATES[next]) sphereState = next;
  };

  window.setJarvisVeronicaArmed = (armed) => {
    veronicaArmed = !!armed;
  };
})();
