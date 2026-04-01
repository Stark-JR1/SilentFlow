from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from postgrest.exceptions import APIError
from starlette.middleware.sessions import SessionMiddleware
from app.core.config import get_settings
from app.core.templates import build_templates

try:
    settings = get_settings()
except (RuntimeError, ValidationError) as e:
    raise RuntimeError(
        "Configuracao invalida: verifique SUPABASE_URL, SUPABASE_ANON_KEY | SUPABASE_KEY "
        "e SUPABASE_SERVICE_ROLE_KEY no .env"
        f"\n{e}"
    ) from e

from app.routers import auth, pages, api

@app.get("/healthz")
def healthz():
    return {"status": "ok"}


app = FastAPI(
    title="FinTrack Pro",
    description="App de finanças pessoais e familiares",
    version="1.0.0",
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url=None,
)

# ---- MIDDLEWARE --------------------------------------------
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.app_secret_key,
    max_age=604800,  # 7 days
    https_only=settings.app_env == "production",
    same_site="lax",
)

# ---- STATIC FILES -----------------------------------------
app.mount("/static", StaticFiles(directory="static"), name="static")

# ---- TEMPLATES --------------------------------------------
templates = build_templates()

# ---- ROUTERS -----------------------------------------------
app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(api.router)

# ---- ERROR HANDLERS ----------------------------------------
@app.exception_handler(401)
async def unauthorized_handler(request: Request, exc):
    return RedirectResponse("/auth/login", status_code=302)

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return templates.TemplateResponse(
        request, "pages/404.html", {"request": request}, status_code=404
    )


@app.exception_handler(APIError)
async def supabase_api_error_handler(request: Request, exc: APIError):
    message = str(exc)
    if "JWT expired" in message or "PGRST303" in message:
        request.session.clear()
        return RedirectResponse("/auth/login", status_code=302)
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            {"detail": "Erro ao comunicar com o Supabase."},
            status_code=502,
        )
    return templates.TemplateResponse(
        request,
        "pages/404.html",
        {"request": request},
        status_code=502,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_env == "development",
    )
