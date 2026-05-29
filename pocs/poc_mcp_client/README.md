# POC — MCPClient + ResourceManifest

Prova de que **um único `MCPClient`, dirigido só pelo `ResourceManifest`**, conecta
em qualquer recurso MCP (HTTP / SSE / stdio) e qualquer padrão de autenticação,
sem código específico por recurso.

## Resultado

| Recurso | Transport (`ProtocolBinding`) | Auth (`scheme` + `location`) | Resultado |
|---------|------------------------------|------------------------------|-----------|
| Tavily  | `MCP_HTTP`  | `api_key` + `query` | ✅ busca real |
| Notion  | `MCP_HTTP`  | `oauth`             | ✅ manifest dirige o fluxo (browser) |
| Resend  | `MCP_STDIO` | `api_key` + `env`   | ✅ email real entregue |
| A2A / header | qualquer | `bearer` / `api_key` + `header` | ✅ modelado e válido |

## Como rodar

Pré-requisito: `.env` na raiz do projeto (carregado automaticamente pelo `TokenResolver`).

```dotenv
TAVILY_API_KEY=tvly-...
RESEND_API_KEY=re_...
SENDER_EMAIL_ADDRESS=onboarding@resend.dev   # ou um endereço de domínio verificado
```

```bash
# Tavily — api_key na query string
python pocs/poc_mcp_client/run_tavily.py

# Notion — OAuth (abre o navegador na 1ª vez)
python pocs/poc_mcp_client/run_notion.py

# Resend — stdio, envia um email REAL
python pocs/poc_mcp_client/run_resend.py <destinatario>
```

> Resend em modo teste (`onboarding@resend.dev`) só entrega para o e-mail da sua
> conta Resend. Para outros destinatários, verifique um domínio em resend.com/domains
> e use um `from` desse domínio.

## Arquitetura validada

Dois eixos ortogonais, ambos no `ResourceManifest`:

- **`ProtocolBinding`** — *como alcançar*: `MCP_HTTP`, `MCP_SSE`, `MCP_STDIO`.
- **`AuthConfig`** — *como autenticar*: `scheme` (`none|bearer|api_key|oauth`) +
  `location` (`header|query|env`), no estilo OpenAPI.

Fluxo:

```
ResourceManifest
  → TokenResolver.resolve()   # carrega .env, lê o segredo da env var
      → ResolvedAuth          # as_headers() | apply_to_url() | as_env()
  → MCPClient._build_transport
      header → headers HTTP
      query  → ?param=token na URL
      env    → injeta no env do processo stdio
      oauth  → delega ao fastmcp.OAuth (DCR + browser + token storage)
```

Princípios:

- **Segredo nunca mora no manifest** — resolvido em runtime via env / `.env`.
- **OAuth não tem segredo estático** — é delegado ao `fastmcp.OAuth`.
- **`ResolvedAuth` é o ponto único** que converte a credencial em header, query
  param ou env do processo filho.

## Arquivos

| Arquivo | Papel |
|---------|-------|
| `mcp_client.py` | `MCPClient` — abstrai transport + auth a partir do manifest |
| `run_tavily.py` / `run_notion.py` / `run_resend.py` | demos por cenário |
| `test_http_travily.py` | teste pytest original do Tavily (async) |
| `src/axon/types.py` | `AuthScheme`, `AuthLocation`, `AuthConfig`, `ResourceManifest` |
| `src/axon/pa/token_resolver.py` | resolve segredo (env + `.env`), location-aware |

## Em aberto

- **Persistência do token OAuth (Notion):** hoje `MemoryStore` → re-auth a cada run;
  falta `token_storage` em disco/keychain para auto-reconnect.
- **stdio:** `env_var` é fonte *e* destino ao mesmo tempo; se os nomes diferirem,
  o modelo ainda não separa origem (de onde ler) e destino (nome injetado).
- **Config vs segredo:** `SENDER_EMAIL_ADDRESS` é config do Resend, flui por herança
  de env e não está no manifest.
- **Integração com o PA:** isto são scripts de POC; falta plugar o `MCPClient` no
  Executor, com o GA emitindo o manifest com `scheme`/`location` corretos no registro.
- **`callable_by="ga_proxy"`** não exercitado (só `pa_direct`).
- **Falha de auth nem sempre levanta erro:** o Tavily devolve `401` como resultado
  normal da tool (`is_error=False`); detectar isso exige inspecionar o conteúdo.
