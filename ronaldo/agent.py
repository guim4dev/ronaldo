"""Hand a transcript to an external agent command and push its reply as a notification."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import uuid

log = logging.getLogger("ronaldo.agent")

PLACEHOLDER = "{text}"
NOTIFY_CHARS = 240


def login_path() -> str:
    """The user's login-shell PATH: launchd starts us with /usr/bin:/bin only."""
    shell = os.environ.get("SHELL", "/bin/zsh")
    try:
        out = subprocess.run([shell, "-lc", 'printf %s "$PATH"'], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        out = ""
    return out.strip() or os.environ.get("PATH", "/usr/bin:/bin")


def build_argv(template: list[str], text: str) -> tuple[list[str], str | None]:
    """Replace {text} in the argv; without a placeholder the text goes to stdin."""
    if any(PLACEHOLDER in a for a in template):
        return [a.replace(PLACEHOLDER, text) for a in template], None
    return list(template), text


def notify(message: str, title: str = "Ronaldo") -> None:
    # Pass values as argv so nothing in the agent's reply is interpreted as AppleScript.
    script = ["-e", "on run argv", "-e", "display notification (item 1 of argv) with title (item 2 of argv)", "-e", "end run"]
    subprocess.run(["osascript", *script, message, title], capture_output=True, timeout=10)


def summarize(output: str) -> str:
    text = " ".join(output.split())
    return text if len(text) <= NOTIFY_CHARS else text[: NOTIFY_CHARS - 1] + "…"


def _report(ok: bool, reply: str, *, notify_reply: bool, name: str, hud: bool, req_id: int | None) -> None:
    if hud:
        from . import hud as hud_module
        if ok:
            hud_module.show("✅ " + summarize(reply or "Entregue."), summarize(reply), "ok", 6, req_id)
        else:
            hud_module.show("❌ Não entregou", summarize(reply), "err", 12, req_id)
    if notify_reply or not ok:
        def send_notification() -> None:
            try:
                notify(summarize(reply) or "Feito.", title=f"Ronaldo · {name}")
            except (OSError, subprocess.SubprocessError):
                log.exception("[%s] falha ao enviar notificação", name)

        threading.Thread(target=send_notification, daemon=True).start()


def _comando_de_modo(text: str, *, hud: bool, req_id: int | None, name: str) -> tuple[bool, str] | None:
    """Liga/desliga o modo voz sem chamar o rei. None quando não é comando."""
    from . import voz as voz_module

    comando = voz_module.comando_modo(text)
    if comando is None:
        return None
    if comando == "ligar":
        voz_module.ligar()
        try:
            voz_module.falar_agora("Modo voz ligado.")
        except Exception:  # noqa: BLE001 - o modo já está ligado; a fala é acessório
            log.exception("[%s] falha ao falar confirmação do modo voz", name)
        if hud:
            from . import hud as hud_module
            hud_module.show("🔊 Modo voz ligado", "As respostas do rei vão ser faladas.", "ok", 6, req_id)
        return True, "Modo voz ligado."
    voz_module.desligar()
    if hud:
        from . import hud as hud_module
        hud_module.show("📝 Modo texto", "As respostas voltam só no app.", "info", 6, req_id)
    return True, "Modo texto."


def _falar_ao_rei(template: list[str], text: str, *, path: str, timeout: float, notify_reply: bool, name: str, hud: bool, req_id: int | None) -> tuple[bool, str]:
    """Envia a fala com --id/--json e põe a resposta do rei na fila do Falador."""
    from . import voz as voz_module

    oid = uuid.uuid4().hex
    corte = template[0]
    argv = [corte, "falar", "--id", oid, "--json", "--", text]
    env = {**os.environ, "PATH": path, "RONALDO_TEXT": text}
    limite = min(timeout, 60)
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=limite, env=env, cwd=os.path.expanduser("~"))
        try:
            dados = json.loads(r.stdout) if r.stdout.strip() else {}
        except ValueError:
            dados = {}
        if not isinstance(dados, dict):
            dados = {}
        ok = r.returncode == 0 and dados.get("ok") is True
        reino = dados.get("reino")
        if ok and not (isinstance(reino, str) and reino):
            ok = False
            reply = "O corte não devolveu o reino da fala."
        elif ok:
            voz_module.enfileirar(reino, oid)
            reply = f"Enviado ao rei ({reino})."
        else:
            erro = dados.get("erro") or dados.get("error")
            if isinstance(erro, dict):
                erro = erro.get("message")
            detalhe = erro or r.stderr.strip() or r.stdout.strip() or f"código {r.returncode}"
            reply = f"O corte falhou: {detalhe}"
    except FileNotFoundError:
        ok, reply = False, f"Comando não encontrado: {corte}"
    except subprocess.TimeoutExpired:
        ok, reply = False, f"O corte não respondeu em {limite:.0f}s"
    except OSError as exc:
        ok, reply = False, f"Falha ao chamar o corte: {exc}"
    log.info("[%s] voz: %s: %s", name, "ok" if ok else "falhou", reply)
    _report(ok, reply, notify_reply=notify_reply, name=name, hud=hud, req_id=req_id)
    return ok, reply


def run(template: list[str], text: str, *, path: str, timeout: float, notify_reply: bool, name: str, hud: bool = False, req_id: int | None = None, atalhos=None, voz: bool = False) -> tuple[bool, str]:
    """Run the agent command to completion (call from a worker thread)."""
    falar_resposta = False
    if voz:
        from . import voz as voz_module

        modo = _comando_de_modo(text, hud=hud, req_id=req_id, name=name)
        if modo is not None:
            log.info("[%s] comando de modo: %s", name, text)
            return modo
        falar_resposta = voz_module.ligado()
    if atalhos:
        from .atalhos import casar, entregar_terminal
        match = casar(text, atalhos)
        if match:
            shortcut, remainder = match
            shortcut_name = shortcut.get("nome") or shortcut["terminal"]
            try:
                status, message = entregar_terminal(shortcut["terminal"], remainder, path=path, timeout=10, nome=shortcut_name)
            except Exception as exc:
                status, message = "falhou", str(exc) or type(exc).__name__
                log.exception("[%s] exceção ao entregar atalho %s", name, shortcut_name)
            ok = status != "falhou"
            log.info("[%s] atalho %s → %s: %s %s", name, shortcut_name, shortcut["terminal"], status, message)
            if hud:
                from . import hud as hud_module
                kind = {"entregue": "ok", "sem_confirmacao": "warn", "falhou": "err"}[status]
                prefix = {"entregue": "✅ ", "sem_confirmacao": "⚠️ ", "falhou": "❌ "}[status]
                title = message if status != "falhou" else f"Não entregou ao {shortcut_name}"
                hud_module.show(prefix + title, summarize(remainder if ok else message), kind, 6 if ok else 12, req_id)
            return ok, message
    if falar_resposta:
        return _falar_ao_rei(template, text, path=path, timeout=timeout, notify_reply=notify_reply, name=name, hud=hud, req_id=req_id)
    argv, stdin = build_argv(template, text)
    env = {**os.environ, "PATH": path, "RONALDO_TEXT": text}
    log.info("[%s] enviando para %s", name, argv[0])
    try:
        r = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout, env=env, cwd=os.path.expanduser("~"))
        ok, output = r.returncode == 0, (r.stdout.strip() or r.stderr.strip())
        error_detail = r.stderr.strip() or r.stdout.strip()
        reply = output if ok else f"O agente falhou (código {r.returncode}): {output}"
    except FileNotFoundError:
        ok, output = False, ""
        error_detail = f"Comando não encontrado: {argv[0]}"
        reply = error_detail
    except subprocess.TimeoutExpired:
        ok, output = False, ""
        error_detail = f"O agente não respondeu em {timeout:.0f}s"
        reply = error_detail
    log.info("[%s] %s: %s", name, "ok" if ok else "falhou", reply)
    if hud:
        from . import hud as hud_module
        if ok:
            hud_module.show("✅ " + summarize(output or "Entregue."), summarize(text), "ok", 6, req_id)
        else:
            hud_module.show("❌ Não entregou", summarize(error_detail or reply), "err", 12, req_id)
    if notify_reply or not ok:  # failures always surface, even on silent routes
        def send_notification() -> None:
            try:
                notify(summarize(reply) or "Feito.", title=f"Ronaldo · {name}")
            except (OSError, subprocess.SubprocessError):
                log.exception("[%s] falha ao enviar notificação", name)

        threading.Thread(target=send_notification, daemon=True).start()
    return ok, reply


def dispatch(template: list[str], text: str, **kw) -> threading.Thread:
    """Fire and forget: the listener keeps listening while the agent works."""
    t = threading.Thread(target=run, args=(template, text), kwargs=kw, daemon=True)
    t.start()
    return t
