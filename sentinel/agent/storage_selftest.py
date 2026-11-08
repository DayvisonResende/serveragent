"""Autoteste da limpeza (etapa 9 do verificar.bat), pelo mesmo caminho do dashboard.

Cria arquivos de teste numa pasta própria dentro de %TEMP% (pasta autorizada por
padrão), roda uma análise só das pastas autorizadas (sem a visão do disco) e
exercita: plano → quarentena → restauração → exclusão definitiva com confirmação.
Os arquivos reais do usuário que a análise encontrar não são tocados: o plano
contém só os arquivos do teste. A pasta de teste é apagada no final.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from sentinel.agent.client import ApiError, LocalClient
from sentinel.agent.config import Settings
from sentinel.agent.selfcheck import Check

DAY = 86_400


def _write(path: Path, size: int, age_days: float, fill: bytes) -> None:
    path.write_bytes((fill * (size // len(fill) + 1))[:size])
    t = time.time() - age_days * DAY
    os.utime(path, (t, t))


def _wait_idle(http: LocalClient, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        status = http.request("GET", "/api/v1/storage/status")
        if not status["running"] or time.monotonic() > deadline:
            return status
        time.sleep(2)


def run(settings: Settings) -> list[Check]:
    checks: list[Check] = []
    http = LocalClient(settings, timeout=120)
    folder = Path(tempfile.gettempdir()) / f"sentinel-autoteste-{int(time.time())}"
    folder.mkdir(parents=True)
    old, dup_a, dup_b, db = folder / "velho.tmp", folder / "copia-a.bin", folder / "copia-b.bin", folder / "protegido.db"
    _write(old, 64 * 1024, 40, b"t")
    _write(dup_a, 1536 * 1024, 3, b"dup")
    _write(dup_b, 1536 * 1024, 1, b"dup")
    _write(db, 64 * 1024, 40, b"d")
    try:
        _run(http, checks, folder, old, dup_a, dup_b, db)
    except (ApiError, OSError) as exc:
        checks.append(Check("Autoteste da limpeza", False, f"{type(exc).__name__}: {exc}"))
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return checks


def _run(http: LocalClient, checks: list[Check], folder: Path, old: Path, dup_a: Path, dup_b: Path, db: Path) -> None:
    status = _wait_idle(http, 600)  # uma análise agendada pode estar em andamento
    if status["running"]:
        checks.append(Check("Análise de armazenamento", False, "outra análise não terminou em 10 min"))
        return
    if not any(str(folder).lower().startswith(a["path"].lower()) for a in status["authorized"]):
        checks.append(Check("Pasta de temporários autorizada", False,
                            f"{folder.parent} não está entre as pastas autorizadas; o autoteste precisa dela"))
        return

    started = time.monotonic()
    http.request("POST", "/api/v1/storage/analyze", {"full_disk": False})
    status = _wait_idle(http, 900)
    last = status["last"]
    ok = not status["running"] and last and last["status"] == "completed"
    s = (last or {}).get("summary", {})
    checks.append(Check("Análise de armazenamento (pastas autorizadas)", bool(ok),
                        f"{s.get('files', 0)} arquivos em {time.monotonic() - started:.0f} s; "
                        f"estimativa limpável: {s.get('recoverable_bytes', 0) / 1024**2:.0f} MB" if ok
                        else f"situação: {(last or {}).get('status')} {(last or {}).get('error') or ''}"))
    if not ok:
        return

    def mine(category: str) -> dict[str, dict[str, Any]]:
        rows = http.request("GET", f"/api/v1/storage/findings?category={category}&limit=5000")["findings"]
        return {Path(r["path"]).name: r for r in rows if Path(r["path"]).parent == folder}

    temp, dups = mine("temp"), mine("duplicate")
    found = ("velho.tmp" in temp and dups.get("copia-b.bin", {}).get("cleanable") is True
             and dups.get("copia-a.bin", {}).get("keep") is True)
    protected_ok = "protegido.db" not in temp and "protegido.db" not in dups
    checks.append(Check("Temporário antigo e duplicado encontrados", found,
                        "velho.tmp; copia-b.bin (a cópia mais antiga fica)" if found else f"temp={list(temp)} duplicados={list(dups)}"))
    checks.append(Check("Banco de dados nunca é sugerido (protegido)", protected_ok, "protegido.db ignorado" if protected_ok else "protegido.db apareceu"))
    if not found:
        return

    plan = http.request("POST", "/api/v1/storage/plans", {"finding_ids": [temp["velho.tmp"]["id"], dups["copia-b.bin"]["id"]],
                                                          "reason": "autoteste"})
    done = http.request("POST", "/api/v1/actions", {"operation": "cleanup_quarantine", "target_id": plan["id"], "reason": "autoteste"})
    moved = done["status"] == "completed" and not old.exists() and not dup_b.exists() and dup_a.exists()
    checks.append(Check("Arquivos movidos para a quarentena", moved, (done.get("result") or {}).get("message") or done["status"]))
    if not moved:
        return
    items = {Path(i["original_path"]).name: i for i in http.request("GET", "/api/v1/storage/quarantine")["items"]
             if i["report_id"] == plan["id"]}

    back = http.request("POST", "/api/v1/actions", {"operation": "quarantine_restore", "target_id": items["velho.tmp"]["id"]})
    restored = back["status"] == "completed" and old.exists()
    checks.append(Check("Restauração devolve o arquivo ao lugar", restored, str(old) if restored else back["status"]))

    name = f"limpeza #{plan['id']}"
    pending = http.request("POST", "/api/v1/actions", {"operation": "quarantine_delete", "target_id": plan["id"]})
    try:
        http.request("POST", f"/api/v1/approvals/{pending['id']}/approve", {"confirmation": "errado"})
        refused = False
    except ApiError as exc:
        refused = exc.status == 409
    deleted = http.request("POST", f"/api/v1/approvals/{pending['id']}/approve", {"confirmation": name})
    gone = deleted["status"] == "completed" and not Path(items["copia-b.bin"]["stored_path"]).exists()
    checks.append(Check("Exclusão definitiva exige digitar a confirmação", pending["status"] == "pending" and refused and gone,
                        f"sem confirmação: recusada; com '{name}': {(deleted.get('result') or {}).get('message') or deleted['status']}"))

    ops = {a["operation"] for a in http.request("GET", "/api/v1/audit?limit=200")["entries"]}
    wanted = {"storage.cleanup", "storage.restore", "storage.quarantine_delete"}
    checks.append(Check("Limpeza registrada na auditoria", wanted <= ops, ", ".join(sorted(wanted & ops)) or "nada registrado"))
