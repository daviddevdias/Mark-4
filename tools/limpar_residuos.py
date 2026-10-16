"""Remove apenas residuos conhecidos; sem --aplicar, mostra a simulacao."""
import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Nao inclui configuracoes, bancos, certificados, modelos, perfis, gravacoes
# ou o cache pago em data/elevenlabs/cache.
PASTAS_DESCARTAVEIS = ('data/temp_voz',)

def dentro_da_raiz(caminho):
    try:
        relativo = caminho.relative_to(ROOT)
        atual = ROOT
        for parte in relativo.parts:
            atual = atual / parte
            if atual.is_symlink() or atual.is_junction():
                return False
        return caminho.resolve().is_relative_to(ROOT)
    except (OSError, ValueError):
        return False


def arquivos_da_pasta(pasta):
    if not dentro_da_raiz(pasta) or not pasta.is_dir():
        return
    try:
        for item in pasta.iterdir():
            if not dentro_da_raiz(item):
                continue
            if item.is_dir():
                yield from arquivos_da_pasta(item)
            elif item.is_file():
                yield item
    except OSError:
        return


def limpar(aplicar=False):
    limite = time.time() - 86400
    candidatos = set()
    for nome in PASTAS_DESCARTAVEIS:
        for p in arquivos_da_pasta(ROOT / nome):
            if nome == 'data/temp_voz' and p.suffix.lower() != '.wav':
                continue
            candidatos.add(p)
    for base in ('comandos', 'interface', 'elevenlabs_eco', 'hud', 'tools', 'tests'):
        for p in arquivos_da_pasta(ROOT/base):
            if '__pycache__' in p.parts and p.suffix == '.pyc':
                candidatos.add(p)
    candidatos.update((ROOT/'__pycache__').glob('*.pyc'))
    grupos = {}
    erros = 0
    for p in sorted(candidatos):
        if not dentro_da_raiz(p):
            continue
        try:
            info = p.stat()
            if not p.is_file() or info.st_mtime >= limite:
                continue
            if aplicar:
                p.unlink()
            grupo = str(p.relative_to(ROOT).parent).replace('\\','/')
            item = grupos.setdefault(grupo, {'arquivos':0,'bytes':0})
            item['arquivos'] += 1
            item['bytes'] += info.st_size
        except OSError:
            erros += 1
    return {'aplicado':aplicar, 'arquivos':sum(v['arquivos'] for v in grupos.values()),
            'bytes':sum(v['bytes'] for v in grupos.values()), 'erros':erros, 'grupos':grupos}

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--aplicar',action='store_true')
    args=parser.parse_args()
    print(json.dumps(limpar(args.aplicar),ensure_ascii=False,indent=2))
