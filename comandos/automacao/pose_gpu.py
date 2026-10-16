"""Pose acelerada por DirectML."""

from pathlib import Path


class PoseDirectML:

    def __init__(self, caminho):
        import onnxruntime as ort

        if "DmlExecutionProvider" not in ort.get_available_providers():
            raise RuntimeError("DirectML não está disponível")
        opcoes = ort.SessionOptions()
        opcoes.enable_mem_pattern = False
        opcoes.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        opcoes.intra_op_num_threads = 2
        self.sessao = ort.InferenceSession(
            str(Path(caminho)),
            sess_options=opcoes,
            providers=[
                ("DmlExecutionProvider", {"device_id": 0}),
                "CPUExecutionProvider",
            ],
        )
        if self.sessao.get_providers()[0] != "DmlExecutionProvider":
            raise RuntimeError("GPU não foi inicializada")
        self.entrada = self.sessao.get_inputs()[0]
        self.tamanho = tuple(self.entrada.shape[2:])

    # Infere pessoas com a GPU
    def predict(
        self, quadro, imgsz=640, conf=0.5, classes=None, max_det=50, verbose=False
    ):
        import cv2
        import numpy as np
        from types import SimpleNamespace

        altura, largura = quadro.shape[:2]
        destinoH, destinoW = self.tamanho
        ganho = min(destinoH / altura, destinoW / largura)
        novaW, novaH = round(largura * ganho), round(altura * ganho)
        padX, padY = (destinoW - novaW) / 2, (destinoH - novaH) / 2
        imagem = (
            cv2.resize(quadro, (novaW, novaH))
            if (novaW, novaH) != (largura, altura)
            else quadro
        )
        imagem = cv2.copyMakeBorder(
            imagem,
            round(padY - 0.1),
            round(padY + 0.1),
            round(padX - 0.1),
            round(padX + 0.1),
            cv2.BORDER_CONSTANT,
            value=(114, 114, 114),
        )
        entrada = (
            np.ascontiguousarray(
                imagem[:, :, ::-1].transpose(2, 0, 1)[None], dtype=np.float32
            )
            / 255.0
        )
        bruto = self.sessao.run(None, {self.entrada.name: entrada})[0][0].T
        validos = (
            np.isfinite(bruto).all(axis=1)
            & (bruto[:, 4] > conf)
            & (bruto[:, 4] <= 1)
            & (bruto[:, 2] > 0)
            & (bruto[:, 3] > 0)
        )
        candidatos = bruto[validos].copy()
        if classes is not None and 0 not in classes:
            candidatos = candidatos[:0]
        caixas = candidatos[:, :4].copy()
        caixas[:, :2] -= candidatos[:, 2:4] / 2
        caixas[:, 2:4] = caixas[:, :2] + candidatos[:, 2:4]
        ordem = candidatos[:, 4].argsort()[::-1][:30000]
        escolhidos = []
        area = np.maximum(caixas[:, 2:] - caixas[:, :2], 0).prod(axis=1)
        while len(ordem) and len(escolhidos) < max_det:
            indice = ordem[0]
            escolhidos.append(indice)
            demais = ordem[1:]
            inicio = np.maximum(caixas[indice, :2], caixas[demais, :2])
            fim = np.minimum(caixas[indice, 2:], caixas[demais, 2:])
            intersecao = np.maximum(fim - inicio, 0).prod(axis=1)
            iou = intersecao / np.maximum(
                area[indice] + area[demais] - intersecao, 1e-7
            )
            ordem = demais[iou <= 0.45]
        ganhoX, ganhoY = novaW / largura, novaH / altura
        caixas = caixas[escolhidos]
        pontos = candidatos[escolhidos, 5:].reshape(-1, 17, 3)
        caixas[:, [0, 2]] = np.clip(
            (caixas[:, [0, 2]] - round(padX - 0.1)) / ganhoX, 0, largura
        )
        caixas[:, [1, 3]] = np.clip(
            (caixas[:, [1, 3]] - round(padY - 0.1)) / ganhoY, 0, altura
        )
        pontos[:, :, 0] = np.clip(
            (pontos[:, :, 0] - round(padX - 0.1)) / ganhoX, 0, largura
        )
        pontos[:, :, 1] = np.clip(
            (pontos[:, :, 1] - round(padY - 0.1)) / ganhoY, 0, altura
        )
        return [
            SimpleNamespace(
                boxes=SimpleNamespace(xyxy=caixas, conf=candidatos[escolhidos, 4]),
                keypoints=SimpleNamespace(data=pontos),
            )
        ]
