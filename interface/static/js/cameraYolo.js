(() => {
  "use strict";
  window.createJarvisYoloOverlay = (host, video, player) => {
    const canvas = document.createElement("canvas"),
      badge = document.createElement("span"),
      toggle = document.createElement("button");
    canvas.className = "camera-yolo";
    badge.className = "camera-yolo-status";
    toggle.className = "camera-tool";
    toggle.textContent = "YOLO";
    toggle.setAttribute("aria-pressed", "true");
    toggle.title = "Mostrar detecção de pessoas e articulações";
    host.append(canvas, badge);
    host.querySelector(".camera-tools")?.append(toggle);
    let closed = false,
      enabled = true,
      visible = true,
      timer = 0,
      controller = null,
      last = null,
      receivedAt = 0;
    const pairs = [
      [5, 6],
      [5, 7],
      [7, 9],
      [6, 8],
      [8, 10],
      [5, 11],
      [6, 12],
      [11, 12],
      [11, 13],
      [13, 15],
      [12, 14],
      [14, 16],
    ];
    const ctx = canvas.getContext("2d");
    function draw() {
      const w = host.clientWidth,
        h = host.clientHeight;
      canvas.width = w;
      canvas.height = h;
      if (
        !enabled ||
        !last ||
        Date.now() - receivedAt > 1800 ||
        last.idade_deteccao_s > 1.8
      ) {
        badge.textContent = enabled
          ? "YOLO · aguardando análise"
          : "YOLO oculto";
        return;
      }
      if (player.configuracao.lente === "cima") {
        badge.textContent = "YOLO disponível na lente inferior";
        return;
      }
      const image = host.querySelector(".camera-preview");
      const ratio = image ? image.naturalWidth / image.naturalHeight : w / h;
      const vw = image ? Math.min(w, h * ratio) : w,
        vh = image ? vw / ratio : h,
        ox = (w - vw) / 2,
        oy = (h - vh) / 2;
      const poses = last.poses || [];
      badge.textContent = `YOLO · ${poses.filter((p) => p.confirmada !== false).length} pessoa(s) · ${Math.round((last.idade_deteccao_s || 0) * 1000)} ms`;
      for (const p of poses) {
        const color = p.confirmada === false ? "#000000" : "#57f4c2";
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = 2;
        const x = ox + p.x1 * vw,
          y = oy + p.y1 * vh;
        ctx.strokeRect(x, y, (p.x2 - p.x1) * vw, (p.y2 - p.y1) * vh);
        const label =
          (p.confirmada === false ? "Confirmando" : "Pessoa") +
          " · " +
          Math.round((p.confianca || 0) * 100) +
          "%";
        ctx.font = "12px system-ui";
        const tw = ctx.measureText(label).width + 12;
        ctx.fillStyle = "#05141ee8";
        ctx.fillRect(x, Math.max(0, y - 23), tw, 22);
        ctx.fillStyle = color;
        ctx.fillText(label, x + 6, Math.max(15, y - 7));
        for (const [a, b] of pairs) {
          const k = p.keypoints || [],
            a1 = k[a],
            b1 = k[b];
          if (!a1 || !b1 || a1[2] < 0.35 || b1[2] < 0.35) continue;
          ctx.beginPath();
          ctx.moveTo(ox + a1[0] * vw, oy + a1[1] * vh);
          ctx.lineTo(ox + b1[0] * vw, oy + b1[1] * vh);
          ctx.stroke();
        }
      }
    }
    async function poll() {
      if (closed) return;
      if (enabled && visible && !document.hidden) {
        controller = new AbortController();
        const deadline = setTimeout(() => controller.abort(), 3000);
        try {
          const r = await fetch("/seguranca/hud", {
            cache: "no-store",
            signal: controller.signal,
          });
          if (!r.ok) throw Error();
          last = await r.json();
          receivedAt = Date.now();
        } catch {
          last = null;
        } finally {
          clearTimeout(deadline);
          if (!closed) draw();
        }
      } else {
        last = null;
        draw();
      }
      if (!closed)
        timer = setTimeout(
          poll,
          document.body.classList.contains("economy-mode") ? 1000 : 350,
        );
    }
    toggle.onclick = () => {
      enabled = !enabled;
      toggle.setAttribute("aria-pressed", String(enabled));
      draw();
    };
    const observer = new IntersectionObserver((e) => {
      visible = e[0].isIntersecting;
      if (!visible) controller?.abort();
    });
    observer.observe(host);
    const resize = new ResizeObserver(draw);
    resize.observe(host);
    poll();
    return {
      close() {
        closed = true;
        clearTimeout(timer);
        controller?.abort();
        observer.disconnect();
        resize.disconnect();
        canvas.remove();
        badge.remove();
        toggle.remove();
      },
    };
  };
})();
