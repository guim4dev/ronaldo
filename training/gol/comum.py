#!/usr/bin/env python3
"""Utilidades compartilhadas por gerar_positivos.py / gerar_negativos.py / features.py.

Regras do projeto:
- tudo mora em $GOL_DATA (padrao ~/data/gol); nada de audio no git;
- audio sempre 16 kHz mono int16;
- a sintese usa o binario piper (raw/piper/piper/piper) e o edge-tts;
- o aumento "grito" usa ffmpeg rubberband (pitch e time-stretch sem mudar a
  taxa de amostragem) e numpy/scipy para ruido, RIR e compressao.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

SR = 16000
JANELA = 2 * SR  # 2 s: 16 embeddings de 96 dimensoes (passo 8, janela mel 76)

ROOT = Path(os.environ.get("GOL_DATA", Path.home() / "data" / "gol")).expanduser()
RAW = ROOT / "raw"
WORK = ROOT / "work"
FEATURES = ROOT / "features"

AQUI = Path(__file__).resolve().parent
MODELS = AQUI.parent.parent / "models"  # ronaldo-treino/models

VOZES_TREINO = ["faber", "edresson", "cadu"]
VOZES_TESTE = ["jeff"]
EDGE_TESTE = [
    "pt-BR-FranciscaNeural",
    "pt-BR-AntonioNeural",
    "pt-BR-ThalitaNeural",
    "pt-PT-RaquelNeural",
    "pt-PT-DuarteNeural",
]

TEXTOS_POSITIVOS = [
    "gol!",
    "gool!",
    "gooool!",
    "goooooooool!",
    "golaço!",
    "golaaaaço!",
    "é gol!",
    "gol gol gol!",
]

# Falas normais com "gol" no meio (negativo dificil).
FRASES_GOL = [
    "o gol foi bonito",
    "que gol",
    "foi gol do Flamengo",
    "quantos gols",
    "o gol saiu aos quarenta e cinco",
    "ele fez o gol no final",
    "não foi gol, foi impedimento",
    "o gol do Corinthians foi de cabeça",
    "esse gol valeu a classificação",
    "o gol aconteceu no segundo tempo",
    "foi um gol muito importante",
    "o time comemorou o gol",
    "o goleiro não viu o gol",
    "o gol foi anulado pelo VAR",
    "quase saiu o gol",
    "o gol saiu depois do cruzamento",
    "foi gol de placa",
    "o gol veio numa jogada rápida",
    "ele gritou gol no estádio",
    "o narrador anunciou o gol",
    "o gol foi marcado de pênalti",
    "foi o gol mais bonito do jogo",
    "o gol do Palmeiras saiu no fim",
    "o gol do São Paulo foi contra",
    "o gol do Fluminense veio de falta",
    "o gol do Grêmio foi de bicicleta",
    "o gol do Internacional foi de cabeça",
    "o gol do Botafogo saiu no primeiro tempo",
    "o gol do Vasco foi de pênalti",
    "o gol do Santos foi de fora da área",
    "o gol do Cruzeiro veio de escanteio",
    "o gol do Atlético foi contra",
    "o gol do Bahia foi de falta",
    "o gol do Fortaleza foi no último minuto",
    "o gol do Sport foi de cabeça",
    "o gol do Náutico foi no começo",
    "o gol do Ceará saiu de bola parada",
    "o gol do Vitória foi de pênalti",
    "o gol do Coritiba foi de bicicleta",
    "o gol do Athletico veio de cruzamento",
    "o gol do Goiás foi de cabeça",
    "o gol do Cuiabá foi de fora da área",
    "o gol do Bragantino foi de falta",
    "o gol do América foi nos acréscimos",
    "o gol do Juventude foi de pênalti",
    "o gol do Avaí saiu no segundo tempo",
    "o gol do Chapecoense foi de cabeça",
    "o gol do Criciúma foi de falta",
    "o gol do Ituano foi de bicicleta",
    "o gol do Ponte Preta foi de pênalti",
    "o gol do Guarani saiu no fim",
    "o gol do Sampaio Corrêa foi de cabeça",
    "o gol do Remo foi de fora da área",
    "o gol do Paysandu saiu de falta",
    "o gol do ABC foi de pênalti",
    "o gol do América de Natal foi de cabeça",
    "o gol do Santa Cruz foi de bicicleta",
    "o gol do Náutico saiu no primeiro tempo",
    "o gol do Vitória foi de falta",
    "o gol do Bahia saiu de escanteio",
    "o gol do Ceará foi de cabeça",
    "o gol do Fortaleza saiu de bola parada",
    "o gol do Sport foi de pênalti",
    "o gol do Náutico foi de fora da área",
    "o gol do Central foi de cabeça",
    "o gol do Salgueiro foi de falta",
    "o gol do Retrô foi de pênalti",
    "o gol do Maguary saiu no fim",
    "o gol do Flamengo foi de bicicleta",
    "o gol do Flamengo saiu de falta",
    "o gol do Flamengo foi de cabeça",
    "o gol do Flamengo veio de escanteio",
    "o gol do Flamengo foi contra",
    "o gol do Flamengo saiu no último minuto",
    "o gol do Vasco foi de cabeça",
    "o gol do Vasco saiu de falta",
    "o gol do Vasco foi de fora da área",
    "o gol do Vasco veio de cruzamento",
    "o gol do Botafogo foi de pênalti",
    "o gol do Botafogo saiu de escanteio",
    "o gol do Botafogo foi de cabeça",
    "o gol do Fluminense saiu de falta",
    "o gol do Fluminense foi de bicicleta",
    "o gol do Fluminense veio de cruzamento",
    "o gol do Grêmio foi de pênalti",
    "o gol do Grêmio saiu de escanteio",
    "o gol do Internacional foi de falta",
    "o gol do Internacional saiu de bicicleta",
    "o gol do Corinthians foi de pênalti",
    "o gol do Corinthians saiu de falta",
    "o gol do Corinthians veio de escanteio",
    "o gol do Palmeiras foi de bicicleta",
    "o gol do Palmeiras saiu de falta",
    "o gol do Palmeiras veio de cruzamento",
    "o gol do São Paulo foi de pênalti",
    "o gol do São Paulo saiu de escanteio",
    "o gol do Santos foi de falta",
    "o gol do Santos veio de cruzamento",
    "o gol do Cruzeiro foi de bicicleta",
    "o gol do Cruzeiro saiu de escanteio",
    "o gol do Atlético foi de pênalti",
    "o gol do Atlético saiu de falta",
    "o gol do Athletico foi de cabeça",
    "o gol do Athletico saiu de escanteio",
    "o gol do Coritiba foi de pênalti",
    "o gol do Coritiba saiu de falta",
    "o gol do Goiás saiu de escanteio",
    "o gol do Goiás foi de pênalti",
    "o gol do Cuiabá saiu de falta",
    "o gol do Cuiabá foi de cabeça",
    "o gol do Bragantino foi de pênalti",
    "o gol do Bragantino saiu de escanteio",
    "o gol do Juventude foi de falta",
    "o gol do Juventude saiu de cabeça",
    "o gol do Avaí foi de pênalti",
    "o gol do Avaí saiu de falta",
    "o gol do Chapecoense saiu de escanteio",
    "o gol do Chapecoense foi de pênalti",
    "o gol do Criciúma saiu de falta",
    "o gol do Criciúma foi de cabeça",
    "o gol do Ituano saiu de escanteio",
    "o gol do Ituano foi de pênalti",
    "o gol do Ponte Preta saiu de falta",
    "o gol do Ponte Preta foi de cabeça",
    "o gol do Guarani saiu de escanteio",
    "o gol do Guarani foi de pênalti",
    "o gol do Sampaio Corrêa saiu de falta",
    "o gol do Sampaio Corrêa foi de pênalti",
    "o gol do Remo saiu de escanteio",
    "o gol do Remo foi de bicicleta",
    "o gol do Paysandu foi de pênalti",
    "o gol do Paysandu saiu de falta",
    "o gol do ABC saiu de escanteio",
    "o gol do ABC foi de cabeça",
    "o gol do Santa Cruz saiu de falta",
    "o gol do Santa Cruz foi de pênalti",
    "o gol do Central saiu de escanteio",
    "o gol do Central foi de pênalti",
    "o gol do Salgueiro saiu de falta",
    "o gol do Salgueiro foi de cabeça",
    "o gol do Retrô saiu de escanteio",
    "o gol do Retrô foi de pênalti",
    "o gol do Maguary saiu de falta",
    "o gol do Maguary foi de cabeça",
    "o gol foi de cabeça",
    "o gol foi de pênalti",
    "o gol foi de falta",
    "o gol foi de bicicleta",
    "o gol foi de fora da área",
    "o gol foi contra",
    "o gol foi no primeiro tempo",
    "o gol foi no segundo tempo",
    "o gol foi nos acréscimos",
    "o gol foi no último minuto",
    "o gol foi no começo do jogo",
    "o gol foi no fim do jogo",
    "o gol foi depois do cruzamento",
    "o gol foi numa jogada rápida",
    "o gol foi numa bola parada",
    "o gol foi num contra-ataque",
    "o gol foi de longe",
    "o gol foi de perto",
    "o gol foi de chute forte",
    "o gol foi de chute colocado",
    "o gol foi de cabeça no canto",
    "o gol foi de pênalti no canto",
    "o gol foi de falta no ângulo",
    "o gol foi de bicicleta no ângulo",
    "o gol foi de fora da área no ângulo",
    "o gol foi contra o goleiro",
    "o gol foi por cima do goleiro",
    "o gol foi por baixo do goleiro",
    "o gol foi no canto do goleiro",
    "o gol foi no meio do gol",
    "o gol foi no fundo do gol",
    "o gol foi na rede",
    "o gol foi no travessão",
    "o gol foi na trave",
    "o gol foi quase",
    "o gol foi anulado",
    "o gol foi confirmado",
    "o gol foi revisado",
    "o gol foi polêmico",
    "o gol foi legal",
    "o gol foi irregular",
    "o gol foi duvidoso",
    "o gol foi claro",
    "o gol foi bonito",
    "o gol foi feio",
    "o gol foi fácil",
    "o gol foi difícil",
    "o gol foi importante",
    "o gol foi decisivo",
    "o gol foi histórico",
    "o gol foi emocionante",
    "o gol foi incrível",
    "o gol foi fantástico",
    "o gol foi espetacular",
    "o gol foi sensacional",
    "o gol foi maravilhoso",
    "o gol foi lindo",
]


# Frases com "gol" no meio: a lista acima (201) + templates com times e
# predicados garante >= 300 frases distintas exigidas pelo contrato.
TIMES = [
    "Flamengo", "Vasco", "Botafogo", "Fluminense", "Grêmio", "Internacional",
    "Corinthians", "Palmeiras", "São Paulo", "Santos", "Cruzeiro", "Atlético",
    "Bahia", "Sport", "Fortaleza", "Ceará", "Vitória", "Goiás",
]
PREDICADOS = [
    "bonito", "de cabeça", "de pênalti", "de falta", "no fim", "no começo",
    "de fora da área", "de bicicleta",
]


def frases_com_gol() -> list[str]:
    """Todas as frases de fala normal que contem "gol" (>= 300, sem repetir)."""
    frases = list(FRASES_GOL)
    for time in TIMES:
        for predicado in PREDICADOS:
            frases.append(f"o gol do {time} foi {predicado}")
    return list(dict.fromkeys(frases))

# Palavras parecidas com "gol" (fora de contexto de grito).
FRASES_PARECIDAS = [
    "o sol está forte hoje",
    "eu tomei um copo de álcool",
    "a gola da camisa está larga",
    "o goleiro defendeu bem",
    "ele joga golfe no clube",
    "o Google me ajudou a achar",
    "o gado está no pasto",
    "eu vou para casa agora",
    "não sei se vai dar tempo",
    "vai chover mais tarde",
    "a gola polo é azul",
    "o goleiro pulou no canto",
    "o sol nasceu bonito",
    "o álcool acabou",
    "o golfe é um esporte caro",
    "o Google mudou a política",
    "o gado saiu do curral",
    "eu vou sair mais tarde",
    "ela não quer ir",
    "ele vai chegar cedo",
    "o sol queimou a planta",
    "o álcool gel acabou",
    "a gola da blusa é branca",
    "o goleiro ficou parado",
    "o campo de golfe é grande",
    "o Google Maps errou o caminho",
    "o gado bebeu água",
    "eu vou de ônibus",
    "não tenho tempo hoje",
    "vai ser difícil",
    "o sol apareceu depois da chuva",
    "o álcool é inflamável",
    "a gola da jaqueta é alta",
    "o goleiro treinou muito",
    "ele joga golfe aos domingos",
    "o Google anunciou novidades",
    "o gado come capim",
    "eu vou tentar de novo",
    "não sei o que fazer",
    "vai dar certo",
    "o sol está quente",
    "o álcool faz mal",
    "a gola rasgou",
    "o goleiro caiu",
    "o golfe não me interessa",
    "o Google é uma empresa",
    "o gado é criado aqui",
    "eu vou dormir cedo",
    "não vou sair hoje",
    "vai ficar tudo bem",
    "o sol secou a roupa",
    "o álcool evaporou",
    "a gola está suja",
    "o goleiro tomou o gol",
    "o golfe é caro",
    "o Google tem muitos serviços",
    "o gado andou pela estrada",
    "eu vou comprar pão",
    "não quero conversa",
    "vai começar o jogo",
    "o sol não apareceu",
    "o álcool não resolve",
    "a gola do casaco é quente",
    "o goleiro é alto",
    "o golfe é um esporte",
    "o Google oferece nuvem",
    "o gado voltou para o curral",
    "eu vou trabalhar",
    "não é assim",
    "vai ser rápido",
    "o sol bate na janela",
    "o álcool é líquido",
    "a gola está apertada",
    "o goleiro do time reserva",
    "o golfe tem poucos fãs",
    "o Google mudou o layout",
    "o gado precisa de água",
    "eu vou estudar",
    "não sei ainda",
    "vai ficar pronto",
    "o sol está no meio do céu",
    "o álcool é volátil",
    "a gola da camiseta é preta",
    "o goleiro defendeu o pênalti",
    "o golfe tem campo grande",
    "o Google pagou a multa",
    "o gado pastou o dia todo",
    "eu vou correndo",
    "não tem problema",
    "vai ser divertido",
    "o sol brilha no mar",
    "o álcool queimou",
    "a gola está amarela",
    "o goleiro ficou no chão",
    "o golfe é para poucos",
    "o Google lançou um produto",
    "o gado atravessou a rua",
    "eu vou voltar",
    "não sei dizer",
    "vai ser hoje",
    "o sol nasce no leste",
    "o álcool seca rápido",
    "a gola do vestido é decote",
    "o goleiro fechou o ângulo",
    "o golfe exige concentração",
    "o Google tem servidores",
    "o gado está gordo",
    "eu vou almoçar",
    "não é verdade",
    "vai dar tempo",
    "o sol está baixo",
    "o álcool gel secou",
    "a gola da farda é dura",
    "o goleiro fez grande defesa",
    "o golfe é jogado ao ar livre",
    "o Google comprou a empresa",
    "o gado está no cercado",
    "eu vou viajar",
    "não quero isso",
    "vai ser bom",
    "o sol aqueceu o chão",
    "o álcool é tóxico",
    "a gola da camisa é larga",
]

# Palavras curtas gritadas que NAO sao gol (negativo dificil com o mesmo aumento).
PALAVRAS_GRITADAS = ["vai!", "não!", "isso!", "boa!", "chuta!", "uh!"]

# Variacoes extras de fala normal (para o negativo nao ficar so com "gol").
FRASES_NEUTRAS = [
    "bom dia, tudo bem?",
    "eu estou indo agora",
    "o jogo começa mais tarde",
    "o time ganhou de dois a zero",
    "a defesa estava desorganizada",
    "o técnico pediu calma",
    "o juiz apitou o final",
    "o estádio estava cheio",
    "a torcida fez a festa",
    "o campeonato está apertado",
    "o atacante perdeu a chance",
    "o escanteio foi bem cobrado",
    "o zagueiro cortou o cruzamento",
    "o meio-campo dominou a partida",
    "o goleiro fez uma defesa difícil",
    "o time jogou bem no segundo tempo",
    "o treinador fez três substituições",
    "o árbitro deu dois minutos",
    "o estádio ficou em silêncio",
    "a torcida cantou alto",
    "o placar ficou igualado",
    "o jogo foi emocionante",
    "o time está na liderança",
    "o camisa dez foi o melhor",
    "o lateral subiu ao ataque",
    "o volante marcou de perto",
    "o zagueiro cabeceou para longe",
    "o atacante estava impedido",
    "o bandeirinha levantou a bandeira",
    "o VAR chamou o juiz",
    "o pênalti foi bem cobrado",
    "o cruzamento saiu na medida",
    "o chute passou perto",
    "o goleiro soltou a bola",
    "o time mudou a postura",
    "o resultado foi justo",
    "o estádio tem capacidade grande",
    "a festa da torcida foi linda",
    "o hino foi cantado",
    "o time entrou em campo",
    "o apito final já tocou",
    "o jogo foi adiado",
    "o gramado estava pesado",
    "o sol atrapalhou o goleiro",
    "o vento mudou o cruzamento",
    "a chuva castigou o campo",
    "o time está confiante",
    "o treino foi leve hoje",
    "o grupo está unido",
    "o próximo jogo é domingo",
    "o uniforme novo é bonito",
    "o clube anunciou o reforço",
    "o estádio recebeu público grande",
    "a venda de ingressos começou",
    "o time tem uma folga",
    "o elenco viajou de avião",
    "o técnico falou na coletiva",
    "o presidente do clube apareceu",
    "o patrocínio foi renovado",
    "o contrato termina em dezembro",
    "o jogador usou uma camisa à venda",
    "o clube abriu a loja",
    "o mascote animou a torcida",
    "o gramado foi cortado",
    "o ginásio estava lotado",
    "o time de futebol americano venceu",
    "o basquete foi decidido no fim",
    "o vôlei teve cinco sets",
    "o tênis teve três sets",
    "o automobilismo teve chuva",
    "o ciclismo foi cancelado",
    "o surf teve boas ondas",
    "o nadador bateu o recorde",
    "o atleta lesionou o joelho",
    "o atleta voltou ao tempo",
    "o campeão recebeu o troféu",
    "a seleção fez dois treinos",
    "o amistoso terminou empatado",
    "a convocação saiu hoje",
    "o estádio passou por reforma",
    "o clube deve dinheiro",
    "o estádio foi vendido",
    "o time perdeu em casa",
    "o time venceu fora",
    "o empate não ajudou",
    "o torcedor saiu cedo",
    "a fila deu a volta no quarteirão",
    "o maçarico chegou com pressa",
    "o sorvete derreteu",
    "o cachorro latiu a noite toda",
    "o café está amargo",
    "a pessoa chegou atrasada",
    "o ônibus demorou",
    "o pão saiu quentinho",
    "a música ficou na cabeça",
    "o filme foi longo",
    "a série termina hoje",
    "o livro está emprestado",
    "a aula foi curta",
    "o computador reiniciou",
    "a internet caiu de novo",
    "o telefone tocou",
    "a mensagem chegou",
    "o e-mail foi enviado",
    "a reunião foi tranquila",
    "o relatório está pronto",
    "a planilha está aberta",
    "o projeto ficou parado",
    "a equipe entregou tudo",
    "o cliente aprovou",
    "o preço subiu",
    "a chuva parou",
    "o céu está limpo",
    "a tarde foi tranquila",
    "a noite foi fria",
    "o chão está molhado",
    "a janela está aberta",
    "o cachorro está dormindo",
    "a comida está pronta",
    "o jantar foi leve",
    "a sobremesa ficou boa",
    "o suco está gelado",
    "a fruta está madura",
    "o mercado abriu",
    "a padaria fechou",
    "o ônibus passou",
    "a praça está cheia",
    "o museu está aberto",
    "a exposição termina domingo",
    "o cinema estreia hoje",
    "a peça teve aplausos",
    "o show começou tarde",
    "a banda tocou bem",
    "o palco é grande",
    "a luz apagou",
    "o som falhou",
    "o vídeo ficou parado",
    "a foto saiu tremida",
    "o celular descarregou",
    "a bateria acabou",
    "o carregador está ligado",
    "o carro não pega",
    "a estrada está livre",
    "o trânsito está pesado",
    "a viagem foi longa",
    "o hotel é simples",
    "a praia estava cheia",
    "o mar está calmo",
    "a areia está quente",
    "o guarda-sol voou",
    "a cidade é grande",
    "o bairro é tranquilo",
    "a casa está vazia",
    "o quarto está organizado",
    "a cozinha ficou limpa",
    "o banho está pronto",
]


# --------------------------------------------------------------------------- #
# Arquivos e processos
# --------------------------------------------------------------------------- #
def piper_bin() -> Path:
    p = RAW / "piper" / "piper" / "piper"
    if not p.exists():
        raise SystemExit(f"binario piper nao encontrado em {p}; rode download.py --etapa piper")
    return p


def piper_modelo(voz: str) -> tuple[Path, Path]:
    base = RAW / "piper" / "vozes" / voz
    modelos = sorted(base.rglob(f"pt_BR-{voz}-*.onnx"))
    if not modelos:
        raise SystemExit(f"modelo piper de {voz} nao encontrado em {base}")
    return modelos[0], modelos[0].with_suffix(".onnx.json")


def ler_audio(p: Path | str) -> tuple[np.ndarray, int]:
    import soundfile as sf

    x, sr = sf.read(str(p), dtype="float32", always_2d=True)
    return x.mean(axis=1), int(sr)


def salvar_wav16(p: Path | str, x: np.ndarray) -> None:
    import soundfile as sf

    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    x = np.asarray(x, dtype=np.float32)
    if x.ndim > 1:
        x = x.mean(axis=1)
    sf.write(str(p), np.clip(x, -1.0, 1.0), SR, subtype="PCM_16")


def resample(x: np.ndarray, sr_in: int, sr_out: int = SR) -> np.ndarray:
    if sr_in == sr_out:
        return x.astype(np.float32, copy=False)
    from math import gcd

    from scipy.signal import resample_poly

    g = gcd(int(sr_in), int(sr_out))
    return resample_poly(x.astype(np.float32), sr_out // g, sr_in // g).astype(np.float32)


def db_rms(x: np.ndarray) -> float:
    if len(x) == 0:
        return -120.0
    r = float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))
    return 20.0 * np.log10(max(r, 1e-9))


def normalizar(x: np.ndarray, pico: float = 0.95) -> np.ndarray:
    m = float(np.max(np.abs(x))) if len(x) else 0.0
    if m < 1e-9:
        return x
    return (x / m * pico).astype(np.float32)


# --------------------------------------------------------------------------- #
# ffmpeg: pitch e time-stretch (rubberband)
# --------------------------------------------------------------------------- #
def _ffmpeg_apply(x: np.ndarray, filtro: str) -> np.ndarray:
    """Aplica um filtro de audio via ffmpeg (wav temporario)."""
    with tempfile.TemporaryDirectory(dir=str(ROOT / "work")) as td:
        entrada = Path(td) / "in.wav"
        saida = Path(td) / "out.wav"
        salvar_wav16(entrada, x)
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(entrada), "-filter:a", filtro, "-ar", str(SR), "-ac", "1", str(saida),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not saida.exists():
            raise RuntimeError(f"ffmpeg falhou: {r.stderr[-500:]}")
        y, _ = ler_audio(saida)
        return y


def esticar(x: np.ndarray, fator: float) -> np.ndarray:
    """Time-stretch preservando o pitch (fator > 1 = mais longo)."""
    if abs(fator - 1.0) < 0.02:
        return x
    return _ffmpeg_apply(x, f"rubberband=tempo={1.0/fator:.4f}:pitch=1")


def mudar_pitch(x: np.ndarray, semitons: float) -> np.ndarray:
    """Muda o pitch preservando a duracao."""
    if abs(semitons) < 0.05:
        return x
    razao = 2.0 ** (semitons / 12.0)
    return _ffmpeg_apply(x, f"rubberband=pitch={razao:.4f}:tempo=1")


def comprimir(x: np.ndarray, forca: float = 3.0) -> np.ndarray:
    """Clipping suave (tanh) + normalizacao: aproxima o grito comprimido."""
    if forca <= 0.01:
        return x
    y = np.tanh(forca * x) / np.tanh(forca)
    return normalizar(y, 0.92)


def ganho(x: np.ndarray, db: float) -> np.ndarray:
    return x * (10.0 ** (db / 20.0))


# --------------------------------------------------------------------------- #
# Vogal: deteccao e alongamento
# --------------------------------------------------------------------------- #
def _envelope(x: np.ndarray, janela: int = 400, passo: int = 160) -> np.ndarray:
    if len(x) < janela:
        return np.zeros(0, dtype=np.float32)
    n = 1 + (len(x) - janela) // passo
    idx = np.arange(n)[:, None] * passo + np.arange(janela)[None, :]
    return np.sqrt(np.mean(np.square(x[idx].astype(np.float64)), axis=1)).astype(np.float32)


def _periodicidade(x: np.ndarray, janela: int = 640, passo: int = 160,
                   fmin: float = 70.0, fmax: float = 500.0) -> np.ndarray:
    """Autocorrelacao normalizada por frame: 1 = muito periodico (vogal)."""
    if len(x) < janela + passo:
        return np.zeros(0, dtype=np.float32)
    n = 1 + (len(x) - janela) // passo
    lo = max(2, int(SR / fmax))
    hi = min(janela - 1, int(SR / fmin))
    saida = np.zeros(n, dtype=np.float32)
    for i in range(n):
        f = x[i * passo : i * passo + janela].astype(np.float64)
        f = f - f.mean()
        e = np.dot(f, f)
        if e < 1e-8:
            continue
        ac = np.correlate(f, f, mode="full")[janela - 1 :]
        ac = ac / ac[0]
        trecho = ac[lo:hi]
        if len(trecho):
            saida[i] = float(trecho.max())
    return saida


def esticar_vogal(x: np.ndarray, fator: float) -> np.ndarray:
    """Alonga a vogal mais longa (regiao vozeada) sem mexer nas consoantes."""
    if fator <= 1.05 or len(x) < SR // 8:
        return x
    env = _envelope(x)
    per = _periodicidade(x)
    n = min(len(env), len(per))
    if n < 4:
        return esticar(x, fator)
    env, per = env[:n], per[:n]
    limiar_env = max(float(env.max()) * 0.15, 1e-4)
    vozeado = (per > 0.30) & (env > limiar_env)
    melhor = (0, 0, 0)
    i = 0
    while i < n:
        if not vozeado[i]:
            i += 1
            continue
        j = i
        while j < n and vozeado[j]:
            j += 1
        if j - i > melhor[0]:
            melhor = (j - i, i, j)
        i = j
    _, ini, fim = melhor
    if fim - ini < 4:  # menos de 40 ms de vogal: alonga o clip inteiro
        return esticar(x, fator)
    a = ini * 160
    b = min(len(x), fim * 160 + 400)
    pre, vogal, pos = x[:a], x[a:b], x[b:]
    if len(vogal) < SR // 20:
        return esticar(x, fator)
    return np.concatenate([pre, esticar(vogal, min(fator, 6.0)), pos]).astype(np.float32)


# --------------------------------------------------------------------------- #
# RIR e mistura
# --------------------------------------------------------------------------- #
_RIRS: list[np.ndarray] | None = None


def rirs() -> list[np.ndarray]:
    global _RIRS
    if _RIRS is None:
        arqs = sorted((RAW / "rir").glob("*.wav"))
        _RIRS = []
        for a in arqs:
            try:
                x, _ = ler_audio(a)
            except Exception:  # noqa: BLE001
                continue
            if len(x) > 320:
                _RIRS.append(x / (np.max(np.abs(x)) + 1e-9))
        if not _RIRS:
            raise SystemExit("nenhuma RIR em raw/rir; rode download.py --etapa rir")
    return _RIRS


def aplicar_rir(x: np.ndarray, rng: random.Random, molhado: float = 0.35) -> np.ndarray:
    from scipy.signal import fftconvolve

    rir = rirs()[rng.randrange(len(rirs()))]
    seco = x
    molhado_sinal = fftconvolve(x, rir)[: len(x)].astype(np.float32)
    if len(molhado_sinal) < len(seco):
        molhado_sinal = np.pad(molhado_sinal, (0, len(seco) - len(molhado_sinal)))
    molhado_sinal = normalizar(molhado_sinal, float(np.max(np.abs(seco)) + 1e-9))
    return ((1 - molhado) * seco + molhado * molhado_sinal).astype(np.float32)


def misturar_snr(x: np.ndarray, ruido: np.ndarray, snr_db: float, rng: random.Random) -> np.ndarray:
    """Mistura ruido em SNR alvo, usando o RMS da parte ativa de x."""
    if len(ruido) < len(x):
        ruido = np.tile(ruido, int(np.ceil(len(x) / max(len(ruido), 1))))
    desloc = rng.randrange(max(1, len(ruido) - len(x))) if len(ruido) > len(x) else 0
    r = ruido[desloc : desloc + len(x)].astype(np.float32)
    alvo = db_rms(x) - snr_db
    atual = db_rms(r)
    r = r * (10.0 ** ((alvo - atual) / 20.0))
    y = x + r
    return normalizar(y, 0.95)


def pool(categoria: str, minimo: int = 1) -> list[Path]:
    """Lista os wavs de uma categoria de audio longo (game, music, noise, speech)."""
    arqs = sorted((RAW / categoria / "wav").glob("*.wav"))
    if not arqs:
        arqs = sorted((RAW / categoria).glob("*.wav"))
    if len(arqs) < minimo:
        raise SystemExit(f"poucos arquivos em raw/{categoria}: {len(arqs)}")
    return arqs


def trecho(arquivo: Path, segundos: float, rng: random.Random,
           max_ini: float | None = None, cache: dict | None = None) -> np.ndarray:
    """Le um trecho aleatorio de um wav longo (usa soundfile seek para nao ler tudo)."""
    import soundfile as sf

    info = sf.info(str(arquivo))
    dur = info.frames / info.samplerate
    usar = min(segundos, max(dur - 0.1, 0.1))
    limite = max_ini if max_ini is not None else max(0.0, dur - usar)
    ini = rng.uniform(0, limite) if limite > 0 else 0.0
    x, sr = sf.read(str(arquivo), start=int(ini * info.samplerate),
                    frames=int(usar * info.samplerate), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    return resample(x, sr) if sr != SR else x


# --------------------------------------------------------------------------- #
# TTS
# --------------------------------------------------------------------------- #
def piper_texto(texto: str, voz: str, length_scale: float, noise_scale: float,
                noise_w: float, speaker: int = 0) -> np.ndarray:
    """Sintetiza uma frase com o piper e devolve float32 16 kHz.

    Cada invocacao usa um diretorio temporario proprio: o piper nomeia os wavs
    pelo relogio e nao aceita nome de saida deterministico com --output_dir.
    """
    onnx, config = piper_modelo(voz)
    with tempfile.TemporaryDirectory(dir=str(ROOT / "work")) as td:
        cmd = [
            str(piper_bin()), "-m", str(onnx), "-c", str(config),
            "--length-scale", f"{length_scale:.2f}",
            "--noise-scale", f"{noise_scale:.2f}",
            "--noise-w", f"{noise_w:.2f}",
            "--speaker", str(speaker),
            "--output_dir", td,
        ]
        r = subprocess.run(cmd, input=texto + "\n", capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"piper falhou: {r.stderr[-800:]}")
        saidas = sorted(Path(td).glob("*.wav"))
        if not saidas:
            raise RuntimeError(f"piper nao gerou wav para {texto!r}")
        x, sr = ler_audio(saidas[-1])
    return resample(x, sr)


def edge_frase(texto: str, voz: str, rate: str = "+0%", volume: str = "+0%") -> np.ndarray:
    """edge-tts: mp3 -> float32 16 kHz."""
    import io

    import soundfile as sf

    with tempfile.TemporaryDirectory(dir=str(ROOT / "work")) as td:
        mp3 = Path(td) / "out.mp3"
        cmd = [
            str(AQUI / ".venv" / "bin" / "edge-tts"),
            "--voice", voz, "--text", texto, "--rate", rate, "--volume", volume,
            "--write-media", str(mp3),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0 or not mp3.exists():
            raise RuntimeError(f"edge-tts falhou ({voz}): {r.stderr[-500:]}")
        x, sr = sf.read(io.BytesIO(mp3.read_bytes()), dtype="float32", always_2d=True)
        x = x.mean(axis=1)
        return resample(x, sr)


# --------------------------------------------------------------------------- #
# Janela de 2 s
# --------------------------------------------------------------------------- #
def janela_com_fundo(clip: np.ndarray, fundo: np.ndarray | None, rng: random.Random,
                     n: int = JANELA) -> np.ndarray:
    """Posiciona o clip no FIM de uma janela de n amostras, com fundo antes dele."""
    clip = clip[:n]
    if fundo is None or len(fundo) == 0:
        fundo = rng.gauss(0, 1e-3) * np.ones(n, dtype=np.float32)
    if len(fundo) < n:
        fundo = np.tile(fundo, int(np.ceil(n / len(fundo))))
    desloc = rng.randrange(max(1, len(fundo) - n)) if len(fundo) > n else 0
    janela = fundo[desloc : desloc + n].astype(np.float32).copy()
    janela[-len(clip) :] = clip
    return normalizar(janela, 0.95)


def fundo_aleatorio(rng: random.Random, escolhas: list[tuple[str, float]], segundos: float = 3.0) -> np.ndarray:
    """Sorteia um fundo de uma lista (categoria, peso) e devolve um trecho.

    Categorias ainda nao baixadas sao ignoradas (o fundo cai nas disponiveis).
    """
    disponiveis = []
    for categoria, peso in escolhas:
        pasta = RAW / categoria / "wav"
        if pasta.exists() and any(pasta.glob("*.wav")):
            disponiveis.append((categoria, peso))
    if not disponiveis:
        raise SystemExit("nenhuma categoria de fundo disponivel (game/noise/music)")
    categorias = [c for c, _ in disponiveis]
    pesos = [p for _, p in disponiveis]
    categoria = rng.choices(categorias, weights=pesos, k=1)[0]
    arquivos = pool(categoria)
    return trecho(arquivos[rng.randrange(len(arquivos))], segundos, rng)


def semente(prefixo: str, i: int) -> random.Random:
    return random.Random(f"{prefixo}:{i}")


def salvar_json(p: Path, obj: dict | list) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")


def contar_wavs(d: Path) -> int:
    return len(list(d.glob("*.wav")))
