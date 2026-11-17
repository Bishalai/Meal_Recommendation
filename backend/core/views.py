"""
Views of the `core` app.

Two kinds of endpoints live here:

* page views  -> render the HTML of the web interface (`/`, `/signin/`, ...)
* API views   -> JSON endpoints mounted under `/api/` (authentication,
                 recommendations, ratings, history, profile).

Authentication for the API is JWT: clients send
`Authorization: Bearer <access token>` after a successful `/api/signin`.
"""

import logging

import pandas as pd
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.shortcuts import render
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import UserProfile
from .recommendation import (
    calculate_user_macronutrients,
    give_rating,
    load_data_to_csv,
    load_req_data,
    recommendmeal_detailed,
    user_dataframe,
    write_data_to_csv,
)
from .serializers import ProfileSerializer, UserSerializer

logger = logging.getLogger(__name__)

MEAL_TIMES = ("breakfast", "lunch", "dinner")

# fields every new account must provide
SIGNUP_FIELDS = (
    "username", "password1", "password2",
    "age", "weight", "height", "sex", "lifestyle",
    "tags", "diet", "disease", "allergy",
)

# profile fields that can be updated later from the profile page
PROFILE_FIELDS = ("age", "weight", "height", "sex", "lifestyle", "tags",
                  "diet", "disease", "allergy")


# ---------------------------------------------------------------------------
# Web pages (the graphical interface)
# ---------------------------------------------------------------------------
def index(request):
    return render(request, "core/index.html")


def signin_page(request):
    return render(request, "core/signin.html")


def signup_page(request):
    return render(request, "core/signup.html")


def dashboard_page(request):
    return render(request, "core/dashboard.html")


# ---------------------------------------------------------------------------
# Authentication API
# ---------------------------------------------------------------------------
class SignUpView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        missing = [field for field in SIGNUP_FIELDS if field not in data]
        if missing:
            return Response(
                {"error": f"missing fields: {', '.join(missing)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if data["password1"] != data["password2"]:
            return Response({"error": "passwords do not match"},
                            status=status.HTTP_400_BAD_REQUEST)

        username = str(data["username"]).strip()
        if not username:
            return Response({"error": "username is required"},
                            status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(username=username).exists():
            return Response({"error": "username already exists"},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.create_user(
                username=username,
                email=data.get("email", ""),
                password=data["password1"],
            )
            UserProfile.objects.create(
                user=user,
                age=data["age"],
                weight=data["weight"],
                height=data["height"],
                sex=data["sex"],
                lifestyle=data["lifestyle"],
                tags=data["tags"],
                diet=data["diet"],
                disease=data["disease"],
                allergy=data["allergy"],
            )
            # the recommendation engine reads the CSV files, so keep them in sync
            load_data_to_csv("user_info.csv", _signup_row(username, data))
        except (TypeError, ValueError) as exc:
            logger.exception("signup failed for %s", username)
            User.objects.filter(username=username).delete()
            return Response({"error": f"invalid signup data: {exc}"},
                            status=status.HTTP_400_BAD_REQUEST)

        return Response({"message": "user created"}, status=status.HTTP_201_CREATED)


def _signup_row(username, data):
    return user_dataframe(
        username=username,
        name=username,
        age=data["age"],
        weight=data["weight"],
        height=data["height"],
        sex=data["sex"],
        lifestyle=data["lifestyle"],
        tags=data["tags"],
        diet=data["diet"],
        disease=data["disease"],
        allergy=data["allergy"],
    )


class SignInView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")
        if not username or not password:
            return Response({"error": "username and password are required"},
                            status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(username=username, password=password)
        if user is None:
            return Response({"error": "invalid credentials"},
                            status=status.HTTP_401_UNAUTHORIZED)

        refresh = RefreshToken.for_user(user)
        return Response({
            "message": "logged in successfully",
            "username": user.username,
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        })


class SignOutView(APIView):
    """JWT tokens are stateless: the client simply deletes them."""

    def post(self, request):
        return Response({"message": "logged out"})


# ---------------------------------------------------------------------------
# Recommendation API
# ---------------------------------------------------------------------------
class RecommendMealView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        meal_time = request.data.get("time")
        if meal_time not in MEAL_TIMES:
            return Response(
                {"error": f"'time' must be one of {', '.join(MEAL_TIMES)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        username = request.user.username
        try:
            result = recommendmeal_detailed(time=meal_time, username=username)
            macros = calculate_user_macronutrients(username)
        except LookupError:
            return Response(
                {"error": "no dish left for this time of day - rate fewer meals "
                          "or add more dishes to the catalogue"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except ValueError as exc:
            # unknown user or a profile missing weight / height / age
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            logger.exception("recommendation failed for %s", username)
            return Response({"error": "could not build a recommendation"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            "user": username,
            "time": meal_time,
            "recommendation method": result["method"],
            "nutrition format": "energy(kcal), carbohydrate(gm), fats(gm), protein(gm)",
            "recommended calories": macros[0],
            "recommended carbohydrates(gm) min": macros[1],
            "recommended carbohydrates(gm) max": macros[2],
            "recommended fats(gm) min": macros[3],
            "recommended fats(gm) max": macros[4],
            "recommended protein(gm) min": macros[5],
            "recommended protein(gm) max": macros[6],
            "food": result["food"],
        })


class RateMealView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            rating = int(request.data.get("rating"))
            meal_time = request.data.get("time")
            food = request.data.get("food")
        except (TypeError, ValueError):
            return Response({"error": "'rating' must be a number"},
                            status=status.HTTP_400_BAD_REQUEST)

        if not 1 <= rating <= 5:
            return Response({"error": "'rating' must be between 1 and 5"},
                            status=status.HTTP_400_BAD_REQUEST)
        if meal_time not in MEAL_TIMES:
            return Response({"error": f"'time' must be one of {', '.join(MEAL_TIMES)}"},
                            status=status.HTTP_400_BAD_REQUEST)
        if not food:
            return Response({"error": "'food' is required"},
                            status=status.HTTP_400_BAD_REQUEST)

        give_rating(rec_food=food, username=request.user.username,
                    time=meal_time, rating=rating)
        return Response({"food": food, "rating": rating, "time": meal_time})


class GetHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        username = request.user.username
        history = load_req_data("user_data.csv")
        records = history[history["username"] == username].to_dict("records")
        return Response({"user": username, "history": records})


# ---------------------------------------------------------------------------
# Profile API
# ---------------------------------------------------------------------------
class UserDetailsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = self._profile(request)
        return Response(ProfileSerializer(profile).data)

    def put(self, request):
        profile = self._profile(request)
        data = request.data
        try:
            for field in PROFILE_FIELDS:
                if field in data:
                    setattr(profile, field, data[field])
            profile.save()
        except (TypeError, ValueError) as exc:
            return Response({"error": f"invalid profile data: {exc}"},
                            status=status.HTTP_400_BAD_REQUEST)

        # keep the CSV copy of the profile in sync with the database
        user_rows = load_req_data("user_info.csv")
        user_rows = user_rows[user_rows["username"] != request.user.username]
        updated = user_dataframe(
            username=request.user.username,
            name=request.user.username,
            age=profile.age,
            weight=profile.weight,
            height=profile.height,
            sex=profile.sex,
            lifestyle=profile.lifestyle,
            tags=profile.tags,
            diet=profile.diet,
            disease=profile.disease,
            allergy=profile.allergy,
        )
        write_data_to_csv("user_info.csv", pd.concat([user_rows, updated],
                                                     ignore_index=True))
        return Response(ProfileSerializer(profile).data)

    def delete(self, request):
        user = request.user
        # remove the CSV row first, then the database records
        user_rows = load_req_data("user_info.csv")
        write_data_to_csv("user_info.csv",
                          user_rows[user_rows["username"] != user.username])
        user.delete()  # cascade also removes the profile
        return Response({"message": "deleted"})

    @staticmethod
    def _profile(request):
        try:
            return UserProfile.objects.get(user=request.user)
        except UserProfile.DoesNotExist:
            raise NotFound(detail="profile not found")


class ProfileListView(APIView):
    """All profiles - useful for the admin / debugging."""

    def get(self, request):
        serializer = ProfileSerializer(UserProfile.objects.all(), many=True)
        return Response(serializer.data)


class UsersListView(APIView):
    """All users - useful for the admin / debugging."""

    def get(self, request):
        serializer = UserSerializer(User.objects.all(), many=True)
        return Response(serializer.data)
