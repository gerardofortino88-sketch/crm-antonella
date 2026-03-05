"""
CRM API - Antonella Travel Designer
Deploy su Railway
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import os
from pymongo import MongoClient
from bson import ObjectId

app = FastAPI(title="CRM Antonella Travel Designer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB - usa variabile d'ambiente MONGO_URL
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "crm_database")

client = MongoClient(MONGO_URL)
db = client[DB_NAME]
contatti = db["contatti"]

# Indici
contatti.create_index("email", unique=True, sparse=True)
contatti.create_index("categoriaCliente")
contatti.create_index("nome")

# ============================================
# MODELLI
# ============================================

class Contatto(BaseModel):
    nome: str
    email: str
    telefono: Optional[str] = ""
    categoriaCliente: Optional[str] = "NOMINATIVO"
    numeroViaggi: Optional[int] = 0
    totaleSpeso: Optional[float] = 0
    ultimaPrenotazione: Optional[str] = ""
    note: Optional[str] = ""

class ContattoResponse(Contatto):
    id: str

class PaginatedResponse(BaseModel):
    items: List[ContattoResponse]
    totalCount: int
    currentPage: int
    totalPages: int

class StatsResponse(BaseModel):
    totaleContatti: int
    clientiHot: int
    clientiWarm: int
    clientiCold: int
    clientiNominativi: int
    fatturatoTotale: float
    percentualeHot: float
    percentualeWarm: float
    percentualeCold: float

# ============================================
# HELPER
# ============================================

def serialize(doc):
    return ContattoResponse(
        id=str(doc["_id"]),
        nome=doc.get("nome", ""),
        email=doc.get("email", ""),
        telefono=doc.get("telefono", ""),
        categoriaCliente=doc.get("categoriaCliente", "NOMINATIVO"),
        numeroViaggi=doc.get("numeroViaggi", 0),
        totaleSpeso=doc.get("totaleSpeso", 0),
        ultimaPrenotazione=doc.get("ultimaPrenotazione", ""),
        note=doc.get("note", "")
    )

# ============================================
# ENDPOINTS
# ============================================

@app.get("/")
async def root():
    return {"status": "ok", "message": "CRM API Antonella Travel Designer"}

@app.get("/api/health")
async def health():
    count = contatti.count_documents({})
    return {"status": "ok", "contatti_count": count}

@app.get("/api/statistiche", response_model=StatsResponse)
async def statistiche():
    total = contatti.count_documents({})
    hot = contatti.count_documents({"categoriaCliente": "HOT"})
    warm = contatti.count_documents({"categoriaCliente": "WARM"})
    cold = contatti.count_documents({"categoriaCliente": "COLD"})
    nominativi = contatti.count_documents({"categoriaCliente": "NOMINATIVO"})
    
    pipeline = [{"$group": {"_id": None, "totale": {"$sum": "$totaleSpeso"}}}]
    result = list(contatti.aggregate(pipeline))
    fatturato = result[0]["totale"] if result else 0
    
    return StatsResponse(
        totaleContatti=total,
        clientiHot=hot,
        clientiWarm=warm,
        clientiCold=cold,
        clientiNominativi=nominativi,
        fatturatoTotale=fatturato,
        percentualeHot=round((hot / total * 100), 1) if total > 0 else 0,
        percentualeWarm=round((warm / total * 100), 1) if total > 0 else 0,
        percentualeCold=round((cold / total * 100), 1) if total > 0 else 0
    )

@app.get("/api/contatti", response_model=PaginatedResponse)
async def get_contatti(
    categoria: Optional[str] = None,
    ricerca: Optional[str] = None,
    viaggiMin: Optional[int] = None,
    spesoMin: Optional[float] = None,
    pagina: int = Query(1, ge=1),
    limite: int = Query(50, ge=1, le=500),
    ordinaPer: str = "nome",
    ordine: str = "asc"
):
    query = {}
    
    if categoria and categoria != "TUTTI":
        query["categoriaCliente"] = categoria
    
    if ricerca:
        query["$or"] = [
            {"nome": {"$regex": ricerca, "$options": "i"}},
            {"email": {"$regex": ricerca, "$options": "i"}},
            {"telefono": {"$regex": ricerca, "$options": "i"}}
        ]
    
    if viaggiMin:
        query["numeroViaggi"] = {"$gte": viaggiMin}
    
    if spesoMin:
        query["totaleSpeso"] = {"$gte": spesoMin}
    
    total = contatti.count_documents(query)
    sort_dir = 1 if ordine == "asc" else -1
    skip = (pagina - 1) * limite
    
    cursor = contatti.find(query).sort(ordinaPer, sort_dir).skip(skip).limit(limite)
    items = [serialize(doc) for doc in cursor]
    
    return PaginatedResponse(
        items=items,
        totalCount=total,
        currentPage=pagina,
        totalPages=(total + limite - 1) // limite if total > 0 else 1
    )

@app.get("/api/contatti/{id}", response_model=ContattoResponse)
async def get_contatto(id: str):
    doc = contatti.find_one({"_id": ObjectId(id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Contatto non trovato")
    return serialize(doc)

@app.post("/api/contatti", response_model=ContattoResponse)
async def crea_contatto(contatto: Contatto):
    doc = contatto.dict()
    doc["dataCreazione"] = datetime.now().isoformat()
    doc["ultimaModifica"] = datetime.now().isoformat()
    
    try:
        result = contatti.insert_one(doc)
        doc["_id"] = result.inserted_id
        return serialize(doc)
    except Exception as e:
        if "duplicate key" in str(e):
            raise HTTPException(status_code=400, detail="Email già esistente")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/contatti/{id}", response_model=ContattoResponse)
async def aggiorna_contatto(id: str, contatto: Contatto):
    update_data = contatto.dict()
    update_data["ultimaModifica"] = datetime.now().isoformat()
    
    result = contatti.find_one_and_update(
        {"_id": ObjectId(id)},
        {"$set": update_data},
        return_document=True
    )
    
    if not result:
        raise HTTPException(status_code=404, detail="Contatto non trovato")
    return serialize(result)

@app.delete("/api/contatti/{id}")
async def elimina_contatto(id: str):
    result = contatti.delete_one({"_id": ObjectId(id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Contatto non trovato")
    return {"success": True}

@app.get("/api/emails-by-categoria")
async def emails_by_categoria(categoria: Optional[str] = None):
    query = {"email": {"$exists": True, "$ne": ""}}
    if categoria and categoria != "TUTTI":
        query["categoriaCliente"] = categoria
    
    cursor = contatti.find(query, {"email": 1, "_id": 0})
    emails = [doc["email"] for doc in cursor if doc.get("email")]
    return {"emails": emails, "count": len(emails)}

# ============================================
# IMPORT BULK
# ============================================

@app.post("/api/import")
async def import_contatti(items: List[Contatto]):
    risultati = {"successo": 0, "aggiornati": 0, "errori": 0}
    
    for item in items:
        try:
            doc = item.dict()
            doc["ultimaModifica"] = datetime.now().isoformat()
            
            result = contatti.update_one(
                {"email": doc["email"]},
                {"$set": doc, "$setOnInsert": {"dataCreazione": datetime.now().isoformat()}},
                upsert=True
            )
            
            if result.upserted_id:
                risultati["successo"] += 1
            else:
                risultati["aggiornati"] += 1
        except:
            risultati["errori"] += 1
    
    return risultati

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
