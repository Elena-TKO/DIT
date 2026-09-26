"""Снимки, камеры, анализ."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response

from app import schemas
from app.api.deps import current_user, get_ctx
from app.services import analysis, cameras, photos
from app.services.common import AppContext, ServiceError

router = APIRouter(prefix="/api")

MAX_BATCH_MB = 200

def _read(files: list[UploadFile]) -> list[tuple[str, bytes]]:
    limit = MAX_BATCH_MB * 1024 * 1024
    total = 0
    for f in files:
        f.file.seek(0, 2)
        size = f.file.tell()
        f.file.seek(0)
        total += size
        if total > limit:
            raise ServiceError(413, f"Слишком большой пакет: больше {MAX_BATCH_MB} МБ")
    return [(f.filename or "photo", f.file.read()) for f in files]


# ---------------------------------------------------------------- снимки
@router.post("/buildings/{building_id}/photos", tags=["photos"], status_code=201)
def upload_photos(building_id: int, files: list[UploadFile] = File(...), camera_id: str | None = Form(default=None),
                  start_at: str | None = Form(default=None), interval_min: int = Form(default=30),
                  user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    cam = int(camera_id) if camera_id and camera_id.strip().isdigit() else None
    return photos.upload_photos(ctx, user, building_id, _read(files), cam, start_at, interval_min)


@router.get("/buildings/{building_id}/photos", tags=["photos"])
def list_photos(building_id: int, limit: int = Query(default=200), offset: int = Query(default=0),
                camera_id: int | None = Query(default=None), taken_from: str | None = Query(default=None),
                taken_to: str | None = Query(default=None), cls: str | None = Query(default=None),
                user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return photos.list_photos(ctx, user, building_id, limit, offset, camera_id, taken_from, taken_to, cls)


@router.get("/photos/{photo_id}", tags=["photos"])
def photo_detail(photo_id: int, user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return photos.photo_detail(ctx, user, photo_id)


@router.get("/photos/{photo_id}/image", tags=["photos"])
def photo_image(photo_id: int, w: int | None = Query(default=None), user: int = Depends(current_user),
                ctx: AppContext = Depends(get_ctx)):
    path, mime = photos.image_file(ctx, user, photo_id, w)
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "private, max-age=86400"})


@router.put("/photos/{photo_id}/detections", tags=["photos"])
def replace_detections(photo_id: int, body: schemas.DetectionsIn, user: int = Depends(current_user),
                       ctx: AppContext = Depends(get_ctx)):
    return photos.replace_detections(ctx, user, photo_id, [i.model_dump() for i in body.items])


@router.post("/photos/{photo_id}/redetect", tags=["photos"])
def redetect(photo_id: int, user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return photos.redetect(ctx, user, photo_id)


@router.delete("/photos/{photo_id}", tags=["photos"], status_code=204)
def delete_photo(photo_id: int, user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    photos.delete_photo(ctx, user, photo_id)
    return Response(status_code=204)


# ---------------------------------------------------------------- анализ
@router.get("/buildings/{building_id}/analysis", tags=["analysis"])
def get_analysis(building_id: int, at: str | None = Query(default=None), user: int = Depends(current_user),
                 ctx: AppContext = Depends(get_ctx)):
    return analysis.analyze(ctx, user, building_id, at, save=False)


@router.post("/buildings/{building_id}/analysis", tags=["analysis"])
def run_analysis(building_id: int, at: str | None = Query(default=None), user: int = Depends(current_user),
                 ctx: AppContext = Depends(get_ctx)):
    """Анализ с сохранением вердикта и отклонений в журнал."""
    return analysis.analyze(ctx, user, building_id, at, save=True)


@router.get("/buildings/{building_id}/timeline", tags=["analysis"])
def get_timeline(building_id: int, at: str | None = Query(default=None), user: int = Depends(current_user),
                 ctx: AppContext = Depends(get_ctx)):
    return analysis.timeline(ctx, user, building_id, at)


@router.get("/buildings/{building_id}/deviations", tags=["analysis"])
def get_deviations(building_id: int, limit: int = Query(default=100), user: int = Depends(current_user),
                   ctx: AppContext = Depends(get_ctx)):
    return analysis.deviation_log(ctx, user, building_id, limit)


@router.get("/buildings/{building_id}/history", tags=["analysis"])
def get_history(building_id: int, limit: int = Query(default=60), user: int = Depends(current_user),
                ctx: AppContext = Depends(get_ctx)):
    return analysis.history(ctx, user, building_id, limit)


@router.get("/buildings/{building_id}/deviations.csv", tags=["analysis"], response_class=PlainTextResponse)
def deviations_csv(building_id: int, user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return PlainTextResponse(analysis.deviations_csv(ctx, user, building_id), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="deviations-{building_id}.csv"'})


# ---------------------------------------------------------------- камеры
@router.get("/projects/{project_id}/cameras", tags=["cameras"])
def list_cameras(project_id: int, user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return cameras.list_cameras(ctx, user, project_id)


@router.post("/projects/{project_id}/cameras", tags=["cameras"], status_code=201)
def create_camera(project_id: int, body: schemas.CameraIn, user: int = Depends(current_user),
                  ctx: AppContext = Depends(get_ctx)):
    return cameras.create_camera(ctx, user, project_id, **body.model_dump())


@router.get("/cameras/{camera_id}", tags=["cameras"])
def get_camera(camera_id: int, user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return cameras.get_camera(ctx, user, camera_id)


@router.patch("/cameras/{camera_id}", tags=["cameras"])
def update_camera(camera_id: int, body: schemas.CameraPatch, user: int = Depends(current_user),
                  ctx: AppContext = Depends(get_ctx)):
    return cameras.update_camera(ctx, user, camera_id, **body.model_dump())


@router.delete("/cameras/{camera_id}", tags=["cameras"], status_code=204)
def delete_camera(camera_id: int, user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    cameras.delete_camera(ctx, user, camera_id)
    return Response(status_code=204)