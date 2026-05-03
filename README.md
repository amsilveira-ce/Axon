# AXON Framework ⚡
Conectar. Transmitir. Resolver.

AXON é uma framework de orquestração de infraestrutura para agentes de IA, projetada para transformar modelos isolados em uma rede neural interoperável e eficiente. Inspirada na arquitetura DAWN, a AXON atua como o sistema nervoso central que gerencia a comunicação e o acesso a recursos através dos protocolos MCP (Model Context Protocol) e A2A (Agent-to-Agent).

A framework foi desenvolvida para solucionar as limitações de contextos estáticos, permitindo que agentes descubram, negociem e utilizem recursos de forma dinâmica e adaptativa.

## Desenvolvimento (rápido)

Siga estes passos para criar um ambiente de desenvolvimento e instalar o pacote localmente.

1. Criar e ativar o virtual environment (macOS / Linux):

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Certificar-se que o `pip` está disponível e atualizar ferramentas:

```bash
python -m ensurepip --upgrade
python -m pip install --upgrade pip setuptools wheel
```

3. Instalar o pacote em modo editável (cria o comando `axon` no ambiente):

```bash
python -m pip install -e .
```

4. (Opcional) instalar `uv` para executar módulos diretamente com conveniência:

```bash
python -m pip install uv
```

5. Executar o comando `axon init`:

```bash
# Com o pacote instalado no venv
axon init

# Ou, sem instalar, usando PYTHONPATH
PYTHONPATH=src python3 -m axon.cli.main init

# Usando `uv` (após instalar em 4.)
PYTHONPATH=src uv run -m axon.cli.main init
```

Se o `pip` não estiver disponível no virtualenv, os comandos do passo 2 acima (`ensurepip`) resolvem o problema; em casos extremos, use o instalador oficial do pip:

```bash
curl -sS https://bootstrap.pypa.io/get-pip.py -o get-pip.py
python get-pip.py
python -m pip install --upgrade pip setuptools wheel
```

Observações:
- Mantenha o virtualenv ativado enquanto desenvolve para garantir que o `axon` instalado venha do ambiente correto.
- O `project.scripts` em `pyproject.toml` cria o entry-point `axon` quando você instala o pacote no ambiente.

