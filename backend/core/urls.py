"""URLs of the `core` app.

* `/`, `/signin/`, `/signup/`, `/dashboard/`  -> HTML pages of the web interface
* `/api/...`                                 -> JSON API used by that interface
"""

from django.urls import include, path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from . import views

api_urlpatterns = [
    # authentication
    path("signup", views.SignUpView.as_view(), name="signup"),
    path("signin", views.SignInView.as_view(), name="signin"),
    path("signout", views.SignOutView.as_view(), name="signout"),
    path("token", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh", TokenRefreshView.as_view(), name="token_refresh"),
    # meals
    path("recommended", views.RecommendMealView.as_view(), name="recommended"),
    path("ratemeal", views.RateMealView.as_view(), name="ratemeal"),
    path("gethistory", views.GetHistoryView.as_view(), name="gethistory"),
    # profile
    path("userdetails", views.UserDetailsView.as_view(), name="userdetails"),
    path("profiles", views.ProfileListView.as_view(), name="profiles"),
    path("users", views.UsersListView.as_view(), name="users"),
]

urlpatterns = [
    # web interface
    path("", views.index, name="index"),
    path("signin/", views.signin_page, name="signin-page"),
    path("signup/", views.signup_page, name="signup-page"),
    path("dashboard/", views.dashboard_page, name="dashboard"),
    # json api
    path("api/", include((api_urlpatterns, "api"))),
]
