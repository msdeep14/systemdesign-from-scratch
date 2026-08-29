from django import forms

from photos.models import Photo
from photos.utils import compress_photo


class PhotoUploadForm(forms.ModelForm):
    class Meta:
        model = Photo
        fields = ["image", "caption"]

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image:
            if image.size > 2 * 1024 * 1024:
                raise forms.ValidationError("Image file size exceeds 2 MB limit.")
            return compress_photo(image)
        return image
