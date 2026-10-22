"""FastAPI gateway entry point.

Usage:
    uv run uvicorn gateway.main:app --host 0.0.0.0 --port 8000 --reload
"""
from contextlib import asynccontextmanager

from common.config import get_settings
from common.logging import configure_logging, get_logger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from gateway.routes import nesting  # F5 kumaş yerleşimi
from gateway.routes import animate, ar, auth, drape, engines, fabrics, face4d, generate, health, health_deep, jobs, print_prep, projects, prompt_library, scanfix, scenegen, sewing, system, templates, variations, versions, ws, media, retopo, upscale, export3d
from gateway.routes import mannequins  # F3: ölçüden manken
from gateway.routes import sew3d  # F2: kalıbı 3D'de mankene dik
from gateway.routes import patterns  # F1: FreeSewing kalıp


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifecycle: setup at startup, cleanup at shutdown."""
    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=True)
    log = get_logger("gateway")
    from gateway.db import init_db
    init_db()
    log.info("db_initialized")
    log.info(
        "gateway_starting",
        host=settings.gateway_host,
        port=settings.gateway_port,
    )
    yield
    log.info("gateway_stopping")


app = FastAPI(
    title="Clothing Design App — Gateway",
    version="0.1.0-bootstrap",
    lifespan=lifespan,
)

# Frontend localhost'tan (Vite proxy) ya da Tailscale host'undan çağırır.
# Auth, Authorization header'ındaki Bearer token ile yapılır (cookie yok), bu yüzden
# allow_credentials=False — bu sayede izinli origin listesi açıkça daraltılabilir
# (wildcard "*" + credentials=True tarayıcı tarafından reddedilen geçersiz bir kombo).
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(health_deep.router)
app.include_router(auth.router)
app.include_router(templates.router)
app.include_router(projects.router)
app.include_router(projects.public_router)
app.include_router(engines.router)
app.include_router(generate.router)
app.include_router(generate.preprocess_router)
app.include_router(generate.preprocess_public_router)
app.include_router(animate.router)
app.include_router(face4d.router)
app.include_router(scenegen.router)
app.include_router(scanfix.router)
app.include_router(jobs.router)
app.include_router(system.router)
app.include_router(variations.router)
app.include_router(drape.router)
app.include_router(fabrics.router)
app.include_router(ar.router)
app.include_router(ar.public_router)
app.include_router(prompt_library.router)
app.include_router(print_prep.router)
app.include_router(print_prep.public_router)
app.include_router(sewing.router)
app.include_router(sewing.public_router)
app.include_router(patterns.router)
app.include_router(patterns.public_router)
app.include_router(mannequins.router)
app.include_router(versions.router)
app.include_router(media.router)
app.include_router(retopo.router)
app.include_router(upscale.router)
app.include_router(export3d.router)
app.include_router(nesting.router)
app.include_router(nesting.public_router)
app.include_router(sew3d.router)
app.include_router(ws.router)


class _TemplatesStaticFiles(StaticFiles):
    """Statik şablon servisini her istekte güncel templates_dir'e bağlar.

    Düz `StaticFiles(directory=...)` dizini __init__ anında (modül import'unda)
    sabitler. Bu hem testlerde (her fixture taze TEMPLATES_DIR set eder) hem de
    üretimde (generate.py gateway başladıktan sonra çalışıp dizini doldurabilir)
    yanlış davranır. Dizini istek anında get_settings() üzerinden çözeriz.
    """

    @property
    def all_directories(self) -> list:
        return [str(get_settings().templates_dir)]

    @all_directories.setter
    def all_directories(self, _value: list) -> None:
        # StaticFiles.__init__ buraya yazmaya çalışır; dinamik olarak okuduğumuz
        # için yoksayıyoruz.
        pass


# Şablon GLB/PNG dosyaları — public statik servis.
# Dizin yoksa mount StaticFiles patlamasın diye check_dir=False.
app.mount(
    "/template-assets",
    _TemplatesStaticFiles(check_dir=False),
    name="template-assets",
)


@app.get("/")
async def root() -> dict:
    return {
        "service": "Clothing Design App Gateway",
        "version": "0.1.0-bootstrap",
        "docs": "/docs",
        "health": "/health",
    }
