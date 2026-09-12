# Documentação do Coppermind

Este diretório reúne a documentação técnica que complementa os READMEs da raiz.
O README principal descreve o caminho feliz; os arquivos abaixo detalham decisões,
limites e fluxos operacionais.

## Índice

| Documento | Conteúdo |
| --- | --- |
| [ARQUITETURA.md](ARQUITETURA.md) | Arquitetura atual, invariantes, Circuit IR, composer, backends e roadmap. |
| [TRANSPORTES.md](TRANSPORTES.md) | Guia em português para `stdio`, Streamable HTTP, loopback e túnel MCP. |
| [TRANSPORTS.md](TRANSPORTS.md) | English guide for `stdio`, Streamable HTTP, loopback and MCP tunnelling. |
| [MULTIMODAL_VISUAL_REVIEW.md](MULTIMODAL_VISUAL_REVIEW.md) | Reviewer visual multimodal opcional, fronteira de dados e gates. |
| [VISUAL_AUTOFIX.md](VISUAL_AUTOFIX.md) | Layout Action IR, auto-fix geométrico e critérios de accept/rollback. |
| [AUTORROTEAMENTO.md](AUTORROTEAMENTO.md) | Fluxo Specctra DSN → Freerouting → SES → preview/commit. |
| [architecture.svg](architecture.svg) | Diagrama resumido da arquitetura. |
| [freerouting-flow.svg](freerouting-flow.svg) | Diagrama do fluxo de autorroteamento. |

## Fonte de verdade

Quando houver conflito entre um documento e o código:

1. `src/coppermind/` define o comportamento real;
2. os testes em `tests/` definem as invariantes executáveis;
3. os documentos devem ser atualizados para refletir ambos.

Em particular, a superfície MCP principal hoje é **semântica**: o agente trabalha
com componentes, pinos e nets; operações cruas de geometria de esquemático ficam
internas.

## Estado dos transports

O mesmo executável suporta:

```bash
coppermind --transport stdio
```

ou:

```bash
coppermind --transport streamable-http --host 127.0.0.1 --port 8765 --path /mcp
```

O modo Streamable HTTP é **single-user por processo e loopback-only**. Para um
cliente em nuvem, use um túnel/gateway MCP autenticado em frente ao endpoint local.

## Estado do fluxo de esquemático

```text
Circuit IR
 → símbolos reais do KiCad
 → Semantic Composer
 → .kicad_sch
 → ERC
 → Visual Reviewer
 → Layout Action IR
 → accept / rollback
```

As cinco fases dessa arquitetura estão consolidadas na `main`; o próximo foco é
benchmarkar circuitos reais e evoluir o caminho de PCB para o mesmo nível semântico.
