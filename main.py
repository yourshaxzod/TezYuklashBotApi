from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os

# Ma'lumotlar bazasini ishga tushirish
from database.connection import init_db
from models.schemas import ApiResponse

# Config va Limiter import qilish
from config import limiter
from slowapi.errors import RateLimitExceeded

# Routerlarni import qilish
from api.youtube import router as youtube_router

# Zarur papkalarni yaratish
os.makedirs("downloads", exist_ok=True)
os.makedirs("database", exist_ok=True)

# FastAPI appni ishga tushirish
app = FastAPI(
    title="Tez Yuklash API",
    description="Ijtimoiy tarmoqlardan video va audio yuklash yoki ma'lumot olish uchun API.",
    version="1.0.1"
)

@app.get("/", response_model=ApiResponse, tags=["Asosiy"])
async def root():
    """
    API root bilan asosiy ma'lumotlar
    """
    return ApiResponse(
        status=True,
        message="Video Yuklash API",
    )

# CORS middleware qo'shish
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Barcha domainlardan so'rovlarga ruxsat berish
    allow_credentials=True,
    allow_methods=["*"],  # Barcha HTTP metodlarga ruxsat berish
    allow_headers=["*"],  # Barcha HTTP headerlar ruxsat berish
)

# Rate limit handlerni o'rnatish
app.state.limiter = limiter

# Routerlarni qo'shish
app.include_router(youtube_router)

# Ma'lumotlar bazasini ishga tushirish
init_db()

# ----- XATO QAYTA ISHLASH -----

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content=ApiResponse(
            status=False,
            message="Ichki server xatosi yuz berdi",
            error=str(exc)
        ).dict()
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content=ApiResponse(
            status=False,
            message=exc.detail,
            error=exc.detail
        ).dict()
    )

# ----- SERVER ISHGA TUSHIRISH -----
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)