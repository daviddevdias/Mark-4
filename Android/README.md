# Jarvis para Android 1.5

Aplicativo nativo em Kotlin e Jetpack Compose. A conexão com o PC usa HTTPS, chave de acesso e conferência da impressão digital SHA-256 do certificado.

## Instalar e conectar

Instale `Mark2-1.5.apk` neste diretório. No painel do PC, abra **Conectar celular → Mostrar dados**. Transfira o endereço do PC, a porta HTTPS, a chave de acesso e a impressão digital para as configurações do aplicativo. Nunca publique esses dados.

As credenciais ficam no cofre do Android. O aplicativo não aceita automaticamente um certificado novo. Se o certificado mudar, confira novamente os dados no PC.

## Navegação

- Início: estado da conexão.
- Torre Stark: câmera ao vivo, movimentos, defesas, alarme, fotos e gravações.
- Agenda e Notas: informações pessoais compartilhadas com o Jarvis.
- WhatsApp: avisos compartilhados pelo celular.
- Comandos: abrir as seções pessoais e ouvir agenda, notas e avisos do WhatsApp no celular e no PC.

O menu abre pelo botão no topo. Arrastar sobre a câmera não abre o menu lateral. A atualização da câmera para quando o aplicativo fica em segundo plano.

## Inteligência local

No rodapé do menu há controles para ativar e desativar LM Studio e Hermes **dentro do Jarvis**. Eles não encerram os programas instalados. O botão **Parar resposta e voz** interrompe a resposta em andamento, a leitura e a voz. A parada do PC também é observada pelo app aberto, com atualização de aproximadamente 1,5 segundo enquanto conectado.

## Voz e gravações

Ative **Respostas por voz no celular** nas configurações. É necessário ter um mecanismo de síntese de voz com português no Android. As confirmações de defesas, alarme, informações pessoais e consultas podem ser faladas no celular. A voz do PC também depende de estar ativada no Jarvis.

As gravações são baixadas para arquivos temporários, sem carregar todo o vídeo na RAM. O player oferece controles de reprodução. Cada arquivo é removido ao fechar ou trocar sua reprodução. O formato precisa ser compatível com o decodificador do aparelho.

## Privacidade

O compartilhamento de notificações exige autorização do usuário no Android. Os avisos na tela bloqueada têm visibilidade privada. O acesso remoto não libera comandos gerais do computador. As novas rotas pessoais têm limites de frequência.

## Verificação

Compilar: `gradlew.bat :app:assembleDebug --offline --no-daemon`.
Validar avisos: `gradlew.bat :app:verificarAvisos --offline --no-daemon`.

Compilação e testes automatizados não substituem verificar câmera, áudio e vídeo no aparelho físico.
