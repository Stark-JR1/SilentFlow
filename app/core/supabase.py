from supabase import create_client, Client
from fastapi import Request, HTTPException, status, Depends
from fastapi.responses import RedirectResponse
from app.core.config import get_settings
from functools import lru_cache

settings = get_settings()


@lru_cache
def get_supabase() -> Client:
    """Anonymous client — for user-scoped operations with their JWT."""
    return create_client(str(settings.supabase_url), settings.supabase_anon_key)


@lru_cache
def get_admin_supabase() -> Client:
    """Service-role client — bypasses RLS for admin/server tasks."""
    return create_client(str(settings.supabase_url), settings.supabase_service_role_key)


def get_current_user(request: Request) -> dict:
    """
    Extract authenticated user from session cookie.
    Returns user dict or raises 401.
    """
    user = request.session.get("user")
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não autenticado",
        )
    return user


def get_current_user_optional(request: Request):
    """Same as above but returns None instead of raising."""
    return request.session.get("user")


def require_auth(request: Request) -> dict:
    """
    Use as a dependency in page routes.
    Redirects to /auth/login if not authenticated.
    """
    user = request.session.get("user")
    if not user:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/auth/login"},
        )
    return user


def get_authed_client(request: Request) -> Client:
    """
    Returns a Supabase client authenticated with the user's access token.
    Use this in API routes that need RLS to work correctly.
    """
    user = request.session.get("user")
    if not user or not user.get("access_token"):
        raise HTTPException(status_code=401, detail="Não autenticado")

    client = create_client(str(settings.supabase_url), settings.supabase_anon_key)
    client.postgrest.auth(user["access_token"])
    return client
