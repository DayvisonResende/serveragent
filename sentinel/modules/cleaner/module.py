"""Armazenamento e limpeza assistida (PRD 8): análise → recomendação → aprovação → execução.

- A análise só lê. Roda quando o usuário pede ou, se configurado, quando a última
  tem mais de ``analysis_interval_hours``; pausa sob pressão severa.
- Um plano de limpeza é uma lista fechada de arquivos vindos da análise mais
  recente. Executá-lo é a operação ``cleanup_quarantine`` do catálogo da Fase 4:
  o clique do usuário aprova; pedidos da IA ficam pendentes.
- Antes de mover, cada arquivo é revalidado (ainda existe, mesmo tamanho e data,
  dentro das pastas autorizadas, não protegido). O que mudou é ignorado.
- Nada é apagado de imediato: vai para a quarentena. Exclusão definitiva só por
  decisão do usuário (operação crítica, com confirmação digitada) ou pela
  política de retenção configurada.
"""

from __future__ import annotations

import asyncio
import logging
import os
import stat
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sentinel.agent.config import PROJECT_ROOT
from sentinel.core.clock import to_iso, utc_now
from sentinel.core.event_bus import Event, Severity
from sentinel.core.exceptions import SentinelError
from sentinel.core.module_registry import Module, ModuleHealth
from sentinel.core.resource_manager import PressureLevel
from sentinel.database.repositories.audit import AuditRepository
from sentinel.database.repositories.settings import SettingsRepository
from sentinel.database.repositories.storage import StorageRepository
from sentinel.modules.cleaner import scope
from sentinel.modules.cleaner.analyzer import AnalysisCancelled, Options, Throttle, analyze, default_disk_roots
from sentinel.modules.cleaner.quarantine import QuarantineStore
from sentinel.modules.security.operations import ActionError, OperationSpec, Target, _fingerprint

if TYPE_CHECKING:
    from sentinel.core.context import AgentContext
    from sentinel.modules.security.module import SecurityModule
    from sentinel.modules.servers.manager import ServersModule

log = logging.getLogger(__name__)

AUTHORIZED_KEY = "storage_authorized_dirs"
RETENTION_ACTOR = "politica-retencao"
MAX_PLAN_ITEMS = 5000
CATEGORY_LABEL = {"temp": "temporários antigos", "old_log": "logs antigos", "duplicate": "duplicados", "large": "arquivos grandes"}
MB, GB = 1024**2, 1024**3


class StorageError(SentinelError):
    """Pedido recusado (mensagem para o usuário)."""


def fmt_bytes(n: float) -> str:
    for unit, size in (("GB", GB), ("MB", MB), ("KB", 1024)):
        if n >= size:
            return f"{n / size:.1f} {unit}".replace(".", ",")
    return f"{int(n)} bytes"


class CleanerModule(Module):
    name = "storage"

    def __init__(self, servers: ServersModule | None, security: SecurityModule | None) -> None:
        self._servers = servers
        self._security = security
        self._ctx: AgentContext | None = None
        self._repo: StorageRepository | None = None
        self._store: QuarantineStore | None = None
        self._task: asyncio.Task[None] | None = None
        self._throttle: Throttle | None = None
        self.progress: dict[str, Any] | None = None
        self.authorized: list[str] = []
        self._custom_authorized = False

    # ---------------------------------------------------------------- ciclo de vida

    async def start(self, context: AgentContext) -> None:
        self._ctx = context
        self._repo = StorageRepository(context.database)
        self._store = QuarantineStore(context.settings.paths.data_dir / "quarantine")
        await self._repo.fail_running("o agente foi encerrado durante a análise")
        saved = await SettingsRepository(context.database).get(AUTHORIZED_KEY)
        self._custom_authorized = saved is not None
        self.authorized = list(saved) if saved is not None else scope.default_authorized()
        if self._security is not None and self._security.actions is not None:
            self._security.actions.register(self.operations())
        else:
            log.warning("Aprovações indisponíveis: a limpeza ficará desativada")
        if context.settings.storage.analysis_interval_hours:
            context.scheduler.add_job("storage.analysis", self._maybe_scheduled_analysis, 3600, timeout=60)
        context.scheduler.add_job("storage.retention", self.apply_retention, 6 * 3600, timeout=900, run_immediately=True)

    async def stop(self) -> None:
        if self._throttle is not None:
            self._throttle.cancel.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), 15)
            except (asyncio.TimeoutError, Exception):
                log.warning("Análise de armazenamento não terminou a tempo")
        if self._ctx is not None:
            for job in ("storage.analysis", "storage.retention"):
                try:
                    await self._ctx.scheduler.remove_job(job)
                except Exception:
                    pass

    def health(self) -> ModuleHealth:
        if self.running:
            return ModuleHealth(True, "analisando o armazenamento")
        return ModuleHealth(True, f"{len(self.authorized)} pasta(s) autorizada(s) para limpeza")

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def _protection(self) -> scope.Protection:
        assert self._ctx is not None
        records = self._servers.records() if self._servers is not None else []
        return scope.build_protection(PROJECT_ROOT, self._ctx.settings.paths.data_dir, scope.server_directories(records))

    # ---------------------------------------------------------------- análise

    async def start_analysis(self, trigger: str, full_disk: bool | None = None) -> int:
        assert self._ctx is not None and self._repo is not None
        if self.running:
            raise StorageError("Já existe uma análise em andamento")
        s = self._ctx.settings.storage
        full = s.full_disk_view if full_disk is None else full_disk
        options = Options(
            large_bytes=s.large_file_mb * MB, temp_age_seconds=s.temp_min_age_days * 86_400,
            log_age_seconds=s.log_min_age_days * 86_400, duplicate_min_bytes=s.duplicate_min_mb * MB,
            max_hash_bytes=int(s.max_hash_gb * GB), disk_roots=await asyncio.to_thread(default_disk_roots) if full else (),
        )
        resources = self._ctx.resources
        self._throttle = Throttle(should_pause=lambda: resources.level is PressureLevel.SEVERE)
        analysis_id = await self._repo.start_analysis(trigger)
        self.progress = {"analysis_id": analysis_id, "started_at": time.time(), "files": 0, "dirs": 0, "bytes": 0,
                         "current": "", "full_disk": full}
        self._task = asyncio.create_task(self._run(analysis_id, options, self._protection(), list(self.authorized)))
        return analysis_id

    def cancel_analysis(self) -> bool:
        if not self.running or self._throttle is None:
            return False
        self._throttle.cancel.set()
        return True

    async def _maybe_scheduled_analysis(self) -> None:
        assert self._ctx is not None and self._repo is not None
        if self.running:
            return
        last = await self._repo.latest_analysis(None)
        hours = self._ctx.settings.storage.analysis_interval_hours
        if last and time.time() - _epoch(last["started_at"]) < hours * 3600:
            return
        await self.start_analysis("agendada")

    async def _run(self, analysis_id: int, options: Options, protection: scope.Protection, authorized: list[str]) -> None:
        assert self._repo is not None and self._throttle is not None

        def progress(p: dict[str, Any]) -> None:
            if self.progress is not None:
                self.progress = {**self.progress, **p}

        try:
            result = await asyncio.to_thread(analyze, authorized, protection, options, self._throttle, progress)
            previous = await self._repo.latest_analysis()
            result.summary["growth"] = _growth(result.summary, previous)
            await self._repo.finish_analysis(analysis_id, "completed", result.summary, result.findings)
            rec = result.summary["recoverable_bytes"]
            self._publish("storage.analysis_completed", Severity.INFO, "Análise de armazenamento concluída",
                          f"{result.summary['files']} arquivos lidos em {result.summary['seconds']:.0f} s. "
                          f"Estimativa do que pode ser limpo nas pastas autorizadas: {fmt_bytes(rec)}.",
                          {"analysis_id": analysis_id, "recoverable_bytes": rec})
        except AnalysisCancelled:
            await self._repo.finish_analysis(analysis_id, "cancelled", error="cancelada")
        except Exception as exc:
            log.exception("Falha na análise de armazenamento")
            await self._repo.finish_analysis(analysis_id, "failed", error=f"{type(exc).__name__}: {exc}")
        finally:
            self.progress = None

    # ---------------------------------------------------------------- consultas

    async def status(self) -> dict[str, Any]:
        assert self._ctx is not None and self._repo is not None
        s = self._ctx.settings.storage
        usage = await self._repo.quarantine_usage()
        return {
            "running": self.running,
            "progress": self.progress,
            "last": await self._repo.latest_analysis(None),
            "last_completed": await self._repo.latest_analysis(),
            "quarantine": {**usage, "max_bytes": int(s.quarantine_max_gb * GB), "retention_days": s.quarantine_retention_days},
            "authorized": [{"path": p, "exists": os.path.isdir(p)} for p in self.authorized],
            "authorized_is_default": not self._custom_authorized,
            "thresholds": {"large_file_mb": s.large_file_mb, "temp_min_age_days": s.temp_min_age_days,
                           "log_min_age_days": s.log_min_age_days, "duplicate_min_mb": s.duplicate_min_mb},
        }

    async def findings(self, category: str | None, limit: int = 500) -> dict[str, Any]:
        assert self._repo is not None
        last = await self._repo.latest_analysis()
        if last is None:
            return {"analysis_id": None, "findings": []}
        rows = await self._repo.findings(last["id"], category, limit)
        # O que já foi movido (ou apagado por outro programa) depois da análise sai da lista.
        present = await asyncio.to_thread(lambda: [os.path.lexists(r["path"]) for r in rows])
        return {"analysis_id": last["id"], "findings": [r for r, ok in zip(rows, present) if ok],
                "gone": present.count(False)}

    async def set_authorized(self, folders: list[str]) -> list[str]:
        assert self._ctx is not None
        protection = self._protection()
        refused = [f"{f}: {why}" for f in folders if (why := scope.check_authorizable(f, protection))]
        if refused:
            raise StorageError("Pasta(s) recusada(s):\n" + "\n".join(refused))
        normalized = scope.unique(folders)
        await SettingsRepository(self._ctx.database).set(AUTHORIZED_KEY, normalized)
        self.authorized, self._custom_authorized = normalized, True
        await AuditRepository(self._ctx.database).record(actor="usuario", operation="storage.authorized_dirs", result="ok",
                                                         details={"folders": normalized})
        return normalized

    # ---------------------------------------------------------------- planos

    async def create_plan(self, requested_by: str, finding_ids: list[int] | None = None, category: str | None = None,
                          reason: str = "") -> dict[str, Any]:
        assert self._repo is not None
        last = await self._repo.latest_analysis()
        if last is None:
            raise StorageError("Nenhuma análise concluída ainda. Rode uma análise primeiro.")
        if finding_ids:
            ids = sorted(set(finding_ids))
            rows = await self._repo.findings_by_id(last["id"], ids)
            if len(rows) != len(ids):
                raise StorageError("Alguns itens não pertencem à análise mais recente. Atualize a página.")
        elif category in CATEGORY_LABEL:
            rows = [r for r in await self._repo.findings(last["id"], category, MAX_PLAN_ITEMS + 1) if r["cleanable"]]
        else:
            raise StorageError("Escolha os arquivos ou uma categoria")
        blocked = [r for r in rows if not r["cleanable"]]
        if blocked:
            raise StorageError(f"{len(blocked)} item(ns) não podem ser limpos: protegidos, fora das pastas autorizadas"
                               " ou cópia mantida de um grupo de duplicados")
        if not rows:
            raise StorageError("Nada a limpar nesta categoria")
        if len(rows) > MAX_PLAN_ITEMS:
            raise StorageError(f"No máximo {MAX_PLAN_ITEMS} arquivos por limpeza")
        items = [{"finding_id": r["id"], "path": r["path"], "size": r["size_bytes"], "mtime": r["modified_at"],
                  "category": r["category"]} for r in rows]
        report_id = await self._repo.create_plan(last["id"], requested_by, items, reason or "limpeza sugerida pela análise")
        return await self.report(report_id)

    async def report(self, report_id: int) -> dict[str, Any]:
        assert self._repo is not None
        report = await self._repo.get_report(report_id)
        if report is None:
            raise StorageError(f"Limpeza #{report_id} não encontrada")
        return report

    async def discard_plan(self, report_id: int) -> bool:
        assert self._repo is not None
        return await self._repo.discard_plan(report_id)

    # ---------------------------------------------------------------- operações do catálogo

    def operations(self) -> dict[str, OperationSpec]:
        assert self._repo is not None
        repo = self._repo

        async def resolve_plan(report_id: int, params: dict[str, Any]) -> Target:
            report = await repo.get_report(report_id)
            if report is None:
                raise ActionError(f"Limpeza #{report_id} não encontrada")
            if report["status"] != "proposed":
                raise ActionError(f"A limpeza #{report_id} não está mais aguardando execução ({report['status']})")
            fp = _fingerprint({"operation": "cleanup_quarantine", "id": report_id, "items": report["details"].get("items")})
            return Target(report_id, f"limpeza #{report_id}", fp)

        async def resolve_restore(item_id: int, params: dict[str, Any]) -> Target:
            item = await repo.quarantine_item(item_id)
            if item is None or item["status"] != "quarantined":
                raise ActionError(f"Item {item_id} não está na quarentena")
            fp = _fingerprint({"operation": "quarantine_restore", "id": item_id, "stored": item["stored_path"]})
            return Target(item_id, os.path.basename(item["original_path"]), fp)

        async def resolve_delete(report_id: int, params: dict[str, Any]) -> Target:
            items = await repo.quarantine("quarantined", report_id)
            if not items:
                raise ActionError(f"Nenhum arquivo da limpeza #{report_id} está na quarentena")
            fp = _fingerprint({"operation": "quarantine_delete", "id": report_id, "items": sorted(i["id"] for i in items)})
            return Target(report_id, f"limpeza #{report_id}", fp)

        async def run_plan(target_id: int, params: dict[str, Any], actor: str, reason: str, approval_id: int | None) -> dict[str, Any]:
            return await self._execute_plan(target_id, actor, approval_id)

        async def run_restore(target_id: int, params: dict[str, Any], actor: str, reason: str, approval_id: int | None) -> dict[str, Any]:
            return await self._restore(target_id, actor, approval_id)

        async def run_delete(target_id: int, params: dict[str, Any], actor: str, reason: str, approval_id: int | None) -> dict[str, Any]:
            return await self._delete_report(target_id, actor, approval_id)

        return {
            "cleanup_quarantine": OperationSpec(
                "cleanup_quarantine", "Mover arquivos para a quarentena", 2,
                "Os arquivos saem do lugar original e ficam guardados na quarentena do Sentinel, de onde podem ser restaurados."
                " No mesmo disco, o espaço só é liberado quando a quarentena for esvaziada.",
                "Um programa que dependa de algum desses arquivos pode falhar até a restauração.",
                resolve_plan, run_plan),
            "quarantine_restore": OperationSpec(
                "quarantine_restore", "Restaurar da quarentena", 1,
                "Devolve o arquivo ao local original.",
                "Nenhum arquivo é sobrescrito: se já existir outro com o mesmo nome no local, a restauração é recusada.",
                resolve_restore, run_restore),
            "quarantine_delete": OperationSpec(
                "quarantine_delete", "Excluir definitivamente da quarentena", 3,
                "Apaga de vez os arquivos desta limpeza que ainda estão na quarentena e libera o espaço.",
                "Não há como desfazer.",
                resolve_delete, run_delete),
        }

    async def _execute_plan(self, report_id: int, actor: str, approval_id: int | None) -> dict[str, Any]:
        assert self._ctx is not None and self._repo is not None and self._store is not None
        repo, store = self._repo, self._store
        if not await repo.claim_plan(report_id):
            raise ActionError(f"A limpeza #{report_id} já foi executada ou descartada")
        report = await self.report(report_id)
        items: list[dict[str, Any]] = report["details"].get("items", [])
        limit = int(self._ctx.settings.storage.quarantine_max_gb * GB)
        used = (await repo.quarantine_usage())["bytes"]
        total = sum(i["size"] for i in items)
        if used + total > limit:
            message = (f"A quarentena passaria do limite ({fmt_bytes(used)} usados + {fmt_bytes(total)} > {fmt_bytes(limit)})."
                       " Exclua definitivamente limpezas antigas ou aumente storage.quarantine_max_gb.")
            await repo.finish_report(report_id, "failed", 0, 0, {**report["details"], "error": message})
            raise ActionError(message)

        protection, authorized = self._protection(), list(self.authorized)
        throttle = Throttle()
        moved = moved_bytes = 0
        results = []
        for index, item in enumerate(items, 1):
            outcome = await asyncio.to_thread(self._move_one, store, report_id, index, item, protection, authorized, throttle)
            if outcome.get("stored_path"):
                await repo.add_quarantined(report_id, {**outcome, "original_path": item["path"], "size": item["size"],
                                                       "mtime": item["mtime"], "category": item["category"],
                                                       "reason": CATEGORY_LABEL.get(item["category"], item["category"])})
                moved += 1
                moved_bytes += item["size"]
            results.append({**item, "result": outcome["result"]})
        status = "completed" if moved == len(items) else "partial" if moved else "failed"
        skipped = len(items) - moved
        await repo.finish_report(report_id, status, moved, 0, {**report["details"], "items": results})
        message = f"{moved} de {len(items)} arquivo(s) movidos para a quarentena ({fmt_bytes(moved_bytes)})"
        if skipped:
            message += f"; {skipped} ignorado(s) — veja o relatório da limpeza #{report_id}"
        await AuditRepository(self._ctx.database).record(
            actor=actor, operation="storage.cleanup", target=f"limpeza #{report_id}", result=status, approval_id=approval_id,
            details={"moved": moved, "skipped": skipped, "bytes": moved_bytes})
        self._publish("storage.cleanup", Severity.INFO, f"Limpeza #{report_id}: {status_label(status)}", message,
                      {"report_id": report_id, "moved": moved, "skipped": skipped})
        return {"ok": moved > 0, "message": message, "moved": moved, "skipped": skipped, "bytes": moved_bytes}

    @staticmethod
    def _move_one(store: QuarantineStore, report_id: int, index: int, item: dict[str, Any], protection: scope.Protection,
                  authorized: list[str], throttle: Throttle) -> dict[str, Any]:
        """Revalida e move um arquivo (roda numa thread). Nunca levanta: devolve o resultado."""
        path = item["path"]
        try:
            info = os.stat(path, follow_symlinks=False)
        except FileNotFoundError:
            return {"result": "não existe mais"}
        except OSError as exc:
            return {"result": f"sem acesso: {exc.strerror or exc}"}
        if not stat.S_ISREG(info.st_mode):
            return {"result": "não é mais um arquivo comum"}
        if info.st_size != item["size"] or abs(info.st_mtime - item["mtime"]) > 1:
            return {"result": "mudou desde a análise"}
        if not any(scope.is_within(path, a) for a in authorized):
            return {"result": "fora das pastas autorizadas"}
        why = protection.reason(path, scope.file_attributes(info))
        if why:
            return {"result": f"protegido: {why}"}
        if scope.is_cloud_placeholder(info):
            return {"result": "arquivo na nuvem (OneDrive)"}
        try:
            stored, digest = store.move_in(path, report_id, index, throttle)
        except OSError as exc:
            return {"result": f"em uso ou sem permissão: {exc.strerror or exc}"}
        except Exception as exc:
            return {"result": f"falhou: {exc}"}
        return {"result": "movido", "stored_path": stored, "sha256": digest}

    async def _restore(self, item_id: int, actor: str, approval_id: int | None) -> dict[str, Any]:
        assert self._ctx is not None and self._repo is not None and self._store is not None
        item = await self._repo.quarantine_item(item_id)
        if item is None or item["status"] != "quarantined":
            raise ActionError(f"Item {item_id} não está na quarentena")
        await asyncio.to_thread(self._store.restore, item["stored_path"], item["original_path"])
        await self._repo.resolve_quarantined(item_id, "restored", actor)
        await AuditRepository(self._ctx.database).record(
            actor=actor, operation="storage.restore", target=item["original_path"], result="ok", approval_id=approval_id,
            details={"item_id": item_id, "report_id": item["report_id"]})
        return {"ok": True, "message": f"Restaurado em {item['original_path']}"}

    async def _delete_report(self, report_id: int, actor: str, approval_id: int | None) -> dict[str, Any]:
        assert self._ctx is not None and self._repo is not None
        items = await self._repo.quarantine("quarantined", report_id)
        count, freed = await self._delete_items(items, actor)
        await AuditRepository(self._ctx.database).record(
            actor=actor, operation="storage.quarantine_delete", target=f"limpeza #{report_id}", result="ok",
            approval_id=approval_id, details={"deleted": count, "bytes": freed})
        return {"ok": count > 0, "message": f"{count} arquivo(s) excluído(s) definitivamente; {fmt_bytes(freed)} liberados"}

    async def _delete_items(self, items: list[dict[str, Any]], actor: str) -> tuple[int, int]:
        assert self._repo is not None and self._store is not None
        count = freed = 0
        per_report: dict[int, int] = {}
        for item in items:
            try:
                await asyncio.to_thread(self._store.delete, item["stored_path"])
            except Exception as exc:
                log.warning("Falha ao excluir da quarentena", extra={"item_id": item["id"], "erro": str(exc)})
                continue
            if await self._repo.resolve_quarantined(item["id"], "deleted", actor):
                count += 1
                freed += item["size_bytes"]
                per_report[item["report_id"]] = per_report.get(item["report_id"], 0) + 1
        for rid, n in per_report.items():
            await self._repo.add_deleted(rid, n)
        return count, freed

    async def apply_retention(self) -> int:
        """Exclui definitivamente o que passou do prazo da quarentena (política configurada)."""
        assert self._ctx is not None and self._repo is not None
        days = self._ctx.settings.storage.quarantine_retention_days
        expired = await self._repo.expired_quarantine(to_iso(utc_now() - timedelta(days=days)))
        if not expired:
            return 0
        count, freed = await self._delete_items(expired, RETENTION_ACTOR)
        if count:
            await AuditRepository(self._ctx.database).record(
                actor=RETENTION_ACTOR, operation="storage.quarantine_delete", target="quarentena", result="ok",
                reason=f"itens com mais de {days} dias", details={"deleted": count, "bytes": freed})
            self._publish("storage.retention", Severity.INFO, "Quarentena: itens antigos excluídos",
                          f"{count} arquivo(s) com mais de {days} dias na quarentena foram excluídos ({fmt_bytes(freed)} liberados).",
                          {"deleted": count, "bytes": freed})
        return count

    def _publish(self, event_type: str, severity: Severity, title: str, description: str, meta: dict[str, Any]) -> None:
        assert self._ctx is not None
        self._ctx.event_bus.publish(Event(event_type=event_type, source="storage", severity=severity, title=title,
                                          description=description, metadata=meta))


def status_label(status: str) -> str:
    return {"completed": "concluída", "partial": "concluída em parte", "failed": "nada foi movido"}.get(status, status)


def _epoch(iso: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(iso).timestamp()


def _growth(summary: dict[str, Any], previous: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Pastas que mais cresceram desde a análise anterior (PRD 8.2: crescimento elevado)."""
    if not previous:
        return []
    before = {d["path"]: d["bytes"] for d in previous["summary"].get("top_dirs", [])}
    deltas = [{"path": d["path"], "delta_bytes": d["bytes"] - before[d["path"]], "since": previous["started_at"]}
              for d in summary.get("top_dirs", []) if d["path"] in before and d["bytes"] - before[d["path"]] >= 50 * MB]
    return sorted(deltas, key=lambda d: d["delta_bytes"], reverse=True)[:5]
