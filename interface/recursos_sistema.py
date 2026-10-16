from collections import deque
import threading
import time
import psutil

TRAVA = threading.Lock()
CACHE = {"tempo": 0, "dados": None}
HISTORICO = deque(maxlen=120)


def consultar(gpu):
    with TRAVA:
        agora = time.monotonic()
        if CACHE["dados"] and agora-CACHE["tempo"]<5:
            return CACHE["dados"]
        processos=[]
        nucleos=max(1,psutil.cpu_count() or 1)
        for processo in psutil.process_iter(["pid","name","memory_info"]):
            try:
                info=dict(processo.info)
                memoria=info.get("memory_info")
                if memoria is None: memoria=processo.memory_info()
                cpu=processo.cpu_percent(None)/nucleos
                processos.append({"nome":info.get("name") or "Processo","cpu":round(cpu,1),"ram_mb":round(memoria.rss/2**20)})
            except (psutil.Error,OSError,AttributeError,KeyError,TypeError):
                continue
        memoria = psutil.virtual_memory()
        tempos = psutil.cpu_times()._asdict()
        total = sum(v for k, v in tempos.items() if k not in {"guest", "guest_nice"})
        ocioso = tempos.get("idle", 0) + tempos.get("iowait", 0)
        anterior = CACHE.get("cpu_tempos") if CACHE["tempo"] else None
        cpu = psutil.cpu_percent(None)
        if anterior and total > anterior[0]:
            cpu = round(max(0, min(100, 100*(1-(ocioso-anterior[1])/(total-anterior[0])))), 1)
        CACHE["cpu_tempos"] = (total, ocioso)
        HISTORICO.append({"hora": time.time(), "cpu": cpu, "ram": memoria.percent})
        dados = {
            "cpu": cpu, "ram": memoria.percent, "gpu": gpu() if callable(gpu) else None,
            "atualizado_em": time.time(),
            "ram_disponivel_mb": round(getattr(memoria, "available", 0)/2**20),
            "pressao_memoria": "alta" if memoria.percent >= 90 else "atencao" if memoria.percent >= 80 else "normal",
            "processos": sorted(processos, key=lambda p: (p["cpu"], p["ram_mb"]), reverse=True)[:8],
            "processos_memoria": sorted(processos, key=lambda p: p["ram_mb"], reverse=True)[:8],
            "historico": list(HISTORICO),
        }
        CACHE.update(tempo=agora,dados=dados)
        return dados
