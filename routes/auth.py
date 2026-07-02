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
            "SELECT id, nombre, usuario, password, rol, COALESCE(es_financiero, FALSE) AS es_financiero FROM usuarios WHERE usuario=%s", (usu,)
        ).fetchone()
        login_ok = False
        if user:
            if check_password_hash(user["password"], pwd):
                login_ok = True
            elif user["password"] == pwd:
                # Cuenta legacy con password en texto plano: aceptar por compatibilidad
                # pero migrar a hash de inmediato para no dejarla expuesta.
                login_ok = True
                con.execute(
                    "UPDATE usuarios SET password=%s WHERE id=%s",
                    (generate_password_hash(pwd), user["id"])
                )
                con.commit()
        if login_ok:
            if user["rol"] == "baneado":
                error = "Tu cuenta ha sido suspendida. Contacta al administrador."
            else:
                session.clear()
                session["uid"]    = user["id"]
                session["nombre"] = user["nombre"]
                session["rol"]    = user["rol"]
                session["es_financiero"] = bool(user.get("es_financiero", False))
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

        # Chequeo explícito: con ON CONFLICT DO NOTHING más abajo, un choque de
        # nombre de usuario NO lanza IntegrityError, así que hay que detectarlo aquí.
        existente = con.execute(
            "SELECT id FROM usuarios WHERE usuario=%s", (usu,)
        ).fetchone()
        if existente:
            return "El usuario ya existe"

        con.execute(
            "INSERT INTO usuarios(nombre, usuario, password, gmail, rol, es_nuevo) "
            "VALUES(%s, %s, %s, %s, %s, TRUE) ON CONFLICT(usuario) DO NOTHING",
            (nombre, usu, generate_password_hash(pwd), gmail, rol)
        )
        con.commit()

        # Recuperar el nuevo usuario para publicar bienvenida
        nuevo = con.execute(
            "SELECT id FROM usuarios WHERE usuario=%s", (usu,)
        ).fetchone()
        if nuevo:
            _post_bienvenida(nombre, nuevo["id"], con)

        return ""
    except IntegrityError:
        return "El usuario ya existe"


def _post_bienvenida(nombre, nuevo_uid, con):
    """
    Publica un post automático de bienvenida en nombre del sistema.
    Usa el usuario admin (id=1) o el primer admin disponible como autor.
    Se ejecuta solo una vez al registrarse.
    """
    import random

    # Buscar al admin para publicar como él
    admin = con.execute(
        "SELECT id FROM usuarios WHERE rol='admin' ORDER BY id LIMIT 1"
    ).fetchone()
    if not admin:
        return  # Si no hay admin todavía, no publicamos

    admin_id = admin["id"]

    saludos = [
        f"🎉 ¡Bienvenido a la familia, {nombre}! 🏡\n\nEstamos muy felices de que hayas llegado. Este es tu espacio para compartir momentos, conectar con los que más quieres y ser parte de algo especial. ¡Que disfrutes mucho! 💛✨",
        f"👋 ¡Hola, {nombre}! ¡Ya eres parte de nuestra familia! 🎊\n\nQué alegría tenerte aquí. Este es un lugar lleno de amor, risas y recuerdos. ¡Bienvenido al grupo! 🤝❤️",
        f"🌟 ¡{nombre} acaba de unirse a la familia! 🥳\n\nCuenta con todos nosotros — este es tu hogar digital. ¡Bienvenido con todo el amor del mundo! 💙🎉",
        f"🫶 ¡Ya somos uno más! ¡Bienvenido, {nombre}! 🎈\n\nAquí encontrarás recuerdos, risas y mucho amor familiar. Nos alegra tenerte. ¡Explora, comparte y disfruta! ✨💛",
        f"🎊 ¡{nombre} llegó a la familia! ¡Bienvenido! 🌈\n\nQue este sea el inicio de muchos momentos compartidos. ¡Estamos felices de tenerte! 💪❤️",
    ]

    texto_bienvenida = random.choice(saludos)

    try:
        con.execute(
            "INSERT INTO publicaciones(usuario_id, texto, media, media_tipo) "
            "VALUES(%s, %s, '', '')",
            (admin_id, texto_bienvenida)
        )
        # Marcar al usuario como ya bienvenido para no repetir
        con.execute(
            "UPDATE usuarios SET es_nuevo=FALSE WHERE id=%s",
            (nuevo_uid,)
        )
        con.commit()
    except Exception as e:
        print(f"[Bienvenida] Error publicando post: {e}")


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect("/")
