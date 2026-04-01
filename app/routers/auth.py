from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from app.core.supabase import get_supabase
from app.core.config import get_settings
from app.core.templates import build_templates

router    = APIRouter(prefix="/auth", tags=["auth"])
templates = build_templates()
settings  = get_settings()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(request, "auth/login.html", {"request": request, "error": None})


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    supabase = get_supabase()
    try:
        resp = supabase.auth.sign_in_with_password({"email": email, "password": password})
        if not resp.user:
            raise Exception("Credenciais inválidas")

        request.session["user"] = {
            "id":           resp.user.id,
            "email":        resp.user.email,
            "full_name":    resp.user.user_metadata.get("full_name", ""),
            "access_token": resp.session.access_token,
        }
        return RedirectResponse("/dashboard", status_code=302)

    except Exception as e:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"request": request, "error": str(e)},
            status_code=400,
        )


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(request, "auth/register.html", {"request": request, "error": None})


@router.post("/register", response_class=HTMLResponse)
async def register_submit(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm: str = Form(...),
):
    if password != confirm:
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {"request": request, "error": "As senhas não coincidem"},
            status_code=400,
        )
    if len(password) < 6:
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {"request": request, "error": "Senha deve ter pelo menos 6 caracteres"},
            status_code=400,
        )

    supabase = get_supabase()
    try:
        resp = supabase.auth.sign_up({
            "email":    email,
            "password": password,
            "options":  {"data": {"full_name": full_name}},
        })
        if not resp.user:
            raise Exception("Erro ao criar conta")
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {"request": request, "error": None, "success": True, "email": email},
        )
    except Exception as e:
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {"request": request, "error": str(e)},
            status_code=400,
        )


@router.get("/logout")
async def logout(request: Request):
    supabase = get_supabase()
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    request.session.clear()
    return RedirectResponse("/auth/login", status_code=302)


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_page(request: Request):
    return templates.TemplateResponse(request, "auth/reset.html", {"request": request, "error": None, "success": False})


@router.post("/reset-password", response_class=HTMLResponse)
async def reset_submit(request: Request, email: str = Form(...)):
    supabase = get_supabase()
    try:
        redirect_to = f"{settings.app_url.rstrip('/')}/auth/reset-password/confirm"
        supabase.auth.reset_password_email(email, {"redirect_to": redirect_to})
        return templates.TemplateResponse(
            request,
            "auth/reset.html",
            {"request": request, "error": None, "success": True},
        )
    except Exception as e:
        return templates.TemplateResponse(
            request,
            "auth/reset.html",
            {"request": request, "error": str(e), "success": False},
            status_code=400,
        )


@router.get("/reset-password/confirm", response_class=HTMLResponse)
async def reset_confirm_page(request: Request):
    return templates.TemplateResponse(
        request,
        "auth/reset_confirm.html",
        {"request": request, "error": None, "success": False},
    )


@router.post("/reset-password/confirm", response_class=HTMLResponse)
async def reset_confirm_submit(
    request: Request,
    password: str = Form(...),
    confirm: str = Form(...),
    access_token: str = Form(""),
    refresh_token: str = Form(""),
):
    if password != confirm:
        return templates.TemplateResponse(
            request,
            "auth/reset_confirm.html",
            {"request": request, "error": "As senhas nao coincidem", "success": False},
            status_code=400,
        )
    if len(password) < 8:
        return templates.TemplateResponse(
            request,
            "auth/reset_confirm.html",
            {"request": request, "error": "A senha deve ter pelo menos 8 caracteres", "success": False},
            status_code=400,
        )
    if not any(char.isalpha() for char in password) or not any(char.isdigit() for char in password):
        return templates.TemplateResponse(
            request,
            "auth/reset_confirm.html",
            {"request": request, "error": "A senha deve conter pelo menos uma letra e um numero", "success": False},
            status_code=400,
        )
    if not access_token:
        return templates.TemplateResponse(
            request,
            "auth/reset_confirm.html",
            {"request": request, "error": "Token de recuperacao ausente ou invalido", "success": False},
            status_code=400,
        )

    supabase = get_supabase()
    try:
        if refresh_token:
            supabase.auth.set_session(access_token, refresh_token)
        else:
            setter = getattr(supabase.auth, "set_auth", None)
            if callable(setter):
                setter(access_token)
            else:
                supabase.auth.set_session(access_token, "")

        supabase.auth.update_user({"password": password})
        return templates.TemplateResponse(
            request,
            "auth/reset_confirm.html",
            {"request": request, "error": None, "success": True, "redirect_to_login": True},
        )
    except Exception as e:
        return templates.TemplateResponse(
            request,
            "auth/reset_confirm.html",
            {"request": request, "error": str(e), "success": False},
            status_code=400,
        )
