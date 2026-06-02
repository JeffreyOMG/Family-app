import os
from flask import Blueprint, render_template, request, redirect, session
from werkzeug.security import generate_password_hash, check_password_hash
from pg8000.exceptions import DatabaseError as IntegrityError
from database import get_db

auth_bp = Blueprint("auth", __name__)

# ─── Código secreto para registro como MIEMBRO ───────────────────────────────
# Configura esta variable en tus variables de entorno (Render, Railway, etc.)
# Nunca lo expongas en el frontend ni lo hardcodees en producción.
MEMBER_CODE = os.getenv("MEMBER_CODE", "FAMILIA2026")


@auth_bp.route("/", methods=["GET", "POST"])
def login():
    if "uid" in session:
        return redirect("/dashboard")
    error = ""
    if request.method == "POST":
        usu = request.form.get("usuario", "").strip()
        pwd = request.form.get("password", "")
        con = get_db()
        user = con.execute(
            "SELECT id, nombre, usuario, password, rol FROM usuarios WHERE usuario=%s", (usu,)
        ).fetchone()
        if user and (user["password"] == pwd or check_password_hash(user["password"], pwd)):
            if user["rol"] == "baneado":
                error = "Tu cuenta ha sido suspendida. Contacta al administrador."
            else:
                session.clear()
                session["uid"]    = user["id"]
                session["nombre"] = user["nombre"]
                session["rol"]    = user["rol"]
                return redirect("/dashboard")
        else:
            error = "Usuario o contraseña incorrectos"
    return render_template("login.html", error=error)


@auth_bp.route("/registro", methods=["GET", "POST"])
def registro():
    error = ""
    if request.method == "POST":
        nombre      = request.form.get("nombre", "").strip()
        usu         = request.form.get("usuario", "").strip()
        gmail       = request.form.get("gmail", "").strip()
        pwd         = request.form.get("password", "")
        conf        = request.form.get("confirmar", "")
        tipo_cuenta = request.form.get("tipo_cuenta", "invitado")   # 'invitado' | 'miembro'
        codigo      = request.form.get("codigo_verificacion", "").strip()

        if not all([nombre, usu, gmail, pwd, conf]):
            error = "Completa todos los campos"
        elif pwd != conf:
            error = "Las contraseñas no coinciden"
        elif len(pwd) < 8:
            error = "Mínimo 8 caracteres"
        elif tipo_cuenta == "miembro":
            if not codigo:
                error = "Debes ingresar el código de verificación para registrarte como Miembro"
            elif codigo != MEMBER_CODE:
                error = "Código de verificación incorrecto. Contacta al administrador."
            else:
                # Código correcto → registrar como miembro
                rol_final = "miembro"
                error = _crear_usuario(nombre, usu, gmail, pwd, rol_final)
                if not error:
                    return redirect("/")
        else:
            # Invitado → sin validación extra
            error = _crear_usuario(nombre, usu, gmail, pwd, "invitado")
            if not error:
                return redirect("/")

    return render_template("registro.html", error=error)


def _crear_usuario(nombre, usu, gmail, pwd, rol):
    """Inserta el usuario. Devuelve string de error o '' si OK."""
    try:
        con = get_db()
        con.execute(
            "INSERT INTO usuarios(nombre, usuario, password, gmail, rol) "
            "VALUES(%s, %s, %s, %s, %s) ON CONFLICT(usuario) DO NOTHING",
            (nombre, usu, generate_password_hash(pwd), gmail, rol)
        )
        con.commit()
        return ""
    except IntegrityError:
        return "El usuario ya existe"


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect("/")
