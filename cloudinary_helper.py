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


def subir_a_cloudinary(file_obj, folder="familia"):
    """
    Sube un archivo a Cloudinary. Retorna (url, tipo) o (None, None) si falla.
    tipo: 'imagen' | 'video' | 'pdf'
    """
    if not file_obj or not file_obj.filename:
        return None, None

    ext = file_obj.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_ALL:
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

    try:
        resultado = cloudinary.uploader.upload(
            file_obj,
            folder=folder,
            resource_type=resource_type
        )
        return resultado["secure_url"], tipo
    except Exception as e:
        print(f"Cloudinary upload error: {e}")
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
        public_id = resto.rsplit(".", 1)[0]
        cloudinary.uploader.destroy(public_id)
    except Exception as e:
        print(f"Cloudinary delete error: {e}")
