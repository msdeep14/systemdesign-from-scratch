import os
import time
import uuid
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import InMemoryUploadedFile
from PIL import Image


def photo_upload_path(instance, filename):
    ext = filename.split(".")[-1]
    filename = f"photo_{uuid.uuid4().hex}_{int(time.time())}.{ext}"
    return os.path.join("photos", str(instance.user.id), filename)


def compress_photo(image_file, quality=70):
    img = Image.open(image_file)

    # Convert transparent images (like PNGs) to solid RGB to prevent JPEG conversion crashes
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    # Downscale large images to a maximum width of 1080px using the high-quality LANCZOS filter
    max_width = 1080
    if img.width > max_width:
        ratio = max_width / float(img.width)
        new_height = int(float(img.height) * float(ratio))
        img = img.resize((max_width, new_height), Image.LANCZOS)

    # Save the optimized image to an in-memory RAM buffer instead of the hard drive
    output = BytesIO()
    img.save(output, format="JPEG", quality=quality, optimize=True)
    output.seek(0)  # Rewind the buffer so Django can read it from the beginning

    # Forcefully rename the file extension to .jpg
    filename = image_file.name
    filename = f"{filename.rsplit('.', 1)[0]}.jpg" if "." in filename else f"{filename}.jpg"

    # Wrap the RAM buffer into a Django object so it can flow seamlessly into S3
    return InMemoryUploadedFile(
        output, "ImageField", filename, "image/jpeg", output.getbuffer().nbytes, None
    )


def validate_and_compress_image(image):
    if image:
        if image.size > 2 * 1024 * 1024:
            raise ValidationError("Image file size exceeds 2 MB limit.")
        return compress_photo(image)
    return image
