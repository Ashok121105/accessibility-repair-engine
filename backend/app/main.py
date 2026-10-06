from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.health import router as health_router
from backend.app.api.projects import router as projects_router
from backend.app.api.hindsight import router as hindsight_router
from backend.app.api.dashboard import router as dashboard_router
from backend.app.api.certificates import router as certificates_router
from backend.app.api.repair import router as repair_router
from backend.app.api.repair_application import router as repair_application_router
from backend.app.api.scan import router as scan_router
from backend.app.api.verification import router as verification_router
from backend.app.core.config import get_settings
from backend.app.projects.upload_limits import UploadSizeLimitMiddleware

settings = get_settings()

app = FastAPI(
    title="Accessibility Repair Engine",
    description="API foundation for verified accessibility repair workflows.",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.add_middleware(UploadSizeLimitMiddleware)
app.include_router(health_router, prefix="/api")
app.include_router(scan_router, prefix="/api")
app.include_router(repair_router, prefix="/api")
app.include_router(repair_application_router, prefix="/api")
app.include_router(verification_router, prefix="/api")
app.include_router(certificates_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(hindsight_router, prefix="/api")
app.include_router(projects_router, prefix="/api")
