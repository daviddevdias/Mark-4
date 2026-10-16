"""Audita arquivos publicaveis e blobs do historico sem imprimir segredos."""
import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    'caminho_usuario': re.compile(r"(?:[A-Za-z]:[\\/]+(?:Users|Usuarios|Usuários)[\\/]+[^\s\x22\x27<>\\/]+|(?<![A-Za-z0-9:/])/(?:home|Users)/[^/\s\x22\x27<>]+)"),
    'hostname_tailscale': re.compile(r'\b[\w.-]+\.ts\.net\b', re.I),
    'chave_privada': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----'),
    'token_provedor': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-(?:proj-)?[A-Za-z0-9_-]{24,}|sk_[A-Za-z0-9]{32,}|AIza[0-9A-Za-z_-]{35}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{20,}|ya29\.[A-Za-z0-9_-]{25,})'),
    'credencial_url': re.compile(r'\b(?:https?|rtsps?|mqtts?)://[^\s/\x22\x27<>:@]+:[^\s/\x22\x27<>@]+@'),
    'segredo_literal': re.compile(r'''(?ix)(?:["']?)(?:api[_-]?key|client[_-]?secret|access[_-]?token|refresh[_-]?token|token[_-]?remoto|password|senha|secret[_-]?key)(?:["']?)\s*[:=]\s*(["'])([^"'\r\n]{8,})\1'''),
    'rede_privada': re.compile(r'\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3})\b'),
    'email': re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'),
}
TEXT = {'.py','.js','.css','.html','.json','.yaml','.yml','.xml','.md','.txt','.toml','.ini','.cfg','.properties','.kts','.kt','.sh','.bat','.ps1','.env','.example','.pem','.key','.log','.jsonl'}

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)

def findings(data):
    text = data.decode('utf-8', errors='replace')
    found = []
    for kind, pattern in PATTERNS.items():
        for m in pattern.finditer(text):
            if kind == 'segredo_literal':
                value = m.group(2)
                if value in {'lm-studio', 'ollama'}:
                    continue
                if re.search(r'(?i)(?:exemplo|example|teste|test|sua_|seu_|dummy|fake|placeholder|change.?me|token_|nao-|invalido|errado)', value):
                    continue
                if any(c in value for c in '{}<>'):
                    continue
            if kind == 'email' and re.search(r'(?i)(?:example\.(?:com|org)|exemplo\.(?:com|com\.br)|android\.com|jetbrains\.com|gradle\.org|w3\.org|schemas\.)',m.group()):
                continue
            found.append({'tipo':kind, 'linha':text.count('\n',0,m.start())+1})
    return found

def audit(history=False):
    tracked = set(git('ls-files','-z').decode().split('\0')) - {''}
    new = set(git('ls-files','--others','--exclude-standard','-z').decode().split('\0')) - {''}
    report = {'arquivos_verificados':0, 'achados':[], 'arquivos_grandes':[], 'ignorados_rastreados':git('ls-files','-ci','--exclude-standard').decode().splitlines()}
    for name in sorted(tracked | new):
        p = ROOT / name
        if not p.is_file():
            continue
        size = p.stat().st_size
        if size > 5 * 1024 * 1024:
            report['arquivos_grandes'].append({'arquivo':name,'bytes':size})
        if size > 10 * 1024 * 1024 or (p.suffix.lower() not in TEXT and p.name not in {'.gitignore','.gitattributes','gradlew'}):
            continue
        report['arquivos_verificados'] += 1
        for item in findings(p.read_bytes()):
            report['achados'].append({'arquivo':name, **item})
    if history:
        objects = git('rev-list','--objects','--all').decode(errors='replace').splitlines()
        report['historico'] = []
        blobs = 0
        proc = subprocess.Popen(['git','cat-file','--batch'],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
        try:
            for entry in objects:
                oid, _, name = entry.partition(' ')
                proc.stdin.write((oid+'\n').encode());proc.stdin.flush()
                header = proc.stdout.readline().split()
                if len(header)!=3:
                    continue
                size = int(header[2]);data = proc.stdout.read(size);proc.stdout.read(1)
                if header[1] != b'blob':
                    continue
                blobs += 1
                if name.startswith(('data/','interface/data/')) or name.endswith(('.pem','.key','.keystore','local.properties')):
                    report['historico'].append({'arquivo':name,'objeto':oid[:12],'tipo':'arquivo_privado_no_historico'})
                if size <= 5*1024*1024 and (Path(name).suffix.lower() in TEXT or name in {'.gitignore','.gitattributes'}):
                    for item in findings(data):
                        report['historico'].append({'arquivo':name,'objeto':oid[:12], **item})
        finally:
            proc.stdin.close();proc.wait()
        report['blobs_historicos_verificados'] = blobs
    return report

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--historico',action='store_true')
    args = parser.parse_args()
    result = audit(args.historico)
    print(json.dumps(result,ensure_ascii=False,indent=2))
