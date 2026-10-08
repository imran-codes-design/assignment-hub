from django.urls import path

from .views import (
    register,
    user_login,
    user_logout,
    client_dashboard,
    writer_dashboard,
    admin_dashboard,
)


urlpatterns = [

    path(
        "register/",
        register,
        name="register"
    ),

    path(
        "login/",
        user_login,
        name="login"
    ),

    path(
        "logout/",
        user_logout,
        name="logout"
    ),

    path(
        "client/dashboard/",
        client_dashboard,
        name="client_dashboard"
    ),

    path(
        "writer/dashboard/",
        writer_dashboard,
        name="writer_dashboard"
    ),

    path(
    "agency-admin/dashboard/",
    admin_dashboard,
    name="admin_dashboard"
   ),

]