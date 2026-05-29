"""
ga/config.py — Configuração e paths do Gateway Agent.

Resolve o contexto ativo seguindo a hierarquia:
  1. argumento context (passado pelo CLI via --context)
  2. AXON_GA_CONTEXT env var
  3. current_gateway no axon.config.json
  4. "default" como fallback

  os outros componentes do GA recebem GAPaths instanciado — nunca paths hardcoded.
"""
from __future__ import annotations

import os
from pathlib import Path

from axon.config import (
    AxonConfig,
    GAInstanceConfig,
    read_config,
    _ENV_GA_CONTEXT,
)


class GAPaths:
    """Paths absolutos de uma instância do GA derivados do data_dir."""

    def __init__(self, ga_dir: Path) -> None:
        self.root        = ga_dir
        self.registry    = ga_dir / "registry.json"
        self.tokens      = ga_dir / "tokens.json"
        self.connections = ga_dir / "connections.json"   # PAs conectados (POST /pa/connect)
        self.traces      = ga_dir / "traces"
        self.ga_config   = ga_dir / "ga.json"

    def makedirs(self) -> None:
        for d in (self.root, self.traces):
            d.mkdir(parents=True, exist_ok=True)


class GAConfig:
    """
    Configuração do GA para o contexto ativo.

    Uso:
        cfg   = GAConfig.resolve()           # contexto ativo
        cfg   = GAConfig.resolve("ga-corp")  # contexto explícito
        paths = cfg.paths                    # GAPaths instanciado
    """

    def __init__(
        self,
        context:  str,
        instance: GAInstanceConfig,
        paths:    GAPaths,
    ) -> None:
        self.context  = context
        self.instance = instance
        self.paths    = paths

    @classmethod
    def resolve(
        cls,
        context: str | None = None,
        cwd:     Path | None = None,
    ) -> "GAConfig":
        """
        Resolve o contexto GA ativo e retorna um GAConfig instanciado.

        Hierarquia:
          1. context argumento
          2. AXON_GA_CONTEXT env var
          3. current_gateway no axon.config.json
          4. "default"
        """
        env_ctx  = os.environ.get(_ENV_GA_CONTEXT)
        ctx      = context or env_ctx

        try:
            cfg = read_config(cwd)
        except FileNotFoundError:
            # fallback sem config — usa paths padrão
            ctx      = ctx or "default"
            base     = cwd or Path.cwd()
            ga_dir   = base / ".axon" / "ga"
            instance = GAInstanceConfig(
                name="Axon Local Gateway",
                port=5000,
                data_dir=str(ga_dir),
            )
            return cls(context=ctx, instance=instance, paths=GAPaths(ga_dir))

        if ctx is None:
            ctx = cfg.current_gateway

        instance = cfg.gateways.get(ctx)
        if instance is None:
            # contexto não encontrado — usa default se existir
            instance = cfg.gateways.get("default") or list(cfg.gateways.values())[0]
            ctx      = "default"

        base   = cwd or Path.cwd()
        p      = Path(instance.data_dir)
        ga_dir = p if p.is_absolute() else base / p

        return cls(context=ctx, instance=instance, paths=GAPaths(ga_dir))

    @property
    def name(self) -> str:
        return self.instance.name

    @property
    def port(self) -> int:
        return self.instance.port

    @property
    def data_dir(self) -> str:
        return self.instance.data_dir