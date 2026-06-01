from flask import Blueprint, render_template, request, redirect, session
from werkzeug.security import generate_password_hash, check_password_hash
from pg8000.exceptions import DatabaseError as IntegrityError
from database import get_db

auth_bp = Blueprint("auth", __name__)

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
            session.clear()
            session["uid"]    = user["id"]
            session["nombre"] = user["nombre"]
            session["rol"]    = user["rol"]
            return redirect("/dashboard")
        error = "Usuario o contraseña incorrectos"
    return render_template("login.html", error=error)

@auth_bp.route("/registro", methods=["GET", "POST"])
def registro():
    error = ""
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        usu    = request.form.get("usuario", "").strip()
        gmail  = request.form.get("gmail", "").strip()
        pwd    = request.form.get("password", "")
        conf   = request.form.get("confirmar", "")
        if not all([nombre, usu, gmail, pwd, conf]):
            error = "Completa todos los campos"
        elif pwd != conf:
            error = "Las contraseñas no coinciden"
        elif len(pwd) < 8:
            error = "Mínimo 8 caracteres"
        else:
            try:
                con = get_db()
                con.execute(
                    "INSERT INTO usuarios(nombre, usuario, password, gmail) VALUES(%s, %s, %s, %s) ON CONFLICT(usuario) DO NOTHING",
                    (nombre, usu, generate_password_hash(pwd), gmail)
                )
                con.commit()
                return redirect("/")
            except IntegrityError:
                error = "El usuario ya existe"
    return render_template("registro.html", error=error)

@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect("/")
