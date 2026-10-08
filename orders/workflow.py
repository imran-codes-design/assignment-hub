from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.contrib.auth import get_user_model

from .models import Order, OrderSubmission, validate_submission_file


def _require_staff(user):
    if not user.is_authenticated or not user.is_staff:
        raise PermissionDenied


def _require_client_or_staff(user, order):
    if not user.is_authenticated:
        raise PermissionDenied
    if user.is_staff:
        return
    if user.role != "client" or order.client_id != user.pk:
        raise PermissionDenied


def assign_writer(actor, order_id, writer):
    _require_staff(actor)
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if order.status not in {"pending", "assigned"}:
            raise ValidationError("Writers can only be assigned to pending or assigned orders.")

        if writer is not None:
            writer = get_user_model().objects.filter(
                pk=writer.pk,
                role="writer",
            ).first()
            if writer is None:
                raise ValidationError("The selected account is not a writer.")

        order.writer = writer
        order.status = "assigned" if writer else "pending"
        order.save(update_fields=["writer", "status", "updated_at"])
    return order


def start_order_work(actor, order_id):
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if not actor.is_authenticated or actor.role != "writer":
            raise PermissionDenied
        if order.writer_id != actor.pk:
            raise PermissionDenied
        if order.status != "assigned":
            raise ValidationError("Only an assigned order can be started.")
        order.status = "in_progress"
        order.save(update_fields=["status", "updated_at"])
    return order


def submit_order_work(actor, order_id, *, file, note=""):
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if not actor.is_authenticated or actor.role != "writer":
            raise PermissionDenied
        if order.writer_id != actor.pk:
            raise PermissionDenied
        if order.status not in {"assigned", "in_progress", "revision"}:
            raise ValidationError(
                "Work can only be submitted for assigned or revision orders."
            )
        if order.submissions.filter(approved=True).exists():
            raise ValidationError("An approved submission cannot be replaced.")
        validate_submission_file(file)

        submission = OrderSubmission.objects.create(
            order=order,
            writer=actor,
            file=file,
            note=note,
        )
        order.status = "submitted"
        order.save(update_fields=["status", "updated_at"])
    return submission


def request_order_revision(actor, order_id):
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        _require_client_or_staff(actor, order)
        if order.status != "submitted":
            raise ValidationError("A revision can only be requested for a submitted order.")
        if order.submissions.filter(approved=True).exists():
            raise ValidationError("A completed order cannot be revised.")
        order.status = "revision"
        order.save(update_fields=["status", "updated_at"])
    return order


def approve_submission(actor, submission_id):
    with transaction.atomic():
        submission = (
            OrderSubmission.objects.select_for_update()
            .select_related("order")
            .get(pk=submission_id)
        )
        order = Order.objects.select_for_update().get(pk=submission.order_id)
        _require_client_or_staff(actor, order)
        if order.status != "submitted":
            raise ValidationError("Only a submitted order can be completed.")

        latest_submission = order.submissions.order_by(
            "-submitted_at",
            "-pk",
        ).first()
        if latest_submission is None or latest_submission.pk != submission.pk:
            raise ValidationError("Only the latest submission can be approved.")
        if order.submissions.filter(approved=True).exclude(pk=submission.pk).exists():
            raise ValidationError("Another submission for this order is already approved.")

        if not submission.approved:
            submission.approved = True
            submission.save(update_fields=["approved"])
        order.status = "completed"
        order.save(update_fields=["status", "updated_at"])
    return submission


def cancel_order(actor, order_id):
    _require_staff(actor)
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if order.status not in {
            "pending",
            "assigned",
            "in_progress",
            "submitted",
            "revision",
        }:
            raise ValidationError("This order cannot be cancelled.")
        if order.submissions.filter(approved=True).exists():
            raise ValidationError("An order with an approved submission cannot be cancelled.")
        order.status = "cancelled"
        order.save(update_fields=["status", "updated_at"])
    return order
