from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
async def health():
    """Check the health of app"""
    return {"status": 200, "service": "Gavnest Agent is up and running..."}