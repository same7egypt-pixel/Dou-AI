from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.entities import GeoCity, GeoCountry, GeoDistrict

router = APIRouter(prefix="/geo", tags=["geo"])


def country_out(c: GeoCountry) -> dict:
    cities = []
    for ct in c.cities:
        cities.append({
            "id": ct.id, "name": ct.name, "active": ct.active,
            "districts": [
                {"id": d.id, "name": d.name, "active": d.active}
                for d in ct.districts
            ],
        })
    return {
        "id": c.id, "name": c.name, "code": c.code, "flag": c.flag,
        "active": c.active, "cities": cities,
    }


class NameIn(BaseModel):
    name: str


class PatchIn(BaseModel):
    active: Optional[bool] = None
    name: Optional[str] = None


@router.get("/countries")
def list_countries(db: Session = Depends(get_db)):
    return [country_out(c) for c in db.query(GeoCountry).all()]


@router.post("/countries")
def add_country(payload: NameIn, db: Session = Depends(get_db)):
    code = payload.name[:2].upper() or "XX"
    c = GeoCountry(name=payload.name, code=code, flag="🌍", active=True)
    db.add(c)
    db.commit()
    db.refresh(c)
    return country_out(c)


@router.get("/countries/{cid}")
def get_country(cid: int, db: Session = Depends(get_db)):
    c = db.get(GeoCountry, cid)
    if not c:
        raise HTTPException(404, "Country not found")
    return country_out(c)


@router.patch("/countries/{cid}")
def patch_country(cid: int, payload: PatchIn, db: Session = Depends(get_db)):
    c = db.get(GeoCountry, cid)
    if not c:
        raise HTTPException(404, "Country not found")
    if payload.active is not None:
        c.active = payload.active
    if payload.name:
        c.name = payload.name
    db.commit()
    return country_out(c)


@router.delete("/countries/{cid}")
def delete_country(cid: int, db: Session = Depends(get_db)):
    c = db.get(GeoCountry, cid)
    if not c:
        raise HTTPException(404, "Country not found")
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.post("/countries/{cid}/cities")
def add_city(cid: int, payload: NameIn, db: Session = Depends(get_db)):
    c = db.get(GeoCountry, cid)
    if not c:
        raise HTTPException(404, "Country not found")
    ct = GeoCity(country_id=cid, name=payload.name, active=True)
    db.add(ct)
    db.commit()
    db.refresh(ct)
    return {"id": ct.id, "name": ct.name, "active": ct.active, "districts": []}


@router.get("/cities/{ctid}")
def get_city(ctid: int, db: Session = Depends(get_db)):
    ct = db.get(GeoCity, ctid)
    if not ct:
        raise HTTPException(404, "City not found")
    return {"id": ct.id, "name": ct.name, "active": ct.active,
            "districts": [{"id": d.id, "name": d.name, "active": d.active} for d in ct.districts]}


@router.patch("/cities/{ctid}")
def patch_city(ctid: int, payload: PatchIn, db: Session = Depends(get_db)):
    ct = db.get(GeoCity, ctid)
    if not ct:
        raise HTTPException(404, "City not found")
    if payload.active is not None:
        ct.active = payload.active
    if payload.name:
        ct.name = payload.name
    db.commit()
    return {"id": ct.id, "name": ct.name, "active": ct.active}


@router.delete("/cities/{ctid}")
def delete_city(ctid: int, db: Session = Depends(get_db)):
    ct = db.get(GeoCity, ctid)
    if not ct:
        raise HTTPException(404, "City not found")
    db.delete(ct)
    db.commit()
    return {"ok": True}


@router.post("/cities/{ctid}/districts")
def add_district(ctid: int, payload: NameIn, db: Session = Depends(get_db)):
    ct = db.get(GeoCity, ctid)
    if not ct:
        raise HTTPException(404, "City not found")
    d = GeoDistrict(city_id=ctid, name=payload.name, active=True)
    db.add(d)
    db.commit()
    db.refresh(d)
    return {"id": d.id, "name": d.name, "active": d.active}


@router.get("/districts/{did}")
def get_district(did: int, db: Session = Depends(get_db)):
    d = db.get(GeoDistrict, did)
    if not d:
        raise HTTPException(404, "District not found")
    return {"id": d.id, "name": d.name, "active": d.active}


@router.patch("/districts/{did}")
def patch_district(did: int, payload: PatchIn, db: Session = Depends(get_db)):
    d = db.get(GeoDistrict, did)
    if not d:
        raise HTTPException(404, "District not found")
    if payload.active is not None:
        d.active = payload.active
    if payload.name:
        d.name = payload.name
    db.commit()
    return {"id": d.id, "name": d.name, "active": d.active}


@router.delete("/districts/{did}")
def delete_district(did: int, db: Session = Depends(get_db)):
    d = db.get(GeoDistrict, did)
    if not d:
        raise HTTPException(404, "District not found")
    db.delete(d)
    db.commit()
    return {"ok": True}