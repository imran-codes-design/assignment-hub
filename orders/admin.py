from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils.html import format_html
from .models import Order, OrderSubmission
from .workflow import (
    approve_submission,
    cancel_order,
    request_order_revision,
)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    readonly_fields = ("status", "writer")
    actions = ("request_revisions", "cancel_orders")

    list_display = (
        "title",
        "client",
        "writer",
        "subject",
        "deadline",
        "budget",
        "status",
        "created_at",
    )

    list_filter = (
        "status",
        "academic_level",
        "subject",
    )

    search_fields = (
        "title",
        "subject",
        "client__username",
        "writer__username",
    )

    @admin.action(description="Request revisions for selected submitted orders")
    def request_revisions(self, request, queryset):
        self._apply_transition(request, queryset, request_order_revision)

    @admin.action(description="Cancel selected cancellable orders")
    def cancel_orders(self, request, queryset):
        self._apply_transition(request, queryset, cancel_order)

    def _apply_transition(self, request, queryset, transition):
        succeeded = 0
        for order in queryset:
            try:
                transition(request.user, order.pk)
            except ValidationError as exc:
                self.message_user(
                    request,
                    f"Order #{order.pk}: {exc.messages[0]}",
                    level=messages.ERROR,
                )
            else:
                succeeded += 1
        if succeeded:
            self.message_user(
                request,
                f"Updated {succeeded} order(s).",
                level=messages.SUCCESS,
            )


@admin.register(OrderSubmission)
class OrderSubmissionAdmin(admin.ModelAdmin):
    fields = (
        "order",
        "writer",
        "protected_file_link",
        "note",
        "approved",
        "submitted_at",
    )
    readonly_fields = fields
    actions = ("approve_submissions",)

    list_display = (
        "order",
        "writer",
        "protected_file_link",
        "approved",
        "submitted_at",
    )

    list_filter = (
        "approved",
        "submitted_at",
    )

    search_fields = (
        "order__title",
        "writer__username",
    )

    @admin.display(description="Protected download")
    def protected_file_link(self, obj):
        if not obj.pk or not obj.file:
            return "-"
        return format_html(
            '<a href="{}">Download submission</a>',
            reverse("download_submission", args=[obj.pk]),
        )

    @admin.action(description="Approve selected latest submissions")
    def approve_submissions(self, request, queryset):
        succeeded = 0
        for submission in queryset:
            try:
                approve_submission(request.user, submission.pk)
            except ValidationError as exc:
                self.message_user(
                    request,
                    f"Submission #{submission.pk}: {exc.messages[0]}",
                    level=messages.ERROR,
                )
            else:
                succeeded += 1
        if succeeded:
            self.message_user(
                request,
                f"Approved {succeeded} submission(s).",
                level=messages.SUCCESS,
            )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False