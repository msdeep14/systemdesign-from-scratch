from django import forms
from django.contrib.auth.models import User
from .models import UserProfile

class UserRegistrationForm(forms.Form):
    username_display = forms.CharField(max_length=50, required=True, label="Username")
    first_name = forms.CharField(max_length=100, required=True, label="First Name")
    last_name = forms.CharField(max_length=100, required=False, label="Last Name")
    password = forms.CharField(widget=forms.PasswordInput(), required=True)
    password_confirm = forms.CharField(widget=forms.PasswordInput(), required=True, label="Confirm Password")

    def clean_username_display(self):
        username = self.cleaned_data.get('username_display')
        if UserProfile.objects.filter(username_display__iexact=username).exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")

        if password and password_confirm and password != password_confirm:
            raise forms.ValidationError("Passwords do not match.")
        
        return cleaned_data

class UserProfileEditForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['first_name', 'last_name', 'profile_picture', 'interests', 'bio']
