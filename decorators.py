"""
Decoradores de acceso para el sistema de roles.

Roles: invitado | miembro | admin

Uso:
    from decorators import login_required, miembro_required, admin_required
"""
from functools import wraps
from flask import session, redirect, jsonify, request


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "uid" not in session:
            return redirect("/")
        return f(*args, **kwargs)
    return decorated


def _es_ajax():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def miembro_required(f):
    """Solo miembro o admin pueden acceder. Invitados → redirige al dashboard."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "uid" not in session:
            return redirect("/")
        rol = session.get("rol", "invitado")
        if rol not in ("miembro", "admin"):
            if _es_ajax():
                return jsonify(ok=False, msg="Acceso restringido a Miembros"), 403
            return redirect("/dashboard?acceso=denegado")
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Solo admin puede acceder."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "uid" not in session:
            return redirect("/")
        if session.get("rol") != "admin":
            if _es_ajax():
                return jsonify(ok=False, msg="Acceso exclusivo de Admin"), 403
            return redirect("/dashboard?acceso=denegado")
        return f(*args, **kwargs)
    return decorated


def financiero_required(f):
    """Admin o Financiero/a pueden acceder."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "uid" not in session:
            return redirect("/")
        rol = session.get("rol", "invitado")
        es_fin = session.get("es_financiero", False)
        if rol != "admin" and not es_fin:
            if _es_ajax():
                return jsonify(ok=False, msg="Acceso restringido a Admin o Financiero/a"), 403
            return redirect("/dashboard?acceso=denegado")
        return f(*args, **kwargs)
    return decorated
