# J.A.R.V.I.S. Mark 4

Seu assistente pessoal para Windows: converse por texto ou voz, use inteligência artificial e conecte os recursos da sua casa em um painel local.

**Primeira vez por aqui?** Siga os passos de instalação abaixo. Câmera, celular, contas e modelos de IA podem ser configurados depois, conforme você precisar.

[Instalar](#1-prepare-o-computador) · [Abrir o Jarvis](#3-abra-o-jarvis) · [Recursos opcionais](#recursos-opcionais) · [Resolver problemas](#precisa-de-ajuda)

## Antes de começar

Você vai precisar de:

- **Windows de 64 bits.**
- **Python 3.12 de 64 bits**, com o Python Launcher instalado para usar o comando `py`.
- **Internet** para baixar as dependências e usar serviços online.
- **Microfone**, se quiser falar com o assistente.

Esta distribuição contém o código do projeto. Modelos de IA e voz, executáveis auxiliares e configurações pessoais são instalados separadamente. Alguns recursos só ficam disponíveis depois dessa configuração.

## 1. Prepare o computador

1. Instale o Python 3.12 de 64 bits, caso ainda não tenha essa versão.
2. Nesta página do GitHub, clique no botão **Code** e depois em **Download ZIP**.
3. Clique com o botão direito no ZIP baixado e escolha **Extrair tudo**.
4. Entre na pasta extraída até encontrar os arquivos **`main.py`** e **`requirements.txt`**.
5. Clique na barra de endereço dessa pasta no Explorador de Arquivos, digite `powershell` e pressione **Enter**.

O terminal deve abrir dentro da pasta do projeto. Para conferir o Python, copie o comando abaixo e pressione **Enter**:

```powershell
py -3.12 --version
```

O resultado esperado começa com `Python 3.12`. Se aparecer um erro, veja [Precisa de ajuda?](#precisa-de-ajuda).

> Copie apenas os comandos dentro das caixas. Não copie textos como `PS C:\...>` que aparecem no seu terminal.

## 2. Instale o Jarvis — apenas na primeira vez

No PowerShell que você acabou de abrir, execute **um comando por vez**. Aguarde cada um terminar antes de continuar.

Crie o ambiente do projeto:

```powershell
py -3.12 -m venv .venv
```

Prepare o instalador de pacotes:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

Instale as dependências:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

O último comando pode levar alguns minutos e baixar arquivos grandes. Espere o terminal voltar a aceitar comandos. Se aparecer uma mensagem de erro, resolva antes de seguir.

Você não precisa ativar o ambiente virtual nem alterar a política de scripts do PowerShell.

## 3. Abra o Jarvis

Na pasta do projeto, execute:

```powershell
.\.venv\Scripts\python.exe main.py
```

A janela do Jarvis deve abrir. Com o aplicativo em execução, você também pode acessar o painel pelo navegador:

**[Abrir o painel neste computador](http://127.0.0.1:5678/painel)**

Esse endereço só funciona enquanto o Jarvis estiver aberto no mesmo computador.

## 4. Faça o primeiro uso

1. Explore o painel e abra as configurações.
2. Configure apenas os recursos que deseja usar, seguindo a seção abaixo.
3. Comece digitando na conversa. Para respostas de IA, configure primeiro um servidor de IA.
4. Se quiser usar voz, confira o microfone e configure a saída de voz.

Na primeira execução, o aplicativo cria a pasta `data/` para guardar suas configurações. É normal que uma integração apareça indisponível enquanto faltar sua configuração, modelo ou equipamento.

**Para usar outro dia:** abra o PowerShell na mesma pasta e execute somente o comando do passo 3. Não é necessário instalar tudo novamente.

**Para encerrar:** use o controle de encerramento do Jarvis. Mantenha apenas uma instância aberta por vez.

## Recursos opcionais

Abra abaixo o recurso que você quer configurar. Você pode fazer isso aos poucos.

<details>
<summary><strong>Conversar com inteligência artificial</strong></summary>

O Jarvis precisa se conectar a um servidor compatível com a API OpenAI.

1. Inicie seu servidor de IA e carregue um modelo.
2. Confira o endereço do servidor e o identificador do modelo.
3. Feche o Jarvis antes de editar sua configuração.
4. Em `data/config_mark2.json`, ajuste `llm_local_url` e `llm_local_modelo`, preservando as demais opções e a formatação do JSON.
5. Abra o Jarvis novamente.

O endereço padrão é `http://localhost:1234/v1`. O consumo de memória e GPU depende do modelo escolhido.

</details>

<details>
<summary><strong>Falar com o Jarvis e ouvir as respostas</strong></summary>

**Para o Jarvis ouvir você:** conecte um microfone e permita seu uso nas configurações de privacidade do Windows. O reconhecimento de voz do PC usa o serviço Google pelo SpeechRecognition e precisa de internet.

**Para ouvir as respostas:** configure uma das opções de saída de voz:

- **ElevenLabs:** use sua própria conta, chave de API e identificador de voz. A configuração fica em `data/elevenlabs/configuracao.json`. As chamadas podem consumir créditos do serviço.
- **Piper:** coloque um modelo `.onnx` e seu arquivo `.onnx.json` correspondente em `modelos_voz/`. Ative o fallback Piper nas configurações para permitir seu uso quando o ElevenLabs não gerar a fala.

Os modelos e as credenciais não acompanham o projeto.

</details>

<details>
<summary><strong>Conectar Gmail, Google Agenda ou SmartThings</strong></summary>

Use suas próprias contas e faça a autorização pelas configurações do Jarvis. Cada serviço pode exigir credenciais e permissões específicas. Nunca publique esses dados no GitHub.

A integração Hermes é separada e opcional. Ela tem pendências conhecidas de dependências; atualize e revise esse componente antes de habilitá-lo.

</details>

<details>
<summary><strong>Usar câmera e detecção de pessoas — configuração avançada</strong></summary>

Você precisa de uma câmera compatível e dos dados de conexão dela, como RTSP e ONVIF.

- Instale o go2rtc em `go2rtc/go2rtc.exe` e coloque o `go2rtc.yaml` na mesma pasta. Confira o stream e a porta usados pelo Jarvis e mantenha a API administrativa restrita ao computador local.
- Para a detecção de pessoas, coloque `yolo11n-pose.pt` em `data/vigia/modelos/`. A variante `.onnx` correspondente pode ser usada pelo backend DirectML quando disponível.
- Configure o endereço e as credenciais da sua própria câmera.

Os executáveis, os modelos e a configuração da câmera não acompanham o repositório público.

</details>

<details>
<summary><strong>Conectar um celular Android — configuração avançada</strong></summary>

O aplicativo complementar precisa ser compilado pelo Android Studio; o repositório não inclui um APK pronto.

1. Abra a pasta `Android/` no Android Studio e configure o SDK exigido pelo projeto.
2. Para o reconhecimento local, obtenha o modelo Vosk conforme sua licença e coloque o ZIP em `Android/app/src/main/assets/vosk-model-small-pt-0.3.zip`.
3. No painel do PC, abra a configuração de conexão do celular e escolha **Mostrar dados de pareamento**.
4. No aplicativo, informe endereço, porta HTTPS, chave de acesso e impressão digital do certificado.

Confira os detalhes no [README do Android](Android/README.md).

</details>

## Precisa de ajuda?

| O que aconteceu? | O que fazer |
| --- | --- |
| O comando `py` não foi reconhecido | Instale o Python 3.12 com o Python Launcher. Feche e abra o PowerShell novamente. |
| Apareceu `No suitable Python runtime found` | O Launcher está instalado, mas não encontrou o Python 3.12. Instale essa versão de 64 bits. |
| Não encontrou `main.py` ou `requirements.txt` | Abra o terminal na pasta que contém esses dois arquivos, e não na pasta acima dela. |
| Não encontrou `.venv\Scripts\python.exe` | Volte ao passo 2 e confira se a criação do ambiente terminou sem erro. |
| Apareceu `ModuleNotFoundError` | Execute novamente a instalação de `requirements.txt`, usando o Python de `.venv` como no passo 2. |
| O painel não abre no navegador | Inicie `main.py`, aguarde a abertura e confira se houve algum erro no terminal. Use o link no mesmo computador. |
| A porta está em uso | Confira se já existe outra instância do Jarvis aberta e encerre-a antes de tentar novamente. |
| A IA não responde | Confira se o servidor de IA está ligado, com um modelo carregado, e se endereço e modelo estão corretos. |
| O microfone não funciona | Confira o dispositivo de entrada e as permissões do Windows. O reconhecimento atual também precisa de internet. |
| Câmera, voz ou uma conta aparecem indisponíveis | Abra a configuração do recurso acima e confira os modelos, credenciais ou equipamentos necessários. |

Se o problema continuar, abra uma issue neste repositório com o passo que tentou e a mensagem de erro. **Remova senhas, chaves, tokens, endereços privados e outros dados pessoais antes de compartilhar qualquer captura ou log.**

## Seus dados e sua segurança

Cada pessoa usa suas próprias contas e configurações. Os dados privados do autor não acompanham esta distribuição.

- **Mantenha `data/` privada:** ela pode conter tokens, certificados, conversas, bancos de dados e gravações.
- **Não publique suas credenciais:** isso inclui chaves de API, senhas e configurações de câmera.
- **Cache de voz:** `data/elevenlabs/cache` guarda falas para reutilização; `data/temp_voz` guarda cópias temporárias. Não apague a pasta `data/` inteira para limpar espaço.
- **Acesso pelo celular:** use a rede privada autorizada, HTTPS e confira o certificado de pareamento.

O projeto está em desenvolvimento. Não exponha a instalação diretamente à internet. A revisão de segurança não elimina todos os riscos.

## Permissão de uso

**Qualquer pessoa pode baixar, instalar e executar este projeto**, usando suas próprias configurações, contas e equipamentos.

Bibliotecas, modelos e serviços de terceiros mantêm suas respectivas licenças e condições de uso. Essa permissão se refere ao código do Jarvis disponibilizado neste repositório.

<details>
<summary><strong>Ferramentas de manutenção e desenvolvimento</strong></summary>

Confira as dependências instaladas:

```powershell
.\.venv\Scripts\python.exe -m pip check
```

Valide a interface com um Chrome já instalado:

```powershell
.\.venv\Scripts\python.exe -m tools.verificar_interface_upgrade --canal chrome
```

Simule a limpeza dos resíduos conhecidos, sem apagar arquivos:

```powershell
.\.venv\Scripts\python.exe tools/limpar_residuos.py
```

Confira o resultado da simulação. Para aplicar essa limpeza:

```powershell
.\.venv\Scripts\python.exe tools/limpar_residuos.py --aplicar
```

O diagnóstico `tools/testar_fala_camera.py` reproduz uma fala de teste. Para recarregar o aplicativo durante o desenvolvimento:

```powershell
.\.venv\Scripts\python.exe dev_watch.py
```

</details>
