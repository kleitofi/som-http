# som-http

Transmite o som do PC Windows para celulares (iPhone, Android) pela rede local.
O áudio sai no que estiver conectado ao celular, como um fone Bluetooth.

- Captura o som do sistema com **WASAPI loopback**, sem precisar de dispositivo virtual.
- Transmite com **WebRTC** (Opus, baixa latência).
- Vários aparelhos podem ouvir ao mesmo tempo.

## Como usar

1. Dê dois cliques em `iniciar.bat`. Na primeira vez ele cria o ambiente e instala as dependências.
2. Abre a janela **Som do PC** com um QR code e o endereço (ex.: `192.168.0.10:8080`).
3. No celular, conectado ao **mesmo Wi-Fi**, aponte a câmera para o QR code e toque em **Ouvir**.

Na primeira execução o Windows pode pedir para liberar o Python no firewall. Permita em **redes privadas**.

### Executável (sem Python)

`dist\SomDoPC.exe` roda em qualquer Windows 10/11 sem instalar nada. Basta copiar o arquivo e dar dois cliques.
Ele aceita as mesmas opções abaixo (ex.: `SomDoPC.exe --port 9000`), e o log fica ao lado do `.exe`.

Para gerar de novo depois de mudar o código, rode `gerar_exe.bat`.

### Janela do PC (painel)

- QR code e endereço, com botão para copiar. Se o PC tiver mais de uma rede, dá para trocar o endereço.
- Escolha da saída de som capturada (↻ atualiza a lista se você ligar um fone/caixa depois).
- Medidor do nível do som e botão **Pausar transmissão** (os celulares recebem silêncio).
- Lista de aparelhos ouvindo, com opção de desconectar um.

### Página do celular

- Botão grande Ouvir/Parar, com anel e barras que acompanham o som.
- Mostra o atraso estimado, há quanto tempo está ouvindo e quantos aparelhos estão conectados.
- Reconecta sozinha se a conexão cair (ex.: Wi-Fi oscilou) e avisa quando o PC pausa.

### Opções

```
iniciar.bat --console              roda sem janela, só no console
iniciar.bat --list                 lista as saídas de som que podem ser capturadas
iniciar.bat --device "Alto-fal"    captura uma saída específica (parte do nome)
iniciar.bat --port 9000            muda a porta (padrão 8080)
```

As opções podem ser combinadas, por exemplo `iniciar.bat --console --port 9000`.
Sem `--device`, captura a saída de som padrão do Windows.

## Observações

- No iPhone é preciso tocar no botão para o áudio começar (regra do iOS).
- A latência é a da rede (~100–200 ms) somada à do Bluetooth.
- Os aparelhos não ficam perfeitamente sincronizados entre si.
- Com a tela do iPhone bloqueada, o som pode parar. Isso ainda precisa ser testado.
- Funciona por `http://` na rede local. Não exponha a porta na internet.
- O registro fica em `som-http.log`.

## Arquivos

- `server.py`: captura o áudio, serve a página e a conexão WebRTC.
- `painel.py`: janela do PC.
- `static/index.html`: página do celular.
- `iniciar.bat`: cria o venv, instala e inicia.
- `gerar_exe.bat`: gera `dist\SomDoPC.exe` com o PyInstaller.
- `icone.ico`: ícone do programa.
