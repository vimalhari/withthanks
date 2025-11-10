import uuid
from django.db import models
from django.contrib.auth.models import User

# Create your models here.
class Charity(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='charity',null=True,blank=True)
    name = models.CharField(max_length=255)
    website = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
    
class VideoTemplate(models.Model):
    id  = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    charity= models.ForeignKey(Charity, on_delete=models.CASCADE, related_name='video_templates')
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    video_file = models.FileField(upload_to='video_templates/')
    overlay_spec_json = models.JSONField(default=dict, blank=True)
    duration_s = models.PositiveIntegerField(default=0, help_text="Optional: video length in seconds")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} . {self.charity.name}"

class TextTemplate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    charity = models.ForeignKey(Charity, on_delete=models.CASCADE, related_name='text_templates')
    name = models.CharField(max_length=255)
    body = models.TextField(
        help_text="Use placeholders like {{donor_name}}, {{donation_amount}}, {{charity}}, {{campaign_name}}"
    )
    locale = models.CharField(max_length=16, default="en")
    voice_id = models.CharField(max_length=128, help_text="ElevenLabs voice id (store for later)")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.charity.name} · {self.name} ({self.locale})"