# Transports MCP — stdio e Streamable HTTP

O Coppermind expõe o mesmo conjunto de tools/resources por dois transports MCP.
A escolha do transport não muda o Circuit IR, o composer, o ERC nem os gates de
segurança; muda apenas **como o cliente conversa com o servidor**.

## 1. stdio

Use quando o cliente MCP roda na mesma máquina e consegue iniciar o Coppermind como
subprocesso.

```bash
coppermind --transport stdio
```

`stdio` é o padrão, portanto isto é equivalente:

```bash
coppermind
```

É o caminho recomendado para Claude Desktop/Code e outros hosts MCP locais.

Exemplo:

```json
{
  "mcpServers": {
    "coppermind": {
      "command": "coppermind",
      "args": ["--transport", "stdio"],
      "env": {
        "COPPERMIND_BACKEND": "auto"
      }
    }
  }
}
```

## 2. Streamable HTTP

Use quando o cliente precisa acessar o Coppermind por HTTP — por exemplo, através de
um túnel MCP confiável.

```bash
coppermind \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8765 \
  --path /mcp
```

O endpoint fica em:

```text
http://127.0.0.1:8765/mcp
```

O mesmo pode ser definido por ambiente:

```bash
export COPPERMIND_TRANSPORT=streamable-http
export COPPERMIND_HTTP_HOST=127.0.0.1
export COPPERMIND_HTTP_PORT=8765
export COPPERMIND_HTTP_PATH=/mcp
coppermind
```

PowerShell:

```powershell
$env:COPPERMIND_TRANSPORT="streamable-http"
$env:COPPERMIND_HTTP_HOST="127.0.0.1"
$env:COPPERMIND_HTTP_PORT="8765"
$env:COPPERMIND_HTTP_PATH="/mcp"
coppermind
```

## 3. Segurança do endpoint HTTP

O Coppermind **recusa bind em interfaces não-loopback**. São aceitos:

- `127.0.0.1`;
- `localhost`;
- `::1`.

Isto é proposital. O servidor atualmente:

- mantém **uma sessão de design por processo**;
- não implementa autenticação multiusuário;
- tem tools de escrita capazes de alterar um projeto KiCad;
- deve ser tratado como um processo de automação local privilegiado.

Portanto, não exponha `0.0.0.0:8765` diretamente na LAN ou Internet.

Além dessa política do Coppermind, o SDK MCP mantém proteção contra DNS rebinding no
Streamable HTTP. Um proxy público genérico pode precisar de configuração adicional de
Host/Origin no gateway. O Coppermind deliberadamente não desativa essa proteção.

## 4. ChatGPT / cliente em nuvem

Um cliente em nuvem não consegue alcançar diretamente `127.0.0.1` do seu PC. O
modelo recomendado é:

```text
cliente MCP em nuvem
        │
        │ HTTPS / MCP Streamable HTTP
        ▼
túnel ou gateway MCP autenticado
        │
        │ conexão local
        ▼
http://127.0.0.1:8765/mcp
        │
        ▼
Coppermind
        │
        ▼
KiCad / kicad-cli
```

Para criar esquemáticos, o cliente/workspace precisa permitir **custom MCP + tools de
escrita**. Ter Streamable HTTP disponível não concede essa permissão por si só.

Quando o produto cliente oferecer um túnel MCP seguro para servidores locais, prefira
essa opção a publicar o endpoint do Coppermind.

## 5. Backend e transport são independentes

Exemplos válidos:

```text
stdio + MemoryBackend
stdio + IPCBackend
Streamable HTTP + MemoryBackend
Streamable HTTP + IPCBackend
```

Na prática, para controlar o KiCad aberto:

```bash
COPPERMIND_BACKEND=ipc coppermind --transport stdio
```

ou:

```bash
COPPERMIND_BACKEND=ipc coppermind --transport streamable-http
```

`COPPERMIND_BACKEND=auto` tenta IPC e degrada para memória quando o KiCad não está
acessível.

## 6. Opções de CLI

```text
--transport {stdio,streamable-http}
--host HOST
--port PORT
--path PATH
--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}
```

Defaults HTTP:

```text
host = 127.0.0.1
port = 8765
path = /mcp
```

Variáveis correspondentes:

```text
COPPERMIND_TRANSPORT
COPPERMIND_HTTP_HOST
COPPERMIND_HTTP_PORT
COPPERMIND_HTTP_PATH
LOG_LEVEL
```

## 7. Diagnóstico

### O servidor inicia, mas o cliente não conecta

Confirme que o endpoint exato termina em `/mcp`:

```text
http://127.0.0.1:8765/mcp
```

Depois confirme se o túnel/gateway realmente aponta para esse endereço local.

### Erro ao usar `0.0.0.0`

É comportamento esperado. O Coppermind bloqueia exposição direta. Use loopback +
túnel/gateway autenticado.

### O MCP conecta, mas o KiCad não é alterado

Transport e backend são camadas diferentes. Verifique:

1. `COPPERMIND_BACKEND=ipc` ou `auto`;
2. KiCad aberto;
3. **Preferences → Plugins → Enable IPC API Server**;
4. `kicad-python` instalado com `pip install -e ".[ipc]"`.

### O esquemático é criado, mas não aparece ao vivo

No KiCad 10, o caminho principal de esquemático ainda usa materialização
`.kicad_sch` + `kicad-cli`. O IPC ao vivo é mais completo no lado de PCB; a evolução
do IPC de esquemático do KiCad 11 será adotada progressivamente.

## 8. Modelo de sessão

No estado atual, `build_server()` cria uma única `Session` e a vincula às tools. Isso
é apropriado para um usuário controlando um projeto por processo, tanto em stdio
quanto através de um túnel HTTP dedicado.

Para um futuro serviço multiusuário, a arquitetura precisará evoluir para:

```text
identidade/autenticação
      ↓
sessão MCP
      ↓
Session Coppermind isolada
      ↓
workspace/projeto isolado
```

Até lá, **um processo = um usuário/contexto de design**.
