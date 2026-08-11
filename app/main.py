from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .database import Base, engine
from .routers import merchants, couriers, orders, auth, shifts, shipping, analytics, geo, admin, fleet, billing
from .models import entities  # noqa: F401 — يسجّل الجداول على Base
from .migrations import run_migrations

Base.metadata.create_all(bind=engine)
run_migrations(engine)

app = FastAPI(title="DOU Platform API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(merchants.router)
app.include_router(couriers.router)
app.include_router(orders.router)
app.include_router(shifts.router)
app.include_router(shipping.router)
app.include_router(analytics.router)
app.include_router(geo.router)
app.include_router(admin.router)
app.include_router(fleet.router)
app.include_router(billing.router)

import os
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/health")
def health():
    return {"status": "ok", "service": "dou-api"}
