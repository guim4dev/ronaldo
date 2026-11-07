"""Portão de grito: só libera o som quando o nível fica X dB acima da fala normal.

Tudo vive em memória: nada é gravado em disco e não há piso absoluto de volume.
A referência é a mediana do RMS dos chunks de fala dos últimos ~5 min; sem 20 s
de fala acumulada não há referência e o portão barra qualquer candidato. Se o
ganho do microfone mudar mais de 6 dB, a referência é invalidada e precisa de
20 s de fala nova. O tempo é contado em chunks de 80 ms, como no resto do
Listener, para os testes serem determinísticos.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass

import numpy as np

from .detector import CHUNK, SAMPLE_RATE

log = logging.getLogger("ronaldo.grito")

PASSO = CHUNK / SAMPLE_RATE  # 80 ms
SILENCIO_DB = -100.0


def rms_dbfs(chunk: np.ndarray) -> float:
    """RMS do chunk em dBFS (0 dB = fundo de escala de int16)."""
    amostras = np.asarray(chunk, dtype=np.float64) / 32768.0
    if amostras.size == 0:
        return SILENCIO_DB
    rms = float(np.sqrt(np.mean(amostras * amostras)))
    if rms <= 0.0:
        return SILENCIO_DB
    return max(SILENCIO_DB, 20.0 * math.log10(rms))


@dataclass(frozen=True)
class Decisao:
    liberado: bool
    nivel: float
    referencia: float | None
    motivo: str


class PortaoGrito:
    """Classe pura (sem áudio, sem disco): observe chunks e avalie candidatos."""

    def __init__(
        self,
        *,
        janela_nivel: int = 13,
        janela_referencia_s: float = 300.0,
        referencia_min_s: float = 20.0,
        janela_recalibragem_s: float = 10.0,
        recalibragem_min_s: float = 5.0,
        desvio_db: float = 6.0,
    ) -> None:
        self.janela_nivel = janela_nivel
        self.janela_referencia = int(round(janela_referencia_s / PASSO))
        self.referencia_min = int(round(referencia_min_s / PASSO))
        self.janela_recalibragem = int(round(janela_recalibragem_s / PASSO))
        self.recalibragem_min = int(round(recalibragem_min_s / PASSO))
        self.desvio_db = desvio_db
        self._chunk = 0
        self._niveis: deque[float] = deque(maxlen=janela_nivel)
        self._recentes: deque[tuple[int, float, bool]] = deque(maxlen=self.janela_recalibragem)
        self._fala: deque[tuple[int, float]] = deque()

    @property
    def nivel(self) -> float:
        """Pico do RMS em dBFS nos últimos 13 chunks (~1,0 s)."""
        return max(self._niveis, default=SILENCIO_DB)

    @property
    def referencia(self) -> float | None:
        """Mediana da fala dos últimos ~5 min; None enquanto não houver 20 s."""
        if len(self._fala) < self.referencia_min:
            return None
        return float(np.median([db for _, db in self._fala]))

    @property
    def fala_acumulada(self) -> float:
        """Segundos de fala (VAD >= 0,5) dentro da referência atual."""
        return len(self._fala) * PASSO

    def observar(self, chunk: np.ndarray, fala: bool) -> float:
        """Registra um chunk de áudio; `fala` é VAD >= limiar."""
        self._chunk += 1
        db = rms_dbfs(chunk)
        self._niveis.append(db)
        self._recentes.append((self._chunk, db, bool(fala)))
        if fala:
            self._fala.append((self._chunk, db))
        self._podar()
        self._recalibrar()
        return db

    def avaliar(self, nota: float, grito_db_acima: float) -> Decisao:
        """Compara o nível atual com a referência e registra o candidato."""
        nivel = self.nivel
        referencia = self.referencia
        if referencia is None:
            liberado, motivo = False, "sem referência"
        elif nivel >= referencia + grito_db_acima:
            liberado, motivo = True, "grito"
        else:
            liberado, motivo = False, "abaixo do limiar"
        log.info(
            "grito: nota %.2f nível %.1f dBFS ref %s liberado=%s (%s)",
            nota,
            nivel,
            "—" if referencia is None else f"{referencia:.1f} dB",
            liberado,
            motivo,
        )
        return Decisao(liberado, nivel, referencia, motivo)

    def _podar(self) -> None:
        limite = self._chunk - self.janela_referencia
        while self._fala and self._fala[0][0] <= limite:
            self._fala.popleft()

    def _recalibrar(self) -> None:
        """Ganho do mic mudou: invalida a referência e exige 20 s de fala nova."""
        referencia = self.referencia
        if referencia is None:
            return
        recentes = [db for _, db, fala in self._recentes if fala]
        if len(recentes) < self.recalibragem_min:
            return
        mediana = float(np.median(recentes))
        if abs(mediana - referencia) > self.desvio_db:
            log.info("referência de grito recalibrando: %.1f dB → %.1f dB", referencia, mediana)
            self._fala.clear()
