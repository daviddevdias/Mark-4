
import ipaddress
import json
import logging
import shutil
import socket
import subprocess
from datetime import datetime, timedelta, timezone

import config

log = logging.getLogger("mark2.https_local")

DIR_CERTIFICADO = config.DATA_DIR / "certificado_https"
ARQ_CERT = DIR_CERTIFICADO / "cert.pem"
ARQ_CHAVE = DIR_CERTIFICADO / "chave.pem"

VALIDADE_DIAS = 397





def caminho_tailscale():
    return shutil.which("tailscale") or shutil.which("tailscale.exe")





def hostname_tailscale(tailscale):
    try:
        saida = subprocess.run(
            [tailscale, "status", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        dados = json.loads(saida.stdout)
        nome = (dados.get("Self") or {}).get("DNSName", "").rstrip(".")
        return nome or None
    except Exception:
        log.debug("Não foi possível ler o status do Tailscale.", exc_info=True)
        return None





def tentar_certificado_tailscale():
    tailscale = caminho_tailscale()
    if not tailscale:
        return None
    hostname = hostname_tailscale(tailscale)
    if not hostname:
        return None
    try:
        DIR_CERTIFICADO.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                tailscale,
                "cert",
                "--cert-file",
                str(ARQ_CERT),
                "--key-file",
                str(ARQ_CHAVE),
                hostname,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        if ARQ_CERT.exists() and ARQ_CHAVE.exists():
            log.info("Certificado HTTPS obtido via Tailscale para %s.", hostname)
            return (str(ARQ_CERT), str(ARQ_CHAVE))
    except Exception:
        log.warning(
            "Tailscale encontrado, mas 'tailscale cert' falhou (HTTPS da "
            "tailnet desabilitado?). Caindo para certificado autoassinado.",
            exc_info=True,
        )
    return None





def data_expiracao(certificado):

    try:
        return certificado.not_valid_after_utc
    except AttributeError:
        return certificado.not_valid_after.replace(tzinfo=timezone.utc)





def certificado_ainda_valido():
    if not (ARQ_CERT.exists() and ARQ_CHAVE.exists()):
        return False
    try:
        from cryptography import x509

        certificado = x509.load_pem_x509_certificate(ARQ_CERT.read_bytes())
        return data_expiracao(certificado) > datetime.now(timezone.utc) + timedelta(days=5)
    except Exception:
        return False





def enderecos_desta_maquina():
    enderecos = set()
    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = ""
    for info in (
        tentar(lambda: socket.getaddrinfo(hostname, None)) if hostname else []
    ):
        enderecos.add(info[4][0])
    return hostname, enderecos





def tentar(func):
    try:
        return func()
    except Exception:
        return []




# Gera certificado autoassinado
def gerar_certificado_autoassinado():
    if certificado_ainda_valido():
        return (str(ARQ_CERT), str(ARQ_CHAVE))

    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        log.error(
            "Pacote 'cryptography' não instalado — não dá pra gerar um "
            "certificado HTTPS autoassinado. Rode: pip install cryptography"
        )
        return None

    log.info("Gerando certificado HTTPS autoassinado (fica salvo pra próxima vez).")
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    nomes_alternativos = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    hostname, enderecos = enderecos_desta_maquina()
    if hostname:
        nomes_alternativos.append(x509.DNSName(hostname))
        nomes_alternativos.append(x509.DNSName(f"{hostname}.local"))
    for ip_texto in enderecos:
        try:
            nomes_alternativos.append(x509.IPAddress(ipaddress.ip_address(ip_texto)))
        except ValueError:
            pass

    nomes_alternativos = list(dict.fromkeys(nomes_alternativos))

    assunto = emissor = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "Mark 2 Jarvis (local)")]
    )
    agora = datetime.now(timezone.utc)
    certificado = (
        x509.CertificateBuilder()
        .subject_name(assunto)
        .issuer_name(emissor)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1))
        .not_valid_after(agora + timedelta(days=VALIDADE_DIAS))
        .add_extension(x509.SubjectAlternativeName(nomes_alternativos), critical=False)
        .sign(chave, hashes.SHA256())
    )

    DIR_CERTIFICADO.mkdir(parents=True, exist_ok=True)
    ARQ_CHAVE.write_bytes(
        chave.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    ARQ_CERT.write_bytes(certificado.public_bytes(serialization.Encoding.PEM))
    return (str(ARQ_CERT), str(ARQ_CHAVE))




# Consulta contexto ssl
def obter_contexto_ssl():
    return tentar_certificado_tailscale() or gerar_certificado_autoassinado()