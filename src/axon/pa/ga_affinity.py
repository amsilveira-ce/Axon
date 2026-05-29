"""
pa/ga_affinity.py — GAAffinityStore

Bandit UCB1 que aprende, por (gateway, capability), qual Gateway Agent tende a
entregar o melhor recurso. Usado pelo Resolver no Step 2 para ordenar quais GAs
consultar primeiro para uma dada capability (exploração x exploração).

Reward de cada consulta ∈ [0,1], combinando três sinais em DUAS fases:

  resolução (update_partial):
    match  (W_MATCH) — qualidade do match retornado pelo GA   (match_score 0..1)
    speed  (W_SPEED) — rapidez da resposta do GA              (de latency_ms)
  pós-execução (update_final):
    exec   (W_EXEC)  — o recurso escolhido executou com sucesso?

  update_partial() registra match+speed como um novo sample do reward médio.
  update_final()  acrescenta o componente de execução ao MESMO sample.
  → Assume-se que update_final(query) é chamado antes do próximo
    update_partial para o mesmo (gateway, capability). Suficiente para o fluxo
    sequencial resolução→execução do PA.

Persistência: JSON em { "gateways": { ga_url: { capability: GAAffinityEntry } } }.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel


# pesos do reward (somam 1.0) — calibração livre do operador
#   parcial (resolução): match×W_MATCH + speed×W_SPEED
#   final (execução):    + success×W_EXEC  (adicionado pelo Executor)
W_MATCH = 0.5
W_SPEED = 0.3
W_EXEC  = 0.2

# constante de exploração do UCB1 (o "2" clássico de reward_mean + √(2·lnN/n))
_UCB_C = 2.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _speed_from_latency(latency_ms: float) -> float:
    """latência → score [0,1]: 0ms→1.0, 1s→0.5, decai suave. Nunca negativo."""
    if latency_ms <= 0:
        return 1.0
    return 1.0 / (1.0 + latency_ms / 1000.0)


class GAAffinityEntry(BaseModel):
    query_count:  int             = 0
    reward_mean:  float           = 0.0
    last_updated: datetime | None = None


class GAAffinityStore:
    """
    UCB1 por (gateway, capability).

    Estrutura interna: { ga_url: { capability: GAAffinityEntry } }
    """

    def __init__(self, table: dict[str, dict[str, GAAffinityEntry]] | None = None) -> None:
        self._table: dict[str, dict[str, GAAffinityEntry]] = table or {}

    # ── acesso interno ─────────────────────────────────────────────────────────

    def _entry(self, ga_url: str, capability: str) -> GAAffinityEntry:
        return self._table.setdefault(ga_url, {}).setdefault(capability, GAAffinityEntry())

    def total_queries(self, capability: str) -> int:
        """Total de consultas para uma capability somando todos os GAs (o N do UCB1)."""
        return sum(
            caps[capability].query_count
            for caps in self._table.values()
            if capability in caps
        )

    # ── UCB ─────────────────────────────────────────────────────────────────────

    def ucb_score(self, ga_url: str, capability: str, total_queries: int) -> float:
        """
        Score UCB1 do par (ga_url, capability).

        query_count == 0 → +infinito (nunca testado: explora primeiro).
        senão            → reward_mean + √(2 · ln(total_queries) / query_count).
        """
        entry = self._table.get(ga_url, {}).get(capability)
        if entry is None or entry.query_count == 0:
            return float("inf")
        if total_queries < 1:
            return entry.reward_mean
        exploration = math.sqrt(_UCB_C * math.log(total_queries) / entry.query_count)
        return entry.reward_mean + exploration

    def ranked_gateways(self, capability: str) -> list[str]:
        """
        GAs conhecidos para a capability, ordenados por UCB desc.
        GAs nunca testados (score infinito) vêm primeiro.
        """
        total = self.total_queries(capability)
        gas = [ga for ga, caps in self._table.items() if capability in caps]
        gas.sort(key=lambda ga: self.ucb_score(ga, capability, total), reverse=True)
        return gas

    # ── updates (duas fases) ─────────────────────────────────────────────────────

    def update_partial(
        self, ga_url: str, capability: str, match_score: float, latency_ms: float
    ) -> None:
        """Fase 1 (resolução): novo sample do reward com match + speed."""
        entry   = self._entry(ga_url, capability)
        partial = W_MATCH * _clamp01(match_score) + W_SPEED * _speed_from_latency(latency_ms)
        entry.query_count += 1
        # média incremental: mean += (x - mean) / n
        entry.reward_mean += (partial - entry.reward_mean) / entry.query_count
        entry.last_updated = _now()

    def update_final(self, ga_url: str, capability: str, execution_success: bool) -> None:
        """Fase 2 (pós-execução): soma o componente de execução ao sample mais recente."""
        entry = self._table.get(ga_url, {}).get(capability)
        if entry is None or entry.query_count == 0:
            return  # nada parcial para completar
        r_exec = W_EXEC * (1.0 if execution_success else 0.0)
        # cada sample contribui 1/n para a média → adiciona o componente exec ao último
        entry.reward_mean += r_exec / entry.query_count
        entry.last_updated = _now()

    # ── persistência ─────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, path: Path) -> "GAAffinityStore":
        if not path.exists():
            return cls()
        raw     = json.loads(path.read_text(encoding="utf-8"))
        gateways = raw.get("gateways", raw)  # tolera formato sem wrapper
        table = {
            ga: {cap: GAAffinityEntry.model_validate(e) for cap, e in caps.items()}
            for ga, caps in gateways.items()
        }
        return cls(table)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": "0.1.0",
            "gateways": {
                ga: {cap: e.model_dump(mode="json") for cap, e in caps.items()}
                for ga, caps in self._table.items()
            },
        }
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
