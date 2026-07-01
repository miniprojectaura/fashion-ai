from fastapi import APIRouter

from services.api.api.v1 import auth, avatar, chat, design, feedback, privacy, search, session, status, storage_files, tailor, tasks, voice, wardrobe, web_match

api_router = APIRouter()
api_router.include_router(status.router, prefix="/status", tags=["status"])
api_router.include_router(session.router, prefix="/session", tags=["session"])
api_router.include_router(storage_files.router, prefix="/storage", tags=["storage"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(feedback.router, prefix="/feedback", tags=["feedback"])
api_router.include_router(privacy.router, prefix="/privacy", tags=["privacy"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(avatar.router, prefix="/avatar", tags=["avatar"])
api_router.include_router(design.router, prefix="/design", tags=["design"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(wardrobe.router, prefix="/wardrobe", tags=["wardrobe"])
api_router.include_router(tailor.router, prefix="/tailor", tags=["tailor"])
api_router.include_router(voice.router, prefix="/voice", tags=["voice"])
api_router.include_router(web_match.router, prefix="/design", tags=["design-match"])
