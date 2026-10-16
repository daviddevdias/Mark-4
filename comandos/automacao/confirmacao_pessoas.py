"""Confirmações espaciais em quadros distintos, sem duplicar evidência."""
import math

class ConfirmadorPessoas:
    def __init__(self, minimo=3, validade=1.5):
        self.minimo = max(3, minimo)
        self.validade = validade
        self.trilhas = []
        self.ultimo = None

    @staticmethod
    def sobreposicao(a, b):
        area = lambda p: max(0, p["x2"]-p["x1"])*max(0, p["y2"]-p["y1"])
        inter = max(0,min(a["x2"],b["x2"])-max(a["x1"],b["x1"]))*max(0,min(a["y2"],b["y2"])-max(a["y1"],b["y1"]))
        return inter/max(1e-9,area(a)+area(b)-inter)

    def atualizar(self, poses, instante):
        # Reprocessar o mesmo quadro nunca aumenta a confiança temporal.
        if not math.isfinite(instante) or (self.ultimo is not None and instante <= self.ultimo):
            return []
        self.ultimo = instante
        antigas = [t for t in self.trilhas if instante-t["ts"] <= self.validade]
        novas, usados, saida = [], set(), []
        for pose in poses:
            candidatos = [(self.sobreposicao(pose,t["pose"]),i,t) for i,t in enumerate(antigas) if i not in usados]
            score,i,trilha = max(candidatos,key=lambda x:x[0],default=(0,-1,None))
            contagem = 1
            if score >= .25:
                usados.add(i);contagem = trilha["n"]+1
            resultado = dict(pose, confirmada=contagem>=self.minimo, quadros_confirmacao=contagem)
            saida.append(resultado);novas.append({"pose":pose,"ts":instante,"n":contagem})
        self.trilhas = novas
        return saida
