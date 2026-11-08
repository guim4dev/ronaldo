"""Modo voz: estado ligado/desligado, texto falável, motores TTS e Falador.

O Falador consulta o andamento das falas no comando `resposta` do config e fala
cada resposta uma única vez. Tudo é local: `say` do macOS ou Wyoming
(Kokoro/Piper na LAN).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.parse
import wave
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.12 always has it
    import tomli as tomllib  # type: ignore[no-redef]

from .agent import login_path

log = logging.getLogger("ronaldo.voz")

CONFIG = Path.home() / ".config" / "ronaldo" / "config.toml"
ESTADO = Path.home() / ".config" / "ronaldo" / "modo-voz.json"
FALADOS = Path.home() / ".config" / "ronaldo" / "falados.json"

AVISO = " O resto está no app."
MOTORES_PADRAO = ["say:Luciana"]
VOLUME_PADRAO = 0.3
TIMEOUT_MOTOR = 4.0
PRAZO_FALADOR = 15 * 60
INTERVALO_FALADOR = 1.0
TIMEOUT_RESPOSTA = 10.0
LIMITE_FALADOS = 500
ENVIADO_PADRAO = "Enviado."
LIGADO_PADRAO = "As respostas vão ser faladas."


# ---------------------------------------------------------------- estado


def _resolver(path: Path | None, padrao: Path) -> Path:
    return Path(path) if path is not None else padrao


def _escrever_estado(valor: bool, path: Path | None = None) -> None:
    destino = _resolver(path, ESTADO)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(destino.name + ".tmp")
    temporario.write_text(json.dumps({"ligado": bool(valor)}), encoding="utf-8")
    os.replace(temporario, destino)


def ligar(path: Path | None = None) -> None:
    _escrever_estado(True, path)


def desligar(path: Path | None = None) -> None:
    _escrever_estado(False, path)


def _ligado(path: Path | None = None) -> bool:
    origem = _resolver(path, ESTADO)
    try:
        dados = json.loads(origem.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(dados.get("ligado")) if isinstance(dados, dict) else False


def ligado(path: Path | None = None) -> bool:
    """Lido a cada uso: app e voz escrevem no mesmo arquivo."""
    return _ligado(path)


# ---------------------------------------------------------------- gravação

_gravando = threading.Event()


def marcar_gravando(valor: bool) -> None:
    if valor:
        _gravando.set()
    else:
        _gravando.clear()


def gravando() -> bool:
    return _gravando.is_set()


# ---------------------------------------------------------------- texto


def _sem_simbolos(texto: str) -> str:
    """Remove emojis e símbolos, preservando letras, números e pontuação de fala."""
    manter = {"So": False, "Sk": False, "Sc": False, "Sm": False, "Cf": False, "Co": False, "Cs": False, "Cn": False}
    return "".join(c for c in texto if manter.get(unicodedata.category(c), True))


_URL = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
_TOKEN = re.compile(r"⟦[^⟧]*⟧")
_CERCA = re.compile(r"(?:```|~~~).*?(?:```|~~~)", re.S)
_CODIGO = re.compile(r"`[^`\n]*`")
_IMAGEM = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_CAMINHO_ABS = re.compile(r"(?<![\w/])(?:~|\.{1,2})?(?:/[\w.@+-]+){2,}/?")
_CAMINHO_REL = re.compile(r"(?<![\w/])(?:[\w.@+-]+/){2,}[\w.@+-]+")
_RONALDO = re.compile(r"\bronaldo\b", re.IGNORECASE)
_MARCA = re.compile(r"[#*_>]")
_ESPACOS = re.compile(r"\s+")
_PONTUACAO_FINAL = " ,;:—-"


def _frases(texto: str) -> list[str]:
    """Divide em frases inteiras; não confunde a inicial "R." com fim de frase."""
    frases: list[str] = []
    inicio = 0
    for encontro in re.finditer(r"[.!?…]+(?=\s|$)", texto):
        fim = encontro.end()
        if fim - inicio <= 2 and texto[inicio:inicio + 1].isalpha():
            continue  # inicial, ex.: "R."
        frases.append(texto[inicio:fim].strip())
        inicio = fim
    resto = texto[inicio:].strip()
    if resto:
        frases.append(resto)
    return frases


def essencial(texto: str, limite: int = 300) -> str:
    """O texto que vale a pena falar: curto, sem código e sem acordar o Ronaldo."""
    if not texto or not texto.strip():
        return ""

    t = texto.replace("\r\n", "\n").replace("\r", "\n")
    t = _CERCA.sub(" ", t)
    t = _CODIGO.sub(" ", t)
    t = _IMAGEM.sub(" ", t)
    t = _LINK.sub(r"\1", t)
    t = _TOKEN.sub(" ", t)
    t = _URL.sub(" ", t)
    t = _CAMINHO_ABS.sub(" ", t)
    t = _CAMINHO_REL.sub(" ", t)
    t = _MARCA.sub(" ", t)
    t = _sem_simbolos(t)
    t = _ESPACOS.sub(" ", t).strip()
    if not t:
        return ""

    if len(t) <= limite:
        return _com_ronaldo(t)

    teto = max(0, limite - len(AVISO))
    escolhidas: list[str] = []
    total = 0
    for frase in _frases(t):
        extra = len(frase) + (1 if escolhidas else 0)
        if total + extra > teto:
            break
        escolhidas.append(frase)
        total += extra

    if escolhidas:
        trecho = " ".join(escolhidas).rstrip(_PONTUACAO_FINAL)
        if not trecho:
            return ""
        return _com_ronaldo(trecho + AVISO)

    trecho = t[:teto]
    if " " in trecho:
        trecho = trecho.rsplit(" ", 1)[0]
    trecho = trecho.rstrip(_PONTUACAO_FINAL)
    if not trecho:
        return ""
    return _com_ronaldo(trecho + AVISO)


def _com_ronaldo(texto: str) -> str:
    return _RONALDO.sub("R.", texto)


# ---------------------------------------------------------------- config


@dataclass
class VozConfig:
    motores: list[str] = field(default_factory=lambda: list(MOTORES_PADRAO))
    volume: float = VOLUME_PADRAO
    enviar: list[str] = field(default_factory=list)
    resposta: list[str] = field(default_factory=list)
    enviado: str = ENVIADO_PADRAO
    ligado: str = LIGADO_PADRAO

    @classmethod
    def from_dict(cls, dados: object) -> "VozConfig":
        if not isinstance(dados, dict):
            return cls()
        motores = dados.get("motores")
        if not (isinstance(motores, list) and motores and all(isinstance(m, str) and m.strip() for m in motores)):
            motores = list(MOTORES_PADRAO)
        volume = dados.get("volume")
        if isinstance(volume, bool) or not isinstance(volume, (int, float)):
            volume = VOLUME_PADRAO
        return cls(
            [m.strip() for m in motores],
            float(volume),
            _argv(dados.get("enviar")),
            _argv(dados.get("resposta")),
            _texto(dados.get("enviado"), ENVIADO_PADRAO),
            _texto(dados.get("ligado"), LIGADO_PADRAO),
        )

    @classmethod
    def load(cls, path: Path | None = None) -> "VozConfig":
        origem = _resolver(path, CONFIG)
        try:
            dados = tomllib.loads(origem.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return cls()
        return cls.from_dict(dados.get("voz", {}))


def _argv(valor: object) -> list[str]:
    if isinstance(valor, list) and valor and all(isinstance(a, str) and a for a in valor):
        return list(valor)
    return []


def _texto(valor: object, padrao: str) -> str:
    return valor.strip() if isinstance(valor, str) and valor.strip() else padrao


# ---------------------------------------------------------------- placeholders


_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][\w-]*)\}")


def campos(nomes: list[str]) -> str:
    return ", ".join("{" + nome + "}" for nome in nomes)


def substituir(template: list[str], valores: dict[str, str]) -> tuple[list[str], list[str]]:
    """Troca {nome} pelos valores; devolve o argv e os nomes que ficaram sem valor."""
    faltando: list[str] = []
    argv: list[str] = []
    for item in template:
        for nome in _PLACEHOLDER.findall(item):
            if nome not in valores and nome not in faltando:
                faltando.append(nome)
        argv.append(_PLACEHOLDER.sub(lambda m: valores.get(m.group(1), m.group(0)), item))
    return argv, faltando


def formatar(template: str, valores: dict[str, str]) -> tuple[str, list[str]]:
    """Troca {nome} no texto; devolve o texto e os nomes que ficaram sem valor."""
    faltando: list[str] = []
    for nome in _PLACEHOLDER.findall(template):
        if nome not in valores and nome not in faltando:
            faltando.append(nome)
    return _PLACEHOLDER.sub(lambda m: valores.get(m.group(1), m.group(0)), template), faltando


# ---------------------------------------------------------------- motores


class Player:
    """Um processo de áudio por vez, guardado para poder ser morto."""

    def __init__(self) -> None:
        self._estado = threading.Lock()
        self._execucao = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._epoca = 0

    @property
    def epoca(self) -> int:
        """Muda a cada stop(): quem guardou a época sabe que foi cancelado."""
        with self._estado:
            return self._epoca

    def run(self, argv: list[str], *, timeout: float | None = None, epoca: int | None = None) -> int:
        """Roda um processo de áudio. Com `epoca`, não roda se houve stop() desde ela."""
        with self._execucao:
            with self._estado:
                if epoca is not None and epoca != self._epoca:
                    return -1  # cancelado antes de começar (ex.: parar() durante a síntese)
                epoca = self._epoca
            try:
                proc = subprocess.Popen(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError as exc:
                log.warning("voz: não consegui executar %s: %s", argv[0], exc)
                return -1
            with self._estado:
                if epoca != self._epoca:  # stop() chegou entre o spawn e o registro
                    self._terminar(proc)
                    return -1
                self._proc = proc
            try:
                return proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._terminar(proc)
                return -1
            finally:
                with self._estado:
                    if self._proc is proc:
                        self._proc = None

    def play(self, caminho: str | Path, volume: float, epoca: int | None = None) -> bool:
        return self.run(["afplay", "-v", f"{volume:g}", str(caminho)], epoca=epoca) == 0

    def stop(self) -> None:
        with self._estado:
            self._epoca += 1
            proc = self._proc
        if proc is not None and proc.poll() is None:
            log.info("voz: parando áudio")
            self._terminar(proc)

    @staticmethod
    def _terminar(proc: subprocess.Popen) -> None:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass


def _temporario(sufixo: str) -> str:
    fd, caminho = tempfile.mkstemp(prefix="ronaldo-voz-", suffix=sufixo)
    os.close(fd)
    return caminho


def _sintetizar_say(texto: str, voz: str, timeout: float, player: Player, epoca: int | None = None) -> str | None:
    caminho = _temporario(".aiff")
    if player.run(["say", "-v", voz, "-r", "190", "-o", caminho, texto], timeout=timeout, epoca=epoca) != 0:
        _apagar(caminho)
        return None
    return caminho


def _apagar(caminho: str) -> None:
    try:
        os.unlink(caminho)
    except FileNotFoundError:
        pass


def _parse_wyoming(motor: str) -> tuple[str, int, str | None]:
    url = urllib.parse.urlparse(motor)
    if not url.hostname or url.port is None:
        raise ValueError(f"motor wyoming inválido: {motor}")
    voz = urllib.parse.unquote(url.fragment) or None
    return url.hostname, url.port, voz


async def _sintetizar_wyoming_async(texto: str, host: str, porta: int, voz: str | None, destino: str) -> None:
    from wyoming.audio import AudioChunk, AudioStop
    from wyoming.client import AsyncClient
    from wyoming.tts import Synthesize, SynthesizeVoice

    cliente = AsyncClient.from_uri(f"tcp://{host}:{porta}")
    await cliente.connect()
    try:
        sintese = Synthesize(text=texto, voice=SynthesizeVoice(name=voz) if voz else None)
        await cliente.write_event(sintese.event())
        with wave.open(destino, "wb") as wav:
            formato = None
            while True:
                evento = await cliente.read_event()
                if evento is None:
                    raise RuntimeError("conexão encerrada antes do AudioStop")
                if AudioChunk.is_type(evento.type):
                    pedaco = AudioChunk.from_event(evento)
                    if formato is None:
                        formato = (pedaco.rate, pedaco.width, pedaco.channels)
                        wav.setframerate(pedaco.rate)
                        wav.setsampwidth(pedaco.width)
                        wav.setnchannels(pedaco.channels)
                    wav.writeframes(pedaco.audio)
                elif AudioStop.is_type(evento.type):
                    break
            if formato is None:
                raise RuntimeError("resposta sem áudio")
    finally:
        try:
            await cliente.disconnect()
        except Exception:  # noqa: BLE001 - desconexão nunca deve mascarar o erro real
            pass


def _sintetizar_wyoming(texto: str, host: str, porta: int, voz: str | None, timeout: float) -> str | None:
    destino = _temporario(".wav")
    try:
        asyncio.run(asyncio.wait_for(_sintetizar_wyoming_async(texto, host, porta, voz, destino), timeout))
    except Exception as exc:  # noqa: BLE001 - qualquer falha cai para o próximo motor
        log.warning("voz: wyoming %s:%s falhou: %s", host, porta, exc)
        _apagar(destino)
        return None
    return destino


def falar_texto(
    texto: str,
    *,
    motores: list[str] | None = None,
    volume: float | None = None,
    timeout: float = TIMEOUT_MOTOR,
    player: Player | None = None,
    epoca: int | None = None,
) -> bool:
    """Tenta cada motor da cadeia; o próximo só entra se o anterior falhar."""
    if not texto or not texto.strip():
        return False
    cfg = VozConfig.load()
    cadeia = list(motores) if motores is not None else cfg.motores
    volume = cfg.volume if volume is None else volume
    player = player or Player()
    if epoca is None:
        epoca = player.epoca  # stop() a partir daqui cancela síntese, fallback e playback

    for motor in cadeia:
        if player.epoca != epoca:
            log.info("voz: cancelada antes do motor %s", motor)
            return False
        caminho: str | None = None
        try:
            if motor.startswith("say:"):
                voz = motor.split(":", 1)[1].strip()
                if not voz:
                    log.warning("voz: motor say sem voz: %s", motor)
                    continue
                caminho = _sintetizar_say(texto, voz, timeout, player, epoca)
            elif motor.startswith("wyoming://"):
                host, porta, voz = _parse_wyoming(motor)
                caminho = _sintetizar_wyoming(texto, host, porta, voz, timeout)
            else:
                log.warning("voz: motor desconhecido: %s", motor)
                continue
        except Exception as exc:  # noqa: BLE001 - falhou ou estourou: tenta o próximo
            log.warning("voz: motor %s falhou: %s", motor, exc)
            continue

        if caminho is None:
            continue
        try:
            if player.epoca != epoca:
                log.info("voz: cancelada depois da síntese do motor %s; não toca", motor)
                return False
            if player.play(caminho, volume, epoca=epoca):
                return True
            if player.epoca != epoca:
                return False  # parada no meio do áudio: não cai pro próximo motor
            log.warning("voz: falha ao tocar áudio do motor %s", motor)
        finally:
            _apagar(caminho)
    return False


# ---------------------------------------------------------------- resposta


_caminho_login: str | None = None


def _path_login() -> str:
    global _caminho_login
    if _caminho_login is None:
        _caminho_login = login_path()
    return _caminho_login


def consultar_resposta(id: str, contexto: dict | None = None, *, path: str | None = None, timeout: float = TIMEOUT_RESPOSTA) -> dict:
    """Roda o comando `[voz].resposta` do config e devolve o JSON."""
    cfg = VozConfig.load()
    if not cfg.resposta:
        raise RuntimeError("config sem [voz].resposta")
    valores = {k: v for k, v in (contexto or {}).items() if isinstance(k, str) and isinstance(v, str)}
    valores["id"] = str(id)
    argv, faltando = substituir(cfg.resposta, valores)
    if faltando:
        raise RuntimeError(f"a resposta pede {campos(faltando)}, que não veio no envio")
    env = {**os.environ, "PATH": path or _path_login()}
    resultado = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        cwd=os.path.expanduser("~"),
    )
    if resultado.returncode != 0:
        detalhe = resultado.stderr.strip() or resultado.stdout.strip() or f"código {resultado.returncode}"
        raise RuntimeError(detalhe)
    dados = json.loads(resultado.stdout)
    if not isinstance(dados, dict):
        raise ValueError("a resposta não é um objeto")
    return dados


# ---------------------------------------------------------------- falador


@dataclass
class _Pendente:
    id: str
    contexto: dict
    quando: float


class Falador:
    """Consulta o comando `resposta` a cada segundo e fala cada resposta pronta uma vez."""

    def __init__(
        self,
        *,
        consultar=None,
        falar=None,
        estado: Path | None = None,
        falados: Path | None = None,
        motores: list[str] | None = None,
        volume: float | None = None,
        intervalo: float = INTERVALO_FALADOR,
        prazo: float = PRAZO_FALADOR,
        relogio=None,
        ligado_fn=None,
        gravando_fn=None,
        automatico: bool = True,
    ) -> None:
        self.consultar = consultar or consultar_resposta
        self.player = Player()
        self._falar = falar or (
            lambda texto, em=None: falar_texto(texto, motores=motores, volume=volume, player=self.player, epoca=self._epoca_fala)
        )
        self.estado = estado
        self.falados = _resolver(falados, FALADOS)
        self.intervalo = intervalo
        self.prazo = prazo
        self.relogio = relogio or time.monotonic
        self._ligado_fn = ligado_fn or (lambda: _ligado(self.estado))
        self._gravando_fn = gravando_fn or gravando
        self.automatico = automatico

        self._lock = threading.Lock()
        self._fila: deque[_Pendente] = deque()
        self._thread: threading.Thread | None = None
        self._vigia: threading.Thread | None = None
        self._parar_thread = threading.Event()
        self._speak_lock = threading.Lock()
        self._atual: str | None = None
        self._cancelar = 0
        self._epoca_fala: int | None = None  # época do Player capturada junto com _cancelar
        self._ids = self._carregar()

    # -- persistência

    def _carregar(self) -> list[str]:
        try:
            dados = json.loads(self.falados.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(dados, list):
            return []
        return [str(item) for item in dados][-LIMITE_FALADOS:]

    def _salvar(self) -> None:
        self.falados.parent.mkdir(parents=True, exist_ok=True)
        temporario = self.falados.with_name(self.falados.name + ".tmp")
        temporario.write_text(json.dumps(self._ids[-LIMITE_FALADOS:]), encoding="utf-8")
        os.replace(temporario, self.falados)

    def ja_falado(self, id: str) -> bool:
        with self._lock:
            return id in self._ids

    def _marcar(self, id: str) -> None:
        if id not in self._ids:
            self._ids.append(id)
            del self._ids[:-LIMITE_FALADOS]
            self._salvar()

    # -- fila

    def iniciar(self) -> None:
        if not self.automatico:
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._loop, name="ronaldo-falador", daemon=True)
            self._vigia = threading.Thread(target=self._vigiar, name="ronaldo-voz-vigia", daemon=True)
            self._thread.start()
            self._vigia.start()

    def _vigiar(self) -> None:
        """O desligar chega por arquivo: para a fala atual mesmo com a fila ocupada."""
        while not self._parar_thread.is_set():
            if not self._ligado_fn():
                self.esvaziar()
            self._parar_thread.wait(self.intervalo)

    def enfileirar(self, id: str, contexto: dict | None = None, quando: float | None = None) -> bool:
        if not id:
            return False
        contexto = dict(contexto or {})
        with self._lock:
            if id in self._ids or any(p.id == id for p in self._fila):
                return False
            self._fila.append(_Pendente(str(id), contexto, self.relogio() if quando is None else quando))
        self.iniciar()
        return True

    def pendentes(self) -> list[tuple[str, dict]]:
        with self._lock:
            return [(p.id, dict(p.contexto)) for p in self._fila]

    # -- fala

    def _loop(self) -> None:
        while not self._parar_thread.is_set():
            try:
                self.passo()
            except Exception:  # noqa: BLE001 - a thread não pode morrer
                log.exception("voz: falha no Falador")
            self._parar_thread.wait(self.intervalo)

    def passo(self) -> None:
        """Um ciclo: resolve a fila, consulta o serviço de respostas e fala o que ficou pronto."""
        if not self._ligado_fn():
            self.esvaziar()
            return
        if self._gravando_fn():
            return

        agora = self.relogio()
        expirados: list[_Pendente] = []
        with self._lock:
            for item in list(self._fila):
                if agora - item.quando > self.prazo:
                    self._fila.remove(item)
                    expirados.append(item)
            pendentes = list(self._fila)
        for item in expirados:
            log.warning("voz: descartado por prazo id=%s", item.id)

        prontos: list[tuple[_Pendente, str, object]] = []
        for item in pendentes:
            try:
                resposta = self.consultar(item.id, item.contexto)
            except Exception as exc:  # noqa: BLE001 - tenta de novo no próximo ciclo
                log.warning("voz: falha ao consultar id=%s: %s", item.id, exc)
                continue
            if not isinstance(resposta, dict) or resposta.get("estado") != "pronta":
                continue
            texto = resposta.get("texto")
            if isinstance(texto, str) and texto.strip():
                prontos.append((item, texto, resposta.get("em")))

        for item, texto, em in prontos:
            if not self._ligado_fn() or self._gravando_fn():
                return
            with self._lock:
                if self._gravando_fn():  # a wake word chegou entre a consulta e a fala
                    return
                if item.id in self._ids:
                    if item in self._fila:
                        self._fila.remove(item)
                    continue
                if item in self._fila:
                    self._fila.remove(item)
                self._marcar(item.id)
                self._atual = item.id
                cancelar = self._cancelar
                self._epoca_fala = self.player.epoca
            self._falar_pronto(item, texto, em, cancelar)

    def _falar_pronto(self, item: _Pendente, texto: str, em: object, cancelar: int) -> None:
        fala = essencial(texto)
        log.info("voz: resposta pronta id=%s em=%s", item.id, em)
        if not fala:
            with self._lock:
                self._atual = None
            return
        latencia = None
        if isinstance(em, (int, float)) and not isinstance(em, bool):
            latencia = max(0.0, time.time() - float(em))
        with self._speak_lock:
            with self._lock:
                interrompido = cancelar != self._cancelar
                if interrompido:
                    self._atual = None
            if interrompido:
                return
            if latencia is None:
                log.info("voz: começou")
            else:
                log.info("voz: começou latência=%.2fs (desde em)", latencia)
            try:
                ok = bool(self._falar(fala, em=em))
            except Exception:  # noqa: BLE001 - uma fala ruim não pode matar a fila
                log.exception("voz: exceção ao falar id=%s", item.id)
                ok = False
            finally:
                log.info("voz: acabou")
            if not ok:
                log.warning("voz: nenhum motor falou id=%s", item.id)
        with self._lock:
            self._atual = None

    def falar_agora(self, texto: str) -> bool:
        """Confirmação curta, fora da fila e sem consultar o serviço de respostas."""
        fala = essencial(texto)
        if not fala:
            return False
        self.player.stop()
        with self._speak_lock:
            self._epoca_fala = self.player.epoca
            try:
                return bool(self._falar(fala, em=None))
            except Exception:  # noqa: BLE001
                log.exception("voz: exceção ao falar agora")
                return False
            finally:
                log.info("voz: acabou")

    def parar(self) -> None:
        """Mata o áudio na hora e marca o item atual como falado."""
        self.player.stop()
        with self._lock:
            self._cancelar += 1
            if self._atual is not None:
                self._marcar(self._atual)
                self._atual = None

    def esvaziar(self) -> None:
        """Modo desligado: para a fala atual e joga a fila fora."""
        self.player.stop()
        with self._lock:
            self._cancelar += 1
            if self._atual is not None:
                self._marcar(self._atual)
                self._atual = None
            self._fila.clear()


# ---------------------------------------------------------------- global


_FALADOR: Falador | None = None
_FALADOR_LOCK = threading.Lock()


def falador() -> Falador:
    global _FALADOR
    with _FALADOR_LOCK:
        if _FALADOR is None:
            _FALADOR = Falador()
        return _FALADOR


def enfileirar(id: str, contexto: dict | None = None, quando: float | None = None) -> bool:
    return falador().enfileirar(id, contexto, quando)


def parar() -> None:
    if _FALADOR is not None:
        _FALADOR.parar()


def falar_agora(texto: str) -> bool:
    if not ligado():
        return False
    return falador().falar_agora(texto)


# ---------------------------------------------------------------- comandos


_MODOS = ("modo voz", "modo tts", "modo fala")
_VERBOS_LIGAR = ("", "ligar ", "liga o ", "ativar ", "ativa o ")
_VERBOS_DESLIGAR = ("desligar ", "desliga o ", "desativar ", "desativa o ")
FRASES_LIGAR = {v + m for v in _VERBOS_LIGAR for m in _MODOS} | {"liga a voz", "ligar a voz"}
FRASES_DESLIGAR = {v + m for v in _VERBOS_DESLIGAR for m in _MODOS} | {"modo texto", "desliga a voz", "desligar a voz"}


def normalizar_comando(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto.casefold())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^\w\s]", " ", t)
    return _ESPACOS.sub(" ", t).strip()


def comando_modo(texto: str) -> str | None:
    """Classifica um comando curto de voz; None quando não é comando."""
    t = normalizar_comando(texto)
    if t.startswith("ronaldo "):
        t = t[len("ronaldo "):].strip()
    if not t or len(t.split()) > 5:
        return None
    if t in FRASES_LIGAR:
        return "ligar"
    if t in FRASES_DESLIGAR:
        return "desligar"
    return None


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    uso = 'uso: ronaldo-voz on|off|status|falar "<texto>"'
    if not args:
        print(uso, file=sys.stderr)
        return 2
    comando = args[0]
    if comando == "on":
        ligar()
        print("Modo voz ligado.")
        return 0
    if comando == "off":
        desligar()
        print("Modo texto.")
        return 0
    if comando == "status":
        print("ligado" if ligado() else "desligado")
        return 0
    if comando == "falar":
        texto = " ".join(args[1:]).strip()
        if not texto:
            print(uso, file=sys.stderr)
            return 2
        return 0 if falar_texto(texto) else 1
    print(uso, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
