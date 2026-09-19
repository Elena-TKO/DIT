"""Авторизация, справочники, стройки, объекты, план работ."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, Response

from app import schemas
from app.api.deps import current_user, get_ctx
from app.services import analysis, projects
from app.services.common import AppContext
from app.services.report_html import render_report

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------- авторизация
@router.post("/auth/register", tags=["auth"])
def register(body: schemas.RegisterIn, ctx: AppContext = Depends(get_ctx)):
    return projects.register(ctx, body.email, body.password, body.name)


@router.post("/auth/login", tags=["auth"])
def login(body: schemas.LoginIn, ctx: AppContext = Depends(get_ctx)):
    return projects.login(ctx, body.email, body.password)


@router.get("/auth/me", tags=["auth"])
def me(user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return projects.get_user(ctx, user)


# ---------------------------------------------------------------- справочники
@router.get("/health", tags=["reference"])
def health(ctx: AppContext = Depends(get_ctx)):
    return {"status": "ok", "detector": ctx.detector.info(), "methodology_version": "1.0",
            "catalog_items": len(ctx.catalog)}


@router.get("/object-types", tags=["reference"])
def object_types():
    return projects.object_types()


@router.get("/methodology", tags=["reference"])
def methodology(ctx: AppContext = Depends(get_ctx)):
    return projects.methodology(ctx)


@router.get("/catalog", tags=["reference"])
def catalog(object_type: str | None = Query(default=None), ctx: AppContext = Depends(get_ctx)):
    return projects.catalog(ctx, object_type)


# ---------------------------------------------------------------- стройки
@router.get("/projects", tags=["projects"])
def list_projects(user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return projects.list_projects(ctx, user)


@router.post("/projects", tags=["projects"], status_code=201)
def create_project(body: schemas.ProjectIn, user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return projects.create_project(ctx, user, body.name, body.address, body.start_date, body.end_date)


@router.get("/projects/{project_id}", tags=["projects"])
def get_project(project_id: int, user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return projects.get_project(ctx, user, project_id)


@router.patch("/projects/{project_id}", tags=["projects"])
def update_project(project_id: int, body: schemas.ProjectPatch, user: int = Depends(current_user),
                   ctx: AppContext = Depends(get_ctx)):
    return projects.update_project(ctx, user, project_id, **body.model_dump())


@router.delete("/projects/{project_id}", tags=["projects"], status_code=204)
def delete_project(project_id: int, user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    projects.delete_project(ctx, user, project_id)
    return Response(status_code=204)


@router.get("/projects/{project_id}/overview", tags=["projects"])
def project_overview(project_id: int, user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return analysis.project_overview(ctx, user, project_id)


@router.get("/projects/{project_id}/report", tags=["report"])
def project_report(project_id: int, at: str | None = Query(default=None), user: int = Depends(current_user),
                   ctx: AppContext = Depends(get_ctx)):
    return analysis.project_report(ctx, user, project_id, at)


@router.get("/projects/{project_id}/report.html", tags=["report"], response_class=HTMLResponse)
def project_report_html(project_id: int, at: str | None = Query(default=None), user: int = Depends(current_user),
                        ctx: AppContext = Depends(get_ctx)):
    return HTMLResponse(render_report(ctx, user, project_id, at))


# ---------------------------------------------------------------- объекты
@router.post("/projects/{project_id}/report-link", tags=["report"])
def create_report_link(project_id: int, ttl_hours: int = Query(default=72), user: int = Depends(current_user),
                       ctx: AppContext = Depends(get_ctx)):
    """Ссылка на отчёт для заказчика: работает без входа, только чтение, с ограниченным сроком."""
    return analysis.create_report_link(ctx, user, project_id, ttl_hours)


@router.get("/public/report/{token}", tags=["report"], response_class=HTMLResponse)
def public_report(token: str, ctx: AppContext = Depends(get_ctx)):
    project_id, owner_id = analysis.project_by_report_token(ctx, token)
    return HTMLResponse(render_report(ctx, owner_id, project_id),
                        headers={"Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex"})


@router.get("/projects/{project_id}/buildings", tags=["buildings"])
def list_buildings(project_id: int, user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return projects.list_buildings(ctx, user, project_id)


@router.post("/projects/{project_id}/buildings", tags=["buildings"], status_code=201)
def create_building(project_id: int, body: schemas.BuildingIn, user: int = Depends(current_user),
                    ctx: AppContext = Depends(get_ctx)):
    return projects.create_building(ctx, user, project_id, body.name, body.object_type, body.start_date, body.end_date)


@router.get("/buildings/{building_id}", tags=["buildings"])
def get_building(building_id: int, user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return projects.get_building(ctx, user, building_id)


@router.patch("/buildings/{building_id}", tags=["buildings"])
def update_building(building_id: int, body: schemas.BuildingPatch, user: int = Depends(current_user),
                    ctx: AppContext = Depends(get_ctx)):
    return projects.update_building(ctx, user, building_id, body.name, body.start_date, body.end_date, body.reschedule)


@router.delete("/buildings/{building_id}", tags=["buildings"], status_code=204)
def delete_building(building_id: int, user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    projects.delete_building(ctx, user, building_id)
    return Response(status_code=204)


# ---------------------------------------------------------------- план
@router.get("/buildings/{building_id}/plan", tags=["plan"])
def get_plan(building_id: int, user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return projects.get_plan(ctx, user, building_id)


@router.patch("/buildings/{building_id}/plan/tasks/{task_id}", tags=["plan"])
def update_task(building_id: int, task_id: int, body: schemas.TaskPatch, user: int = Depends(current_user),
                ctx: AppContext = Depends(get_ctx)):
    return projects.update_task(ctx, user, building_id, task_id, **body.model_dump())


@router.post("/buildings/{building_id}/plan/bulk", tags=["plan"])
def bulk_toggle(building_id: int, body: schemas.BulkToggleIn, user: int = Depends(current_user),
                ctx: AppContext = Depends(get_ctx)):
    return projects.bulk_toggle(ctx, user, building_id, body.task_ids, body.enabled)


@router.post("/buildings/{building_id}/plan/reschedule", tags=["plan"])
def reschedule(building_id: int, user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return projects.reschedule_plan(ctx, user, building_id)


@router.post("/buildings/{building_id}/plan/regenerate", tags=["plan"])
def regenerate(building_id: int, user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return projects.regenerate_plan(ctx, user, building_id)
