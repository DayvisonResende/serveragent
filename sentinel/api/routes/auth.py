"""Login por código de uso único e encerramento de sessão.

Fluxo: ``python -m sentinel dashboard`` (ou abrir-dashboard.bat) grava um
código válido por poucos minutos e abre ``/login?code=...`` no navegador. O
código é trocado por um cookie de sessão HttpOnly/SameSite=Strict.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from sentinel.api.app import get_deps
from sentinel.api.security import SESSION_COOKIE

public_router = APIRouter()
router = APIRouter(prefix="/api/v1/auth")

_FAILED_PAGE = """<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>Sentinel</title>
<link rel="stylesheet" href="/css/app.css"></head>
<body class="standalone"><main class="notice">
<h1>{title}</h1><p>{message}</p>
<p>Para entrar, execute <strong>abrir-dashboard.bat</strong> na pasta do Sentinel.</p>
</main></body></html>"""


@public_router.get("/login", include_in_schema=False)
async def login(request: Request, code: str = "") -> Response:
    auth = get_deps(request).auth
    if auth.limiter.blocked():
        return HTMLResponse(
            _FAILED_PAGE.format(title="Muitas tentativas", message="Aguarde um minuto e tente novamente."),
            status_code=429,
        )
    session = await auth.login(code)
    if session is None:
        return HTMLResponse(
            _FAILED_PAGE.format(title="Link inválido ou expirado", message="Cada link de acesso funciona uma única vez e por poucos minutos."),
            status_code=401,
        )
    token, expires = session
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max(int(expires - time.time()), 1),
        httponly=True,
        samesite="strict",
        secure=False,  # HTTP local; acesso remoto exigirá HTTPS (fase futura)
        path="/",
    )
    return response


@router.get("/session")
async def session_info() -> dict[str, bool]:
    return {"authenticated": True}


@router.post("/logout", status_code=204)
async def logout(request: Request) -> Response:
    await get_deps(request).auth.logout(request.cookies.get(SESSION_COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="strict", httponly=True)
    return response
