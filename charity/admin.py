from django.contrib import admin

from .models import Campaign, Charity, Donation, Donor, TextTemplate, VideoSendLog, VideoTemplate

# Register your models here.
admin.site.register(Charity)
admin.site.register(VideoTemplate)
admin.site.register(TextTemplate)
admin.site.register(Campaign)
admin.site.register(Donor)
admin.site.register(Donation)
admin.site.register(VideoSendLog)

# @admin.register(VideoTemplate)
# class Cha


# @admin.register(TextTemplate)
# class
