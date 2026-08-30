import os
import time
import uuid
from io import BytesIO

from django.core.files.uploadedfile import InMemoryUploadedFile
from PIL import Image


def photo_upload_path(instance, filename):
    ext = filename.split(".")[-1]
    filename = f"photo_{uuid.uuid4().hex}_{int(time.time())}.{ext}"
    return os.path.join("photos", str(instance.user.id), filename)


def compress_photo(image_file, quality=85):
    img = Image.open(image_file)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    output = BytesIO()
    img.save(output, format="JPEG", quality=quality, optimize=True)
    output.seek(0)

    filename = image_file.name
    if "." in filename:
        filename = f"{filename.rsplit('.', 1)[0]}.jpg"
    else:
        filename = f"{filename}.jpg"

    return InMemoryUploadedFile(
        output, "ImageField", filename, "image/jpeg", output.getbuffer().nbytes, None
    )
