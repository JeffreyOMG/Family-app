import os
import cloudinary
import cloudinary.uploader

cloudinary.config(
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key    = os.getenv("CLOUDINARY_API_KEY"),
    api_secret = os.getenv("CLOUDINARY_API_SECRET"),
    secure     = True
)

ALLOWED_IMAGES = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_VIDEOS = {"mp4", "mov", "avi", "webm"}
ALLOWED_DOCS   = {"pdf"}
ALLOWED_ALL    = ALLOWED_IMAGES | ALLOWED_VIDEOS | ALLOWED_DOCS

# ── Transformaciones "eager": se pre-generan al subir ──────────────────────────
# Cloudinary las cachea en CDN inmediatamente, evitando el "first-hit" penalty.
# Solo aplica a imágenes (resource_type='image').
EAGER_TRANSFORMS_PERFILES = [
    {"width": 80,  "height": 80,  "crop": "fill", "fetch_format": "auto", "quality": "auto"},  # avatar
    {"width": 120, "height": 120, "crop": "fill", "fetch_format": "auto", "quality": "auto"},  # avatar_md
    {"width": 300, "height": 300, "crop": "fill", "fetch_format": "auto", "quality": "auto"},  # avatar_lg
]
EAGER_TRANSFORMS_PORTADAS = [
    {"width": 900, "height": 300, "crop": "fill", "fetch_format": "auto", "quality": "auto"},  # cover
]
EAGER_TRANSFORMS_POSTS = [
    {"width": 800, "fetch_format": "auto", "quality": "auto"},  # feed
]
EAGER_TRANSFORMS_GALERIA = [
    {"width": 400, "height": 400, "crop": "fill", "fetch_format": "auto", "quality": "auto"},  # gallery
    {"width": 800, "fetch_format": "auto", "quality": "auto"},  # feed/full
]
EAGER_TRANSFORMS_FINANZAS = [
    {"width": 72,  "height": 72,  "crop": "fill", "fetch_format": "auto", "quality": "auto"},  # comp_thumb
    {"width": 1000, "fetch_format": "auto", "quality": "auto"},                                 # comp_full
]

# Mapa folder → eager transforms
_EAGER_MAP = {
    "familia/perfiles": EAGER_TRANSFORMS_PERFILES,
    "familia/portadas": EAGER_TRANSFORMS_PORTADAS,
    "familia/posts":    EAGER_TRANSFORMS_POSTS,
    "familia/polls":    EAGER_TRANSFORMS_POSTS,
    "familia/galeria":  EAGER_TRANSFORMS_GALERIA,
    "familia/finanzas": EAGER_TRANSFORMS_FINANZAS,
}


def subir_a_cloudinary(file_obj, folder="familia"):
    """
    Sube un archivo a Cloudinary con transformaciones eager pre-generadas.
    Retorna (url, tipo) o (None, None) si falla.
    tipo: 'imagen' | 'video' | 'pdf'
    """
    if not file_obj or not file_obj.filename:
        return None, None

    ext = file_obj.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_ALL:
        print(f"[Cloudinary] Extensión no permitida: {ext}")
        return None, None

    if ext in ALLOWED_VIDEOS:
        resource_type = "video"
        tipo = "video"
    elif ext in ALLOWED_DOCS:
        resource_type = "raw"
        tipo = "pdf"
    else:
        resource_type = "image"
        tipo = "imagen"

    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key    = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")
    if not cloud_name or not api_key or not api_secret:
        print("[Cloudinary] ERROR: Variables de entorno no configuradas "
              "(CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET)")
        return None, None

    # Solo aplicar eager a imágenes (los videos/PDFs no usan transformaciones de imagen)
    eager = _EAGER_MAP.get(folder, []) if resource_type == "image" else []

    try:
        upload_opts = {
            "folder":        folder,
            "resource_type": resource_type,
        }
        if eager:
            upload_opts["eager"] = eager
            upload_opts["eager_async"] = True   # no bloquea la respuesta

        resultado = cloudinary.uploader.upload(file_obj, **upload_opts)
        url = resultado.get("secure_url")
        if not url:
            print(f"[Cloudinary] Upload sin secure_url. Respuesta: {resultado}")
            return None, None
        print(f"[Cloudinary] ✓ Subido a {folder}: {url} (eager={len(eager)} transforms)")
        return url, tipo
    except Exception as e:
        print(f"[Cloudinary] Upload error (folder={folder}): {e}")
        return None, None


def eliminar_de_cloudinary(url):
    """Elimina un archivo de Cloudinary dado su URL segura."""
    if not url or "cloudinary.com" not in url:
        return
    try:
        partes = url.split("/upload/")
        if len(partes) < 2:
            return
        resto = partes[1]
        # Quitar versión (v1234567890/)
        if resto.startswith("v") and "/" in resto:
            resto = resto.split("/", 1)[1]
        # Quitar posibles transformaciones si se guardó URL transformada
        if not resto.startswith("familia/"):
            # Tiene transformaciones en la URL, saltarlas hasta el public_id
            partes2 = resto.split("/familia/")
            if len(partes2) >= 2:
                resto = "familia/" + partes2[-1]
        public_id = resto.rsplit(".", 1)[0]
        cloudinary.uploader.destroy(public_id)
        print(f"[Cloudinary] ✓ Eliminado: {public_id}")
    except Exception as e:
        print(f"[Cloudinary] Delete error: {e}")
