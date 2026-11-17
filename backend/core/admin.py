from django.contrib import admin

from .models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "age", "sex", "diet", "lifestyle")
    search_fields = ("user__username", "diet", "disease", "allergy")
