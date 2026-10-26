import asyncio
import logging
from datetime import datetime, timezone

from celery import shared_task
from sqlalchemy import select

from app.clients.email import EmailServiceSkipped
from app.clients.http import clients
from app.clients.whatsapp import send_whatsapp
from app.database import AsyncSessionLocal
from app.flows.registry import FLOWS
from app.models import Event, Visitor, WorkflowRun, WorkflowStatus
from app.tasks.celery_app import celery_app


logger = logging.getLogger(__name__)


# =========================================================
# TASK ENTRY
# =========================================================

@celery_app.task(bind=True, name="workflow.run", max_retries=0)
def run_workflow(self, run_id: str) -> dict:
    return asyncio.run(_do_run_workflow(run_id))


# =========================================================
# MAIN LOGIC
# =========================================================

async def _do_run_workflow(run_id: str) -> dict:
    await clients.startup()
    try:
        async with AsyncSessionLocal() as db:
            run = await db.scalar(
                select(WorkflowRun).where(WorkflowRun.run_id == run_id)
            )
            if not run:
                logger.error("WorkflowRun not found: %s", run_id)
                return {"status": "not_found", "run_id": run_id}

            flow_def = FLOWS.get(run.flow_name)
            if not flow_def:
                run.status = WorkflowStatus.FAILED
                run.error = f"Unknown flow: {run.flow_name}"
                await db.commit()
                return {"status": "unknown_flow", "run_id": run_id}

            visitor = await db.scalar(
                select(Visitor).where(Visitor.txn_Id == run.txn_id)
            )
            if not visitor:
                run.status = WorkflowStatus.FAILED
                run.error = f"Visitor not found: {run.txn_id}"
                await db.commit()
                return {"status": "visitor_not_found", "run_id": run_id}

            run.status = WorkflowStatus.RUNNING
            run.started_at = datetime.now(timezone.utc)
            _init_steps(run, flow_def)
            await db.commit()

            any_failed = False
            any_completed = False

            for step in flow_def.steps:
                # OCR is already done by the time this task runs.
                if step.name == "ocr":
                    _set_step(run, "ocr", status="completed")
                    await db.commit()
                    any_completed = True
                    continue

                # Config gate for optional steps.
                if step.flag and not _config_flag(run, step.flag):
                    _set_step(run, step.name, status="skipped",
                              error=f"Flag '{step.flag}' is off")
                    await db.commit()
                    continue

                run.current_step = step.name
                _set_step(run, step.name, status="running")
                await db.commit()

                try:
                    result = await _dispatch_step(step.name, visitor, run)
                    _set_step(run, step.name, status="completed", result=result)
                    await db.commit()
                    any_completed = True
                    logger.info(
                        "workflow step ok run=%s step=%s", run_id, step.name,
                    )

                except EmailServiceSkipped as exc:
                    logger.info(
                        "workflow step skipped run=%s step=%s: %s",
                        run_id, step.name, exc,
                    )
                    _set_step(run, step.name, status="skipped",
                              error=str(exc)[:500])
                    await db.commit()
                    any_completed = True

                except Exception as exc:
                    logger.exception(
                        "workflow step failed run=%s step=%s: %s",
                        run_id, step.name, exc,
                    )
                    _set_step(run, step.name, status="failed",
                              error=str(exc)[:1000])
                    run.error = f"{step.name}: {exc}"[:2000]
                    await db.commit()
                    any_failed = True
                    break

            if any_failed and any_completed:
                run.status = WorkflowStatus.PARTIAL
            elif any_failed:
                run.status = WorkflowStatus.FAILED
            else:
                run.status = WorkflowStatus.COMPLETED

            run.current_step = None
            run.completed_at = datetime.now(timezone.utc)
            await db.commit()

            return {"status": run.status.value, "run_id": run_id}

    finally:
        await clients.shutdown()


# =========================================================
# STEP DISPATCH
# =========================================================

async def _dispatch_step(step_name: str, visitor: Visitor, run: WorkflowRun) -> dict:
    if step_name == "whatsapp":
        return await _step_whatsapp(visitor, run)
    if step_name == "email_campaign":
        return await _step_email_campaign(visitor, run)
    raise ValueError(f"Unknown step: {step_name}")


async def _step_whatsapp(visitor: Visitor, run: WorkflowRun) -> dict:
    if not visitor.phone:
        raise ValueError("Visitor has no phone number for WhatsApp")

    phone = _first_phone(visitor.phone)

    return await send_whatsapp(
        txn_id=visitor.txn_Id,
        phone=phone,
        template="welcome",
        variables={
            "name": visitor.name or "",
            "company": visitor.company_name or "",
        },
    )


async def _step_email_campaign(visitor: Visitor, run: WorkflowRun) -> dict:
    """Trigger the campaign configured on the visitor's event.

    Skips (not fails) if the event has no campaign_id, or if the Email
    service returns 404 for the campaign.
    """
    from app.clients.email import trigger_campaign

    async with AsyncSessionLocal() as db:
        event = await db.scalar(
            select(Event).where(Event.id == visitor.event_id)
        )

    if event is None:
        raise EmailServiceSkipped("Event not found for visitor")

    if not event.campaign_id:
        raise EmailServiceSkipped("No campaign configured for this event")

    agent_ids: list[int] = []
    if visitor.agent_id:
        agent_ids.append(visitor.agent_id)

    return await trigger_campaign(
        campaign_id=event.campaign_id,
        source_event_id=event.id,
        workflow_run_id=run.run_id,
        visitor=visitor,
        admin_id=visitor.admin_id,
        agent_ids=agent_ids,
    )


# =========================================================
# HELPERS
# =========================================================

def _init_steps(run: WorkflowRun, flow_def) -> None:
    steps = dict(run.steps or {})
    for step in flow_def.steps:
        if step.name not in steps:
            steps[step.name] = {"status": "pending"}
    run.steps = steps


def _set_step(
    run: WorkflowRun,
    step_name: str,
    *,
    status: str,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    steps = dict(run.steps or {})
    entry = dict(steps.get(step_name) or {})
    entry["status"] = status
    if result is not None:
        entry["result"] = result
    if error is not None:
        entry["error"] = error
    steps[step_name] = entry
    run.steps = steps


def _get_config(run: WorkflowRun) -> dict:
    return (run.steps or {}).get("config") or {}


def _config_flag(run: WorkflowRun, flag: str) -> bool:
    return bool(_get_config(run).get(flag))


def _first_phone(raw: str | None) -> str:
    if not raw:
        return ""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts[0] if parts else ""