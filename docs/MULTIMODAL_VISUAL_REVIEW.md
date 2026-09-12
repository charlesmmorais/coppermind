# Multimodal Visual Reviewer

CopperMind's deterministic Visual Reviewer remains enabled without any external AI service. The multimodal layer is optional and reviews the **real PDF exported by KiCad** together with a bounded Circuit IR context.

## Pipeline

```text
Circuit IR
   ↓
Semantic Composer
   ↓
Deterministic Visual Reviewer + geometry-only reflow
   ↓
KiCad SVG render
   ↓
KiCad PDF render
   ↓
Optional multimodal reviewer
   ↓
Structured visual findings
   ↓
ERC / preview / commit gate
```

The multimodal model never receives MCP tools, Python execution, shell access, file-system access, or a capability to change the Circuit IR. It can only return structured visual findings. The allowed suggestions are geometric: grouping/moving symbols, labels and visual blocks without changing electrical connectivity.

## OpenAI configuration

```bash
export COPPERMIND_VISUAL_PROVIDER=openai
export OPENAI_API_KEY="..."
export COPPERMIND_VISUAL_MODEL="gpt-5.6-terra"
```

Optional settings:

```bash
# API endpoint override; useful for compatible gateways/proxies.
export COPPERMIND_OPENAI_RESPONSES_URL="https://api.openai.com/v1/responses"

# Request timeout, bounded internally to 5..180 seconds.
export COPPERMIND_VISUAL_AI_TIMEOUT="60"

# Off by default. When enabled, a high-confidence AI error can block commit.
export COPPERMIND_VISUAL_AI_GATE="1"

# Off by default. Fail closed when the configured multimodal reviewer is unavailable.
export COPPERMIND_VISUAL_AI_REQUIRED="1"
```

With no `COPPERMIND_VISUAL_PROVIDER`, or with it set to `off`, the system does not make an external model request.

## Safety model

The provider receives only:

- KiCad-rendered schematic PDF;
- component reference, symbol ID and value;
- schematic X/Y positions;
- net names and node references;
- bounded Circuit IR constraints;
- visual counts.

The provider is instructed to review readability and organization only. Responses are normalized before entering the pipeline:

- unknown component references are discarded;
- severity is restricted to `info`, `warning` or `error`;
- per-finding penalties are capped;
- total AI penalty is capped at 25 points;
- maximum 8 findings are accepted;
- confidence is clamped to 0..1;
- AI findings are advisory unless `COPPERMIND_VISUAL_AI_GATE=1`;
- external failure is non-blocking unless `COPPERMIND_VISUAL_AI_REQUIRED=1`.

## Output

The normal `visual_review.review` object gains:

```json
{
  "deterministic_score": 96.0,
  "score": 91.0,
  "multimodal": {
    "enabled": true,
    "available": true,
    "provider": "openai",
    "model": "gpt-5.6-terra",
    "summary": "Power stage is readable but visually dispersed.",
    "penalty": 5.0,
    "findings": [
      {
        "code": "AI_BLOCK_GROUPING",
        "severity": "warning",
        "message": "The power-stage parts are visually dispersed.",
        "refs": ["U2", "L1", "D1"],
        "suggestion": "Group the power-stage symbols without changing their nets.",
        "confidence": 0.91,
        "source": "multimodal"
      }
    ]
  }
}
```

The deterministic score is retained for auditability. The final score subtracts only normalized, capped multimodal penalties.

## Data boundary

When an external provider is enabled, the KiCad-rendered PDF and the bounded context described above leave the local process and are sent to that provider. Do not enable an external provider for sensitive designs unless that data transfer is acceptable under the applicable security and privacy policy.
