"""Armazenamento pela API: o mesmo caminho do dashboard (PRD 8.4, 15.1)."""

import time
from pathlib import Path
from types import SimpleNamespace

from sentinel.core.event_bus import EventBus
from sentinel.core.resource_manager import PressureLevel
from sentinel.modules.cleaner.module import CleanerModule
from sentinel.modules.security.actions import ActionService
from tests.integration.test_api import ORIGIN, api  # noqa: F401  (fixture)
from tests.unit.test_cleaner import make_settings, tree  # noqa: F401  (fixture)


def attach(api, tree, tmp_path):  # noqa: F811
    actions = ActionService(api.db, EventBus(), {}, 1800)

    class Scheduler:
        def add_job(self, *a, **k):
            pass

        async def remove_job(self, name):
            pass

    ctx = SimpleNamespace(settings=make_settings(tmp_path), database=api.db, event_bus=EventBus(), scheduler=Scheduler(),
                          resources=SimpleNamespace(level=PressureLevel.NORMAL))
    module = CleanerModule(SimpleNamespace(records=lambda: []), SimpleNamespace(actions=actions))  # type: ignore[arg-type]
    object.__setattr__(api.deps, "storage", module)  # ApiDeps é imutável
    object.__setattr__(api.deps, "security", SimpleNamespace(actions=actions))
    return module, ctx


def test_storage_flow_through_api(api, tree, tmp_path):  # noqa: F811
    module, ctx = attach(api, tree, tmp_path)
    loop_run = api.loop.run_until_complete
    loop_run(module.start(ctx))  # type: ignore[arg-type]
    with api.client as c:  # laço persistente, como no agente (a análise roda em segundo plano)
        api.login()
        assert c.put("/api/v1/storage/authorized", json={"folders": ["/"]}, headers=ORIGIN).status_code == 409
        r = c.put("/api/v1/storage/authorized", json={"folders": [str(tree.temp), str(tree.downloads)]}, headers=ORIGIN)
        assert r.status_code == 200

        assert c.post("/api/v1/storage/analyze", json={"full_disk": False}, headers=ORIGIN).status_code == 202
        deadline = time.time() + 10
        while (status := c.get("/api/v1/storage/status").json())["running"] and time.time() < deadline:
            time.sleep(0.05)  # o dashboard faz o mesmo: consulta o andamento
        assert status["last_completed"], status["last"]
        assert status["last_completed"]["summary"]["recoverable_bytes"] > 0 and not status["running"]

        temp = c.get("/api/v1/storage/findings?category=temp").json()["findings"]
        assert [Path(f["path"]).name for f in temp] == ["velho.tmp"]
        plan = c.post("/api/v1/storage/plans", json={"finding_ids": [temp[0]["id"]]}, headers=ORIGIN).json()
        assert plan["status"] == "proposed" and plan["files_found"] == 1

        # A execução passa pelo catálogo de ações (clique do usuário = aprovação), como qualquer operação.
        done = c.post("/api/v1/actions", json={"operation": "cleanup_quarantine", "target_id": plan["id"]}, headers=ORIGIN).json()
        assert done["status"] == "completed" and not (tree.temp / "velho.tmp").exists()
        items = c.get("/api/v1/storage/quarantine").json()["items"]
        assert len(items) == 1
        back = c.post("/api/v1/actions", json={"operation": "quarantine_restore", "target_id": items[0]["id"]}, headers=ORIGIN).json()
        assert back["status"] == "completed" and (tree.temp / "velho.tmp").exists()
        reports = c.get("/api/v1/storage/reports").json()["reports"]
        assert reports[0]["files_moved"] == 1
        audit = {a["operation"] for a in c.get("/api/v1/audit").json()["entries"]}
        assert {"storage.cleanup", "storage.restore", "storage.authorized_dirs"} <= audit


def test_storage_routes_require_session(api):  # noqa: F811
    assert api.client.get("/api/v1/storage/status").status_code == 401
    assert api.client.post("/api/v1/storage/analyze", json={}, headers=ORIGIN).status_code == 401
