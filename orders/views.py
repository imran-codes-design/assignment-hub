from pathlib import Path

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, HttpResponseNotAllowed
from django.shortcuts import render, redirect, get_object_or_404

from .forms import OrderForm, AssignWriterForm, SubmissionForm
from .models import Order, OrderSubmission
from .workflow import (
    approve_submission,
    assign_writer as assign_order_writer,
    cancel_order,
    request_order_revision,
    start_order_work,
    submit_order_work,
)


@login_required
def create_order(request):

    if request.user.role != "client":
        if request.user.role == "writer":
            return redirect("writer_dashboard")

        return redirect("home")

    if request.method == "POST":

        form = OrderForm(request.POST)

        if form.is_valid():

            order = form.save(commit=False)
            order.client = request.user
            order.save()

            return redirect("client_dashboard")

    else:

        form = OrderForm()

    return render(
        request,
        "orders/create_order.html",
        {"form": form}
    )


@login_required
def writer_orders(request):

    if request.user.role != "writer":

        if request.user.role == "client":
            return redirect("client_dashboard")

        return redirect("home")

    orders = Order.objects.filter(
        writer=request.user
    ).order_by("deadline")

    return render(
        request,
        "orders/writer_orders.html",
        {"orders": orders}
    )


@login_required
def writer_order_detail(request, order_id):

    if request.user.role != "writer":

        if request.user.role == "client":
            return redirect("client_dashboard")

        return redirect("home")

    order = get_object_or_404(
        Order,
        id=order_id,
        writer=request.user
    )

    if request.method == "POST" and request.POST.get("action") == "start":
        try:
            start_order_work(request.user, order.id)
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
        else:
            return redirect("writer_order_detail", order_id=order.id)

    form = SubmissionForm(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
    )
    if request.method == "POST" and request.POST.get("action") == "submit":
        if form.is_valid():
            try:
                submit_order_work(
                    request.user,
                    order.id,
                    file=form.cleaned_data["file"],
                    note=form.cleaned_data["note"],
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                return redirect(
                    "writer_order_detail",
                    order_id=order.id,
                )

    return render(
        request,
        "orders/writer_order_detail.html",
        {"order": order, "form": form},
    )


@login_required
def download_submission(request, submission_id):
    submission = get_object_or_404(
        OrderSubmission.objects.select_related("order", "order__client"),
        pk=submission_id,
    )
    user = request.user

    if user.is_staff:
        pass
    elif user.role == "client":
        if (
            submission.order.client_id != user.pk
            or not submission.approved
        ):
            raise Http404
    elif user.role == "writer":
        if submission.order.writer_id != user.pk:
            raise Http404
    else:
        raise Http404

    try:
        file_handle = submission.file.open("rb")
    except FileNotFoundError as exc:
        raise Http404 from exc

    filename = Path(submission.file.name).name
    return FileResponse(
        file_handle,
        as_attachment=True,
        filename=filename,
        content_type="application/octet-stream",
    )


@staff_member_required
def assign_writer(request, order_id):

    order = get_object_or_404(
        Order,
        id=order_id
    )

    if request.method == "POST":

        form = AssignWriterForm(
            request.POST,
            instance=order
        )

        if form.is_valid():
            try:
                assign_order_writer(
                    request.user,
                    order.id,
                    form.cleaned_data["writer"],
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                return redirect("admin_dashboard")

    else:

        form = AssignWriterForm(
            instance=order
        )

    return render(
        request,
        "orders/assign_writer.html",
        {
            "order": order,
            "form": form,
        }
    )


@login_required
def client_order_action(request, order_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    order = get_object_or_404(Order, pk=order_id)
    action = request.POST.get("action")
    try:
        if action == "approve":
            submission = order.submissions.order_by(
                "-submitted_at",
                "-pk",
            ).first()
            if submission is None:
                raise ValidationError("There is no submission to approve.")
            approve_submission(request.user, submission.pk)
        elif action == "revision":
            request_order_revision(request.user, order.id)
        else:
            raise Http404
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    return redirect("client_dashboard")


@staff_member_required
def staff_order_action(request, order_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    order = get_object_or_404(Order, pk=order_id)
    action = request.POST.get("action")
    try:
        if action == "revision":
            request_order_revision(request.user, order.id)
        elif action == "cancel":
            cancel_order(request.user, order.id)
        else:
            raise Http404
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    return redirect("admin_dashboard")