from django import forms

from photos.utils import validate_and_compress_image
from stories.models import Story


class StoryUploadForm(forms.ModelForm):
    class Meta:
        model = Story
        fields = ["image"]

    def clean_image(self):
        return validate_and_compress_image(self.cleaned_data.get("image"))
