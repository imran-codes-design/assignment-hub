from django.shortcuts import render, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.http import HttpResponseForbidden
from django.views.decorators.http import require_POST

from .forms import RegisterForm


def home(request):
    if not request.user.is_authenticated:
        return render(request, "accounts/public_home.html")
    if request.user.is_staff:
        return redirect("admin_dashboard")
    if request.user.role == "client":
        return redirect("client_dashboard")
    if request.user.role == "writer":
        return redirect("writer_dashboard")
    return HttpResponseForbidden("Your account role is not supported.")


def register(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)

        if form.is_valid():
            form.save()
            return redirect("login")
    else:
        form = RegisterForm()

    return render(
        request,
        "accounts/register.html",
        {"form": form}
    )


def user_login(request):
    if request.method == "POST":

        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(
            request,
            username=username,
            password=password
        )

        if user is not None:
            login(request, user)
            if user.is_staff:
                return redirect("admin_dashboard")
            if user.role == "client":
                return redirect("client_dashboard")
            if user.role == "writer":
                return redirect("writer_dashboard")
            return redirect("home")

        else:

            return render(
                request,
                "accounts/login.html",
                {
                    "error": "Invalid username or password."
                }
            )

    return render(
        request,
        "accounts/login.html"
    )


@require_POST
def user_logout(request):
    logout(request)
    return redirect("login")


@login_required
def client_dashboard(request):

    if request.user.role != "client":
        if request.user.role == "writer":
            return redirect("writer_dashboard")

        return redirect("home")

    from orders.models import Order, OrderSubmission

    orders = Order.objects.filter(
        client=request.user
    ).prefetch_related(
        Prefetch(
            "submissions",
            queryset=OrderSubmission.objects.order_by(
                "-submitted_at",
                "-pk",
            ),
        )
    ).order_by(
        "-created_at"
    )

    return render(
        request,
        "accounts/client_dashboard.html",
        {
            "orders": orders
        }
    )


@login_required
def writer_dashboard(request):

    if request.user.role != "writer":
        if request.user.role == "client":
            return redirect("client_dashboard")

        return redirect("home")

    return render(
        request,
        "accounts/writer_dashboard.html"
    )


@staff_member_required
def admin_dashboard(request):

    from accounts.models import User
    from orders.models import Order, OrderSubmission

    total_clients = User.objects.filter(
        role="client"
    ).count()

    total_writers = User.objects.filter(
        role="writer"
    ).count()

    total_orders = Order.objects.count()

    pending_orders = Order.objects.filter(
        status="pending"
    ).count()

    assigned_orders = Order.objects.filter(
        status="assigned"
    ).count()

    submitted_orders = Order.objects.filter(
        status="submitted"
    ).count()

    completed_orders = Order.objects.filter(
        status="completed"
    ).count()

    recent_orders = Order.objects.select_related(
        "client",
        "writer"
    ).order_by(
        "-created_at"
    )[:10]

    recent_submissions = OrderSubmission.objects.select_related(
        "order",
        "writer"
    ).order_by(
        "-submitted_at"
    )[:10]

    context = {
        "total_clients": total_clients,
        "total_writers": total_writers,
        "total_orders": total_orders,
        "pending_orders": pending_orders,
        "assigned_orders": assigned_orders,
        "submitted_orders": submitted_orders,
        "completed_orders": completed_orders,
        "recent_orders": recent_orders,
        "recent_submissions": recent_submissions,
    }

    return render(
        request,
        "accounts/admin_dashboard.html",
        context
    )