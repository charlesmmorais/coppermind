# Guia de Autorroteamento (Freerouting)

Este guia mostra, passo a passo, como rotear automaticamente uma PCB no fluxo do
Coppermind usando o [Freerouting](https://github.com/freerouting/freerouting) —
do export do DSN no KiCAD até aplicar o resultado na placa.

![Fluxo Freerouting](freerouting-flow.svg)

O Coppermind usa o formato **Specctra**: exporta-se um `.dsn`, o Freerouting
roteia e gera um `.ses`, e o Coppermind importa o `.ses` de volta como trilhas e
vias — tudo dentro de uma transação reversível (preview/diff/commit).

---

## Pré-requisitos

| Requisito | Por quê |
| --- | --- |
| KiCAD 10+ | exportar o Specctra DSN da sua placa |
| `freerouting.jar` (v2) **ou** Docker/Podman | executar o autorouter |
| Java 21+ (só se rodar o jar direto, sem container) | runtime do Freerouting |
| Coppermind instalado (`pip install -e .`) | orquestrar o fluxo |

O Coppermind detecta o runtime automaticamente, **nesta ordem**: Java local →
Docker → Podman. Confira a qualquer momento com a tool `route_check`.

---

## Passo 1 — Exportar o DSN do KiCAD

O `kicad-cli` **não** exporta Specctra DSN, então o export é feito pela interface
do KiCAD (PCB Editor):

1. Abra sua placa no **PCB Editor** do KiCAD.
2. Menu **File → Export → Specctra DSN…**
3. Salve como, por exemplo, `~/projetos/minha_placa/board.dsn`.

> Dica: garanta que os nets e footprints já estão definidos (faça o
> *Update PCB from Schematic*, F8, antes de exportar).

---

## Passo 2 — Obter o Freerouting

Escolha **uma** das opções abaixo.

### Opção A — Docker (recomendada, sem instalar Java)

```bash
docker pull eclipse-temurin:21-jre
mkdir -p ~/.kicad-mcp
curl -L -o ~/.kicad-mcp/freerouting.jar \
  https://github.com/freerouting/freerouting/releases/download/v2.1.0/freerouting-2.1.0.jar
```

### Opção B — Java direto

```bash
# Ubuntu/Debian
sudo apt install -y openjdk-21-jre-headless
mkdir -p ~/.kicad-mcp
curl -L -o ~/.kicad-mcp/freerouting.jar \
  https://github.com/freerouting/freerouting/releases/download/v2.1.0/freerouting-2.1.0.jar
```

### Opção C — Podman

Igual ao Docker; o Coppermind usa o Podman automaticamente se o Docker não estiver
disponível.

> Ajuste a URL/versão do `.jar` conforme a *release* mais recente do Freerouting.

---

## Passo 3 — Verificar a prontidão

Peça ao assistente (ou chame a tool diretamente):

```text
route_check
```

Resposta típica quando tudo está pronto:

```json
{ "runtime": "docker", "detail": "docker fallback", "jar_present": true, "ready": true }
```

Se `ready` for `false`, falta o runtime (Java/Docker/Podman) ou o `.jar` no caminho
informado.

---

## Passo 4 — Rodar o autorroteamento

Com a placa aberta no Coppermind (após `project_create`/`open` e o `.dsn` exportado):

```text
route_autoroute
  dsn_path = ~/projetos/minha_placa/board.dsn
  ses_path = ~/projetos/minha_placa/board.ses
  jar_path = ~/.kicad-mcp/freerouting.jar   # (padrão; pode omitir)
  max_passes = 10
```

O Coppermind:

1. resolve o runtime (Java/Docker/Podman) e monta o comando
   `freerouting -de board.dsn -do board.ses -mp 10`;
2. executa o Freerouting e aguarda o `.ses`;
3. faz o **parse do SES** (respeitando resolução/unidades) → trilhas + vias;
4. aplica ao *working board*, **substituindo** o roteamento obsoleto.

Retorno:

```json
{ "ok": true, "tracks": 128, "vias": 14, "pending_commit": true }
```

---

## Passo 5 — Revisar e confirmar

Nada foi gravado ainda — reveja antes de aceitar:

```text
design_preview     # diff estruturado + DRC nativo + render + advice (citado)
design_commit      # verifica (estrutural + DRC) e grava; bloqueia em erros
# ou
design_rollback    # descarta o resultado do autorouter
```

O commit roda o portão de verificação (checagens estruturais + DRC/ERC nativo do
KiCAD). Se houver violação de erro, o commit é **bloqueado** e o working board fica
intacto para você ajustar.

---

## Alternativa — Importar um SES já existente

Se você já tem um `.ses` (roteou pelo GUI do Freerouting, por exemplo):

```text
route_import_ses
  ses_path = ~/projetos/minha_placa/board.ses
  replace  = true     # substitui o roteamento atual (padrão)
```

---

## Solução de problemas

| Sintoma | Causa provável | Solução |
| --- | --- | --- |
| `route_check` → `ready:false` | sem Java/Docker/Podman ou jar ausente | instale o runtime / baixe o `.jar` no caminho |
| "Freerouting is not available" | idem acima | rode `route_check` e corrija |
| `.ses` vazio / poucas trilhas | DSN sem nets/regras | refaça o export do DSN após F8 no KiCAD |
| Trilhas em posição errada | unidade/resolução do SES | o parser respeita `(resolution …)`; confirme o DSN de origem |
| Quero ver o que mudou | — | use `design_preview` antes do `design_commit` |

---

## Referência rápida das tools

| Tool | O que faz |
| --- | --- |
| `route_check` | informa runtime (Java/Docker/Podman) e se o jar está presente |
| `route_export_dsn` | tenta exportar DSN via IPC; senão orienta o export manual |
| `route_autoroute` | DSN → Freerouting → SES → aplica ao board |
| `route_import_ses` | importa um `.ses` já roteado |
| `design_preview` / `design_commit` / `design_rollback` | revisar e confirmar/descartar |

Veja também o [README](../README.md) e a [arquitetura](ARQUITETURA.md).
