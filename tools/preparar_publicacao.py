"""Gera ZIP dos fontes atuais, sem .git, dados privados ou arquivos ignorados."""
import argparse
import json
import subprocess
import zipfile
from pathlib import Path

from auditar_publicacao import findings

ROOT = Path(__file__).resolve().parents[1]
BLOQUEADOS = {'data','backups','interface/data','elevenlabs_eco/dados','Save','go2rtc','.tools','.venv','.git','dist','modelos_voz'}
EXTENSOES_PRIVADAS = {'.pem','.key','.pfx','.p12','.keystore','.jks','.db','.sqlite','.sqlite3','.log','.wav','.mp4','.webm','.pt','.onnx','.apk','.aab'}

def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT)

def candidatos():
    nomes=set(git('ls-files','--cached','--others','--exclude-standard','-z').decode('utf-8').split('\0'))-{''}
    entrada=b''.join(n.encode('utf-8')+b'\0' for n in sorted(nomes))
    resultado=subprocess.run(['git','check-ignore','--no-index','--stdin','-z'],input=entrada,stdout=subprocess.PIPE,cwd=ROOT,check=False)
    if resultado.returncode not in (0,1):
        raise RuntimeError('Nao foi possivel verificar o .gitignore')
    ignorados=set(resultado.stdout.decode('utf-8').split('\0'))-{''}
    for nome in sorted(nomes-ignorados):
        p=ROOT/nome
        if not p.is_file():
            continue
        if any(nome==b or nome.startswith(b+'/') for b in BLOQUEADOS):
            raise RuntimeError(f'Arquivo privado fora do ignore: {nome}')
        if p.suffix.lower() in EXTENSOES_PRIVADAS or p.name.startswith('.env') and p.name!='.env.example':
            raise RuntimeError(f'Extensao privada fora do ignore: {nome}')
        atual=ROOT
        for parte in Path(nome).parts:
            atual=atual/parte
            if atual.is_symlink() or atual.is_junction():
                raise RuntimeError(f'Link nao permitido: {nome}')
        if not p.resolve().is_relative_to(ROOT):
            raise RuntimeError(f'Caminho fora do projeto: {nome}')
        yield nome,p

def gerar(destino):
    conteudos=[]
    for nome,p in candidatos():
        dados=p.read_bytes()
        if len(dados)>10*1024*1024:
            raise RuntimeError(f'Arquivo grande inesperado: {nome}')
        if b'\0' not in dados:
            suspeitas=[a for a in findings(dados) if a['tipo'] not in {'rede_privada','email'}]
            if suspeitas:
                raise RuntimeError(f'Possivel segredo em {nome}: {suspeitas}')
        conteudos.append((nome,dados))
    destino.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destino,'x',compression=zipfile.ZIP_DEFLATED) as pacote:
        for nome,dados in conteudos:
            pacote.writestr('Mark-2/'+nome,dados)
    with zipfile.ZipFile(destino) as pacote:
        if pacote.testzip() is not None:
            raise RuntimeError('Falha na integridade do ZIP')
        if len(pacote.namelist())!=len(conteudos):
            raise RuntimeError('Quantidade de arquivos divergente')
    return {'pacote':str(destino),'arquivos':len(conteudos),'bytes':destino.stat().st_size}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--saida',type=Path,default=ROOT/'dist'/'Mark-2-github-limpo.zip')
    args=parser.parse_args()
    print(json.dumps(gerar(args.saida),ensure_ascii=False,indent=2))
