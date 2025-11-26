# server.py
import asyncio
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

app = FastAPI(title="Fake Story API (with delay)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # autorisé en dev
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).parent.resolve()
STORY_FILE = BASE_DIR / "story.zip"

# Table de correspondance des IDs -> noms et couleurs
CHARACTER_MAP = {
    941054838965: {"name": "10011", "color": {"r": 0, "g": 200, "b": 0}},     # vert
    941054904502: {"name": "10005", "color": {"r": 0, "g": 100, "b": 255}},   # bleu
    941054314685: {"name": "40101", "color": {"r": 255, "g": 0, "b": 0}},     # rouge
}

DEFAULT_RESPONSE = {"name": "0", "color": {"r": 128, "g": 128, "b": 128}}  # gris


@app.get("/get-character")
async def get_character(tag_id: int = Query(..., description="Tag id du personnage")):
    """
    Retourne un personnage et sa couleur de groupe.
    """
    data = CHARACTER_MAP.get(tag_id, DEFAULT_RESPONSE)
    return JSONResponse({
        "name": data["name"],
        "group_color": data["color"]
    })


@app.post("/generate-story")
async def generate_story(request: Request):
    """
    Simule la génération d'une histoire (20 secondes d'attente),
    puis renvoie le fichier 'story.mp3' depuis le même dossier.
    """
    if not STORY_FILE.exists():
        raise HTTPException(status_code=500, detail=f"Audio file not found: {STORY_FILE.name}")

    # Lire le JSON facultatif (ignoré ici)
    try:
        _ = await request.json()
    except Exception:
        pass

    # Simule le délai de génération (20 secondes)
    await asyncio.sleep(5)

    return FileResponse(
        path=str(STORY_FILE),
        filename="story.zip",
        media_type="application/zip"
    )


@app.get("/")
def root():
    return {"msg": "Fake Story API — OK. GET /get-character?tag_id=...  POST /generate-story"}
