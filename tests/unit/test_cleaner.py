"""Análise de armazenamento, planos de limpeza e quarentena (PRD 8, 23.3)."""

import asyncio
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel.agent.config import Settings
from sentinel.core.event_bus import EventBus
from sentinel.core.resource_manager import PressureLevel
from sentinel.database.database import Database
from sentinel.database.migrations import apply_migrations
from sentinel.modules.cleaner import scope
from sentinel.modules.cleaner.analyzer import AnalysisCancelled, Options, Throttle, analyze
from sentinel.modules.cleaner.module import CleanerModule, StorageError
from sentinel.modules.security.actions import ActionService
from sentinel.modules.security.operations import ActionError

DAY = 86_400
MB = 1024**2


def write(path: Path, size: int = 10, age_days: float = 0, fill: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((fill * (size // len(fill) + 1))[:size])
    t = time.time() - age_days * DAY
    os.utime(path, (t, t))
    return path


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """Pasta 'temp' e 'downloads' autorizadas, uma pasta protegida e uma fora do escopo."""
    temp, downloads, outside = tmp_path / "temp", tmp_path / "downloads", tmp_path / "pessoal"
    monkeypatch.setattr(scope, "temp_dirs", lambda: [scope.norm(temp)])
    write(temp / "velho.tmp", 2000, age_days=30)
    write(temp / "novo.tmp", 2000, age_days=1)  # jovem demais: fica
    write(downloads / "app.log", 500, age_days=60)
    write(downloads / "a" / "filme.mkv", 3 * MB, age_days=10, fill=b"abc")
    write(downloads / "b" / "filme (1).mkv", 3 * MB, age_days=2, fill=b"abc")  # duplicado mais novo
    write(downloads / "c" / "outro.mkv", 3 * MB, age_days=2, fill=b"abd")  # mesmo tamanho, conteúdo diferente
    write(downloads / "dados.db", 3 * MB, age_days=90, fill=b"z")  # banco de dados: protegido
    write(downloads / "servidor" / "mundo.dat", 3 * MB, age_days=90, fill=b"abc")  # pasta de servidor
    write(outside / "grande.iso", 6 * MB)
    return SimpleNamespace(root=tmp_path, temp=temp, downloads=downloads, outside=outside)


def options(**kw):
    base = dict(large_bytes=5 * MB, temp_age_seconds=7 * DAY, log_age_seconds=30 * DAY,
                duplicate_min_bytes=1 * MB, max_hash_bytes=1024 * MB)
    return Options(**{**base, **kw})


def protection(tree):
    return scope.build_protection(tree.root / "projeto", tree.root / "projeto" / "data", [str(tree.downloads / "servidor")])


def test_analysis_categorizes_only_inside_authorized_and_respects_protection(tree):
    result = analyze([str(tree.temp), str(tree.downloads)], protection(tree), options(disk_roots=(str(tree.root),)))
    by = {(f.category, Path(f.path).name): f for f in result.findings}
    assert ("temp", "velho.tmp") in by and ("temp", "novo.tmp") not in by
    assert ("old_log", "app.log") in by
    dup = [f for f in result.findings if f.category == "duplicate"]
    assert sorted((Path(f.path).name, f.keep, f.cleanable) for f in dup) == [("filme (1).mkv", False, True), ("filme.mkv", True, False)]
    assert not any(Path(f.path).name in ("outro.mkv", "dados.db", "mundo.dat") and f.cleanable for f in result.findings)
    big = by[("large", "grande.iso")]
    assert not big.cleanable and big.note == "fora das pastas autorizadas"  # visão do disco: só informa
    s = result.summary
    assert s["recoverable_bytes"] == 2000 + 500 + 3 * MB
    assert any(d["path"].endswith("downloads") for d in s["top_dirs"])


def test_duplicate_reading_respects_budget(tree):
    result = analyze([str(tree.downloads)], protection(tree), options(max_hash_bytes=1 * MB))
    assert not [f for f in result.findings if f.category == "duplicate"]
    assert any("limite de leitura" in w for w in result.summary["warnings"])


@pytest.mark.skipif(os.name == "nt", reason="links simbólicos exigem privilégio no Windows")
def test_links_are_never_followed(tree):
    (tree.downloads / "atalho").symlink_to(tree.outside, target_is_directory=True)
    result = analyze([str(tree.downloads)], protection(tree), options(large_bytes=1))
    assert not any("pessoal" in f.path or "atalho" in f.path for f in result.findings)


def test_analysis_pauses_under_pressure_and_can_be_cancelled(tree):
    pressure = {"on": True}
    throttle = Throttle(should_pause=lambda: pressure["on"], every=1)
    throttle.cancel.set()  # cancelado enquanto pausado: sai sem terminar
    with pytest.raises(AnalysisCancelled):
        analyze([str(tree.downloads)], protection(tree), options(), throttle)


def test_authorizing_broad_or_protected_folders_is_refused(tree):
    prot = protection(tree)
    assert "disco inteiro" in scope.check_authorizable(os.path.abspath(os.sep), prot)
    assert "pasta pessoal" in scope.check_authorizable(str(Path.home()), prot)
    assert "protegida" in scope.check_authorizable(str(tree.downloads / "servidor"), prot)
    (tree.root / "projeto" / "data").mkdir(parents=True)
    assert "Sentinel" in scope.check_authorizable(str(tree.root / "projeto" / "data"), prot)
    assert scope.check_authorizable(str(tree.downloads), prot) is None  # contém um servidor: protegido arquivo a arquivo
    assert scope.check_authorizable(str(tree.temp), prot) is None


# ------------------------------------------------------------------ módulo + aprovações


def make_settings(tmp_path, **storage):
    return Settings(paths={"data_dir": tmp_path / "projeto" / "data"},
                    storage={"full_disk_view": False, "large_file_mb": 10, **storage})


def run_module(tmp_path, tree, scenario):
    async def runner():
        settings = make_settings(tmp_path)
        db = Database(tmp_path / "s.db")
        await db.open()
        await apply_migrations(db)
        bus = EventBus()
        actions = ActionService(db, bus, {}, 1800)

        class Scheduler:
            def add_job(self, *a, **k):
                pass

            async def remove_job(self, name):
                pass

        servers = SimpleNamespace(records=lambda: [SimpleNamespace(working_directory=str(tree.downloads / "servidor"),
                                                                   executable=None, log_path=None)])
        ctx = SimpleNamespace(settings=settings, database=db, event_bus=bus, scheduler=Scheduler(),
                              resources=SimpleNamespace(level=PressureLevel.NORMAL))
        module = CleanerModule(servers, SimpleNamespace(actions=actions))  # type: ignore[arg-type]
        await module.start(ctx)  # type: ignore[arg-type]
        await module.set_authorized([str(tree.temp), str(tree.downloads)])
        try:
            return await scenario(module, actions, db)
        finally:
            await db.close()

    return asyncio.run(runner())


async def analyzed(module):
    await module.start_analysis("teste")
    await module._task
    return {(f["category"], Path(f["path"]).name): f for f in (await module.findings(None))["findings"]}


def test_cleanup_moves_to_quarantine_restore_and_delete(tmp_path, tree):
    async def scenario(module, actions, db):
        found = await analyzed(module)
        plan = await module.create_plan("usuario", [found[("temp", "velho.tmp")]["id"], found[("duplicate", "filme (1).mkv")]["id"]])
        done = await actions.request("cleanup_quarantine", plan["id"], {}, "usuario", "teste", approval="user")
        quarantined = await module._repo.quarantine()
        stored_ok = all(Path(i["stored_path"]).exists() and len(i["sha256"]) == 64 for i in quarantined)
        again = None
        try:
            await actions.request("cleanup_quarantine", plan["id"], {}, "usuario", "de novo", approval="user")
        except ActionError as exc:
            again = str(exc)
        restore_id = next(i["id"] for i in quarantined if i["original_path"].endswith("velho.tmp"))
        restored = await actions.request("quarantine_restore", restore_id, {}, "usuario", "voltar", approval="user")
        pending = await actions.request("quarantine_delete", plan["id"], {}, "usuario", "esvaziar", approval="user")
        with pytest.raises(ActionError):
            await actions.approve(pending["id"], "usuario", confirmation="errado")
        deleted = await actions.approve(pending["id"], "usuario", confirmation=f"limpeza #{plan['id']}")
        report = await module.report(plan["id"])
        return done, stored_ok, again, restored, pending, deleted, report, await module._repo.quarantine(None)

    done, stored_ok, again, restored, pending, deleted, report, all_items = run_module(tmp_path, tree, scenario)
    assert done["status"] == "completed" and "2 de 2" in done["result"]["message"]
    assert not (tree.downloads / "b" / "filme (1).mkv").exists() and (tree.downloads / "a" / "filme.mkv").exists()
    assert stored_ok
    assert "já foi executada" in again or "não está mais aguardando" in again  # plano é de uso único
    assert restored["status"] == "completed" and (tree.temp / "velho.tmp").exists()
    assert pending["status"] == "pending" and pending["requires_confirmation"]  # exclusão definitiva: nível 3
    assert deleted["status"] == "completed"
    statuses = sorted(i["status"] for i in all_items)
    assert statuses == ["deleted", "restored"] and report["files_moved"] == 2 and report["files_deleted"] == 1
    assert not any(Path(i["stored_path"]).exists() for i in all_items if i["status"] == "deleted")


def test_changed_or_protected_files_are_skipped_at_execution(tmp_path, tree):
    async def scenario(module, actions, db):
        found = await analyzed(module)
        plan = await module.create_plan("usuario", category="old_log")
        write(tree.downloads / "app.log", 900, age_days=60)  # mudou depois da análise
        result = await actions.request("cleanup_quarantine", plan["id"], {}, "usuario", "x", approval="user")
        blocked = None
        try:
            await module.create_plan("usuario", [found[("duplicate", "filme.mkv")]["id"]])  # a cópia mantida
        except StorageError as exc:
            blocked = str(exc)
        return result, await module.report(plan["id"]), blocked

    result, report, blocked = run_module(tmp_path, tree, scenario)
    assert result["status"] == "failed" and (tree.downloads / "app.log").exists()
    assert report["details"]["items"][0]["result"] == "mudou desde a análise"
    assert "não podem ser limpos" in blocked


def test_ai_request_waits_for_approval_and_quarantine_limit(tmp_path, tree):
    async def scenario(module, actions, db):
        await analyzed(module)
        plan = await module.create_plan("ia:assistente", category="duplicate")
        pending = await actions.request("cleanup_quarantine", plan["id"], {}, "ia:assistente", "IA sugeriu", approval="required")
        still_there = (tree.downloads / "b" / "filme (1).mkv").exists()
        full = module._repo.quarantine_usage

        async def almost_full():
            return {**(await full()), "bytes": int(5 * 1024**3 - MB)}  # falta 1 MB; o plano tem 3 MB

        module._repo.quarantine_usage = almost_full
        with pytest.raises(ActionError, match="limite"):
            await actions.approve(pending["id"], "usuario")
        return pending, still_there

    pending, still_there = run_module(tmp_path, tree, scenario)
    assert pending["status"] == "pending" and still_there


def test_retention_deletes_only_expired_items(tmp_path, tree):
    async def scenario(module, actions, db):
        found = await analyzed(module)
        plan = await module.create_plan("usuario", [found[("temp", "velho.tmp")]["id"]])
        await actions.request("cleanup_quarantine", plan["id"], {}, "usuario", "x", approval="user")
        none_yet = await module.apply_retention()
        await db.execute("UPDATE quarantine_items SET quarantined_at = '2000-01-01T00:00:00+00:00'")
        purged = await module.apply_retention()
        return none_yet, purged, await module._repo.quarantine(None)

    none_yet, purged, items = run_module(tmp_path, tree, scenario)
    assert none_yet == 0 and purged == 1 and items[0]["status"] == "deleted" and items[0]["resolved_by"] == "politica-retencao"


def test_only_one_analysis_at_a_time(tmp_path, tree):
    async def scenario(module, actions, db):
        await module.start_analysis("teste")
        with pytest.raises(StorageError, match="em andamento"):
            await module.start_analysis("teste")
        await module._task
        return (await module._repo.latest_analysis())["status"]

    assert run_module(tmp_path, tree, scenario) == "completed"
