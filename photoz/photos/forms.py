from django import forms

from photos.models import Photo
from photos.utils import validate_and_compress_image


class PhotoUploadForm(forms.ModelForm):
    class Meta:
        model = Photo
        fields = ["image", "caption"]

    def clean_image(self):
        return validate_and_compress_image(self.cleaned_data.get("image"))
