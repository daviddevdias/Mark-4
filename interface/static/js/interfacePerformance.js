(() => {
  "use strict";
  let longTasks = 0,
    longestTask = 0;
  if (
    window.PerformanceObserver &&
    PerformanceObserver.supportedEntryTypes?.includes("longtask")
  )
    new PerformanceObserver((list) => {
      for (const item of list.getEntries()) {
        longTasks++;
        longestTask = Math.max(longestTask, item.duration);
      }
    }).observe({ entryTypes: ["longtask"] });
  // Reporta desempenho apenas local
  async function report() {
    if (document.hidden) return;
    const builds = performance.getEntriesByName("jarvis-tab-build"),
      core = window.jarvisAnimationStats || {};
    const data = {
      fps: core.fps ?? null,
      target: core.targetFps ?? 30,
      renderer: window.jarvisGpuInfo?.renderer || "Sem núcleo ativo",
      tab_ms: builds.length
        ? Math.round(builds[builds.length - 1].duration)
        : null,
      long_tasks: longTasks,
      longest_ms: Math.round(longestTask),
      config_open: document.body.classList.contains("cfg"),
    };
    window.jarvisPerformanceStats = data;
    performance.clearMeasures("jarvis-tab-build");
    performance.clearMarks("jarvis-tab-start");
    performance.clearMarks("jarvis-tab-end");
    try {
      await fetch("/interface/desempenho", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
    } catch (_) {}
    longTasks = 0;
    longestTask = 0;
  }
  setInterval(report, 5000);
  setTimeout(report, 1500);
})();
