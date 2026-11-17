from django.contrib.auth.models import User
from django.db import models


class UserProfile(models.Model):
    """Health / taste profile of a user, used by the recommendation engine."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)
    height = models.FloatField(null=True, help_text="cm")
    weight = models.FloatField(null=True, help_text="kg")
    age = models.IntegerField(null=True)
    sex = models.CharField(max_length=10, null=True)
    lifestyle = models.CharField(max_length=20, null=True)
    tags = models.TextField(max_length=200, null=True, help_text="comma separated food preferences")
    diet = models.CharField(max_length=20, null=True)
    disease = models.CharField(max_length=100, null=True, help_text="comma separated diseases")
    allergy = models.CharField(max_length=100, null=True, help_text="comma separated ingredients")

    class Meta:
        verbose_name = "user profile"

    def __str__(self):
        return self.user.username if self.user else "anonymous"
