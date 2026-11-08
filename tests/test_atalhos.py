import subprocess
from types import SimpleNamespace

import pytest

from ronaldo import agent, atalhos
from ronaldo.atalhos import casar, encaminhar, executar_comando


MUSICA = {"palavras": ["musica"], "comando": ["/mock/tocador", "--tocar"], "nome": "musica"}
AGENTE = {"palavras": ["agente"], "comando": ["/mock/agente", "ask", "{text}"], "nome": "agente"}


def _proc(rc=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------- casar


@pytest.mark.parametrize("texto", ["Ronaldo, musica!", "musica", "Música!", "Ronaldo, musica. Toca", "musica agora"])
def test_atalho_curto_casa_fala_curta(texto):
    assert casar(texto, [MUSICA])[0] is MUSICA


@pytest.mark.parametrize("texto", ["musica do album novo que saiu ontem", "a musica", "musical", "Ronaldo, musica do album novo que saiu"])
def test_atalho_curto_nao_pega_frase_longa_nem_palavra_parecida(texto):
    assert casar(texto, [MUSICA]) is None


def test_max_palavras_configuravel():
    assert casar("musica a b c d e f", [{**MUSICA, "max_palavras": 10}]) is not None


def test_atalho_com_texto_nao_tem_limite_e_devolve_o_resto():
    texto = "agente, toca a música mais longa que existir agora"
    atalho, resto = casar(texto, [AGENTE])
    assert atalho is AGENTE and resto == "toca a música mais longa que existir agora"


def test_atalho_com_texto_sem_resto_casa_vazio():
    assert casar("agente", [AGENTE]) == (AGENTE, "")


def test_primeiro_de_dois_atalhos_casa():
    segundo = {"palavras": ["agente"], "comando": ["/mock/agente"], "nome": "agente"}
    assert casar("Agente, toca", [MUSICA, segundo])[0] is segundo


def test_qualquer_posicao_continua_so_em_fala_curta():
    som = {"palavras": ["som", "sons"], "comando": ["/mock/tocador"], "nome": "som", "qualquer_posicao": True}
    for texto in ["Do som porra.", "som porra", "que som!", "Ronaldo, som, porra!"]:
        assert casar(texto, [som])[0] is som
    for texto in ["o som do time adversário no último minuto", "Ronaldo, que horas são"]:
        assert casar(texto, [som]) is None


def test_sem_qualquer_posicao_continua_so_no_comeco():
    assert casar("do som porra", [{"palavras": ["som"], "comando": ["/mock/tocador"]}]) is None


# ---------------------------------------------------------------- executar_comando


def test_executar_comando_expande_til_e_nao_espera(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    vistos = []
    monkeypatch.setattr(atalhos.subprocess, "Popen", lambda argv, **kw: vistos.append((argv, kw)) or SimpleNamespace(pid=1))
    status, msg = executar_comando(["/usr/bin/afplay", "-v", "0.6", "~/Music/favorita.wav"], path="/usr/bin:/bin", nome="musica")
    assert status == "entregue" and "musica" in msg
    argv, kw = vistos[0]
    assert argv == ["/usr/bin/afplay", "-v", "0.6", f"{tmp_path}/Music/favorita.wav"]
    assert kw.get("start_new_session") is True and kw["stdin"] == subprocess.DEVNULL


def test_executar_comando_falha_vira_falhou(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("tocador")

    monkeypatch.setattr(atalhos.subprocess, "Popen", boom)
    status, msg = executar_comando(["/nao/existe"], path="/bin", nome="musica")
    assert status == "falhou" and "tocador" in msg


# ---------------------------------------------------------------- encaminhar


def _run(monkeypatch, resultado):
    visto = {}

    def fake(argv, **kw):
        visto["argv"] = argv
        visto["kw"] = kw
        if isinstance(resultado, Exception):
            raise resultado
        return resultado

    monkeypatch.setattr(atalhos.subprocess, "run", fake)
    return visto


def test_encaminhar_zero_usa_a_primeira_linha_do_stdout(monkeypatch):
    visto = _run(monkeypatch, _proc(0, "Entregue ao canal.\nmais nada"))
    assert encaminhar(AGENTE["comando"], "  toca a música  ", path="/mock", nome="agente") == ("entregue", "Entregue ao canal.")
    assert visto["argv"] == ["/mock/agente", "ask", "toca a música"]
    assert visto["kw"]["timeout"] == 15.0 and visto["kw"]["stdin"] == subprocess.DEVNULL


def test_encaminhar_zero_sem_stdout_usa_mensagem_padrao(monkeypatch):
    _run(monkeypatch, _proc(0, "\n  \n"))
    assert encaminhar(AGENTE["comando"], "toca", path="/mock", nome="agente") == ("entregue", "Entregue ao agente.")


def test_encaminhar_75_vira_sem_confirmacao(monkeypatch):
    _run(monkeypatch, _proc(75, "Enviado, sem confirmação\n"))
    assert encaminhar(AGENTE["comando"], "toca", path="/mock", nome="agente") == ("sem_confirmacao", "Enviado, sem confirmação")


def test_encaminhar_75_sem_stdout_usa_mensagem_padrao(monkeypatch):
    _run(monkeypatch, _proc(75, ""))
    assert encaminhar(AGENTE["comando"], "toca", path="/mock", nome="agente") == ("sem_confirmacao", "Enviado ao agente, sem confirmação")


def test_encaminhar_outro_codigo_usa_a_primeira_linha_do_stderr(monkeypatch):
    _run(monkeypatch, _proc(1, "stdout irrelevante", "falhou feio\nresto\n"))
    assert encaminhar(AGENTE["comando"], "toca", path="/mock", nome="agente") == ("falhou", "falhou feio")


def test_encaminhar_falha_sem_stderr_usa_stdout(monkeypatch):
    _run(monkeypatch, _proc(2, "detalhe do stdout"))
    assert encaminhar(AGENTE["comando"], "toca", path="/mock", nome="agente") == ("falhou", "detalhe do stdout")


def test_encaminhar_timeout_vira_sem_confirmacao(monkeypatch):
    _run(monkeypatch, subprocess.TimeoutExpired("agente", 15))
    assert encaminhar(AGENTE["comando"], "toca", path="/mock", nome="agente") == (
        "sem_confirmacao",
        "agente não respondeu em 15s; entrega incerta",
    )


def test_encaminhar_comando_inexistente_falha(monkeypatch):
    _run(monkeypatch, FileNotFoundError("agente"))
    status, msg = encaminhar(AGENTE["comando"], "toca", path="/mock", nome="agente")
    assert status == "falhou" and "não encontrado" in msg


def test_encaminhar_resto_vazio_falha_sem_rodar(monkeypatch):
    monkeypatch.setattr(atalhos.subprocess, "run", lambda *a, **k: pytest.fail("não devia rodar"))
    assert encaminhar(AGENTE["comando"], "  ", path="/mock", nome="agente") == ("falhou", "nada pra mandar ao agente")


def test_encaminhar_expande_til_sem_expandir_o_texto(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    visto = _run(monkeypatch, _proc(0, "ok"))
    encaminhar(["~/bin/agente", "ask", "{text}"], "~ não é caminho", path="/mock")
    assert visto["argv"] == [f"{tmp_path}/bin/agente", "ask", "~ não é caminho"]


# ---------------------------------------------------------------- agent e HUD


def test_agent_atalho_curto_hud_e_sem_fallback(monkeypatch):
    monkeypatch.setattr("ronaldo.atalhos.executar_comando", lambda *a, **k: ("entregue", "Tocou musica."))
    monkeypatch.setattr(agent.subprocess, "run", lambda *a, **k: pytest.fail("agente chamado"))
    shown = []
    monkeypatch.setattr("ronaldo.hud.show", lambda *a: shown.append(a))
    assert agent.run(["/mock/agente"], "musica", path="/mock", timeout=1, notify_reply=False, name="rota", hud=True, req_id=99, atalhos=[MUSICA])[0]
    assert shown[-1][2:4] == ("ok", 6) and shown[-1][-1] == 99

    monkeypatch.setattr("ronaldo.atalhos.executar_comando", lambda *a, **k: ("falhou", "nope"))
    assert not agent.run(["/mock/agente"], "musica", path="/mock", timeout=1, notify_reply=False, name="rota", hud=True, req_id=100, atalhos=[MUSICA])[0]
    assert shown[-1][2:4] == ("err", 12) and shown[-1][-1] == 100
    assert shown[-1][1] == "nope"


def test_agent_atalho_com_texto_espera_e_mostra_o_aviso(monkeypatch):
    visto = {}

    def fake(argv, **kw):
        visto["argv"] = argv
        return _proc(75, "Enviado, sem confirmação")

    monkeypatch.setattr("ronaldo.atalhos.subprocess.run", fake)
    shown = []
    monkeypatch.setattr("ronaldo.hud.show", lambda *a: shown.append(a))
    ok, msg = agent.run(["/mock/agente"], "agente, toca a música", path="/mock", timeout=1, notify_reply=False, name="rota", hud=True, req_id=101, atalhos=[AGENTE])
    assert ok and msg == "Enviado, sem confirmação"
    assert visto["argv"][-1] == "toca a música"
    assert shown[-1][2:4] == ("warn", 6) and shown[-1][-1] == 101


def test_agent_atalho_com_texto_timeout_mostra_aviso(monkeypatch):
    _run(monkeypatch, subprocess.TimeoutExpired("agente", 15))
    shown = []
    monkeypatch.setattr("ronaldo.hud.show", lambda *a: shown.append(a))
    ok, msg = agent.run(["/mock/agente"], "agente, toca a música", path="/mock", timeout=1, notify_reply=False, name="rota", hud=True, req_id=104, atalhos=[AGENTE])
    assert ok and msg == "agente não respondeu em 15s; entrega incerta"
    assert shown[-1][2:4] == ("warn", 6) and shown[-1][-1] == 104


def test_agent_atalho_com_texto_e_resto_vazio_falha(monkeypatch):
    monkeypatch.setattr("ronaldo.atalhos.subprocess.run", lambda *a, **k: pytest.fail("não devia rodar"))
    shown = []
    monkeypatch.setattr("ronaldo.hud.show", lambda *a: shown.append(a))
    ok, msg = agent.run(["/mock/agente"], "agente", path="/mock", timeout=1, notify_reply=False, name="rota", hud=True, req_id=102, atalhos=[AGENTE])
    assert ok is False and "nada pra mandar" in msg
    assert shown[-1][2:4] == ("err", 12) and shown[-1][-1] == 102


def test_agent_atalho_sem_casar_cai_no_agente(monkeypatch):
    monkeypatch.setattr(agent.subprocess, "run", lambda *a, **k: _proc(0, "fallback"))
    shown = []
    monkeypatch.setattr("ronaldo.hud.show", lambda *a: shown.append(a))
    assert agent.run(["/mock/agente"], "outra coisa", path="/bin", timeout=1, notify_reply=False, name="rota", hud=False, atalhos=[MUSICA])[0]
    assert not shown


def test_agent_atalho_nao_chama_o_modo_voz_nem_o_envio(monkeypatch):
    from ronaldo import voz

    monkeypatch.setattr(voz, "ligado", lambda *a, **k: True)
    monkeypatch.setattr(agent, "_falar_com_voz", lambda *a, **k: pytest.fail("modo voz chamado"))
    monkeypatch.setattr(agent.subprocess, "run", lambda *a, **k: pytest.fail("envio chamado"))
    rodou = []
    monkeypatch.setattr("ronaldo.atalhos.executar_comando", lambda argv, **k: rodou.append(argv) or ("entregue", "Tocou musica."))
    shown = []
    monkeypatch.setattr("ronaldo.hud.show", lambda *a: shown.append(a))
    ok, msg = agent.run(["/mock/agente", "ask", "{text}"], "Ronaldo, musica!", path="/mock", timeout=1, notify_reply=False, name="rota", hud=True, req_id=7, atalhos=[MUSICA], voz=True)
    assert ok and rodou == [MUSICA["comando"]]
    assert shown[-1][2] == "ok"


def test_agent_atalho_com_excecao_inesperada_mostra_erro(monkeypatch):
    monkeypatch.setattr("ronaldo.atalhos.executar_comando", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("inesperado")))
    shown = []
    monkeypatch.setattr("ronaldo.hud.show", lambda *a: shown.append(a))
    assert agent.run(["/mock/agente"], "musica", path="/mock", timeout=1, notify_reply=False, name="rota", hud=True, req_id=103, atalhos=[MUSICA]) == (False, "inesperado")
    assert shown[-1][0].startswith("❌") and shown[-1][2] == "err"
