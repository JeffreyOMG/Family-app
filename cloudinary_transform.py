"""
cloudinary_transform.py
=======================
Utilidad para insertar parámetros de transformación en URLs de Cloudinary.

Antes (sin optimización):
  https://res.cloudinary.com/cloud/image/upload/v123/familia/perfiles/foto.jpg
  → Sirve el original tal como fue subido (puede ser 5-15 MB de una foto de celular)

Después (con optimización):
  https://res.cloudinary.com/cloud/image/upload/w_80,h_80,c_fill,f_auto,q_auto/v123/familia/perfiles/foto.jpg
  → Cloudinary redimensiona, convierte a WebP/AVIF y comprime automáticamente (~5-20 KB)

Ahorro estimado: 95-99% de bandwidth por imagen.
"""

# ── Presets de transformación ──────────────────────────────────────────────────
PRESETS: dict[str, str] = {
    # Avatares pequeños (navbar, chips, comentarios, ranking)
    "avatar":       "w_80,h_80,c_fill,f_auto,q_auto",
    # Avatares medianos (post header, listas de miembros)
    "avatar_md":    "w_120,h_120,c_fill,f_auto,q_auto",
    # Foto de perfil grande (perfil propio / ver perfil usuario)
    "avatar_lg":    "w_300,h_300,c_fill,f_auto,q_auto",
    # Portada de perfil
    "cover":        "w_900,h_300,c_fill,f_auto,q_auto",
    # Imagen en el feed (post media)
    "feed":         "w_800,f_auto,q_auto",
    # Miniatura en galería (grid 3 columnas)
    "gallery":      "w_400,h_400,c_fill,f_auto,q_auto",
    # Miniatura de comprobante/soporte (36×36 px en tabla)
    "comp_thumb":   "w_72,h_72,c_fill,f_auto,q_auto",
    # Vista completa de comprobante en modal (max 1000px ancho)
    "comp_full":    "w_1000,f_auto,q_auto",
    # Imagen de opción de encuesta
    "poll_opt":     "w_300,h_200,c_fill,f_auto,q_auto",
    # Carrusel de múltiples fotos en un post
    "carousel":     "w_800,f_auto,q_auto",
    # Al menos comprimir formato (sin redimensionar), para casos especiales
    "compress":     "f_auto,q_auto",
}


def cl_url(url: str | None, preset: str = "feed") -> str:
    """
    Inserta transformaciones de Cloudinary en una URL de imagen.

    - Solo actúa sobre URLs de tipo `image/upload`.
    - No modifica videos ni PDFs.
    - Si ya contiene transformaciones, no las duplica.
    - Si la URL no es de Cloudinary, la devuelve intacta.

    Uso en Jinja2:
        {{ p.foto | cl_url('avatar') }}
        {{ p.media | cl_url('feed') }}
    """
    if not url or "cloudinary.com" not in url:
        return url or ""

    # Solo imágenes — no tocar video/upload ni raw/upload
    if "image/upload" not in url:
        return url

    transform = PRESETS.get(preset, PRESETS["feed"])

    # Evitar doble transformación (la URL ya tiene parámetros insertados)
    marker = transform.split(",")[0]  # e.g. "w_80"
    if f"/upload/{marker}" in url or f"/{marker}," in url:
        return url

    return url.replace("/image/upload/", f"/image/upload/{transform}/", 1)


def cl_video(url: str | None, preset: str = "feed") -> str:
    """
    Igual que cl_url pero para URLs de video (resource_type='video').

    Uso en Jinja2:
        {{ p.media | cl_video('feed') }}
    """
    if not url or "cloudinary.com" not in url:
        return url or ""

    # Solo videos — no tocar image/upload ni raw/upload
    if "video/upload" not in url:
        return url

    transform = PRESETS.get(preset, PRESETS["feed"])

    marker = transform.split(",")[0]  # e.g. "w_800"
    if f"/upload/{marker}" in url or f"/{marker}," in url:
        return url

    return url.replace("/video/upload/", f"/video/upload/{transform}/", 1)


def cl_poster(url: str | None) -> str:
    """
    Genera la URL de la miniatura (poster) de un video: toma el primer
    frame y lo sirve como imagen jpg optimizada. Cloudinary genera esta
    imagen "al vuelo" a partir del mismo video subido, sin necesidad de
    subir un archivo aparte.

    Uso en Jinja2:
        <video poster="{{ p.media | cl_poster }}">...</video>
    """
    if not url or "cloudinary.com" not in url or "video/upload" not in url:
        return url or ""

    # Insertar: tomar el frame en el segundo 0, optimizar formato/calidad
    poster_url = url.replace("/video/upload/", "/video/upload/so_0,f_auto,q_auto/", 1)

    # Cambiar la extensión del archivo (mp4, mov, etc.) a jpg
    base, _, _ext = poster_url.rpartition(".")
    if base:
        poster_url = f"{base}.jpg"

    return poster_url


def cl_url_js_presets() -> str:
    """
    Devuelve los presets como un literal JS para inyectar en templates.
    Usado por el helper clUrl() en JavaScript.
    """
    lines = [f'"{k}":"{v}"' for k, v in PRESETS.items()]
    return "{" + ",".join(lines) + "}"
