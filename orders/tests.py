from io import BytesIO
from datetime import timedelta
from tempfile import TemporaryDirectory
from zipfile import ZIP_STORED, ZipFile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.auth.models import AnonymousUser
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from .forms import OrderForm, SubmissionForm
from .models import MAX_SUBMISSION_FILE_SIZE, Order, OrderSubmission
from .workflow import (
    approve_submission,
    assign_writer,
    cancel_order,
    request_order_revision,
    start_order_work,
    submit_order_work,
)


PDF_CONTENT = b"%PDF-1.4\nAssignment submission\n%%EOF\n"


class SubmissionFileSecurityTests(TestCase):
    def setUp(self):
        self.media_directory = TemporaryDirectory()
        self.settings_override = override_settings(
            MEDIA_ROOT=self.media_directory.name
        )
        self.settings_override.enable()

        self.client_user = User.objects.create_user(
            username="client",
            password="test-password",
            role="client",
        )
        self.other_client = User.objects.create_user(
            username="other-client",
            password="test-password",
            role="client",
        )
        self.writer = User.objects.create_user(
            username="writer",
            password="test-password",
            role="writer",
        )
        self.other_writer = User.objects.create_user(
            username="other-writer",
            password="test-password",
            role="writer",
        )
        self.order = self.create_order(self.client_user, self.writer)
        self.other_order = self.create_order(
            self.other_client,
            self.other_writer,
        )

    def tearDown(self):
        self.settings_override.disable()
        self.media_directory.cleanup()

    def create_order(self, client, writer):
        return Order.objects.create(
            client=client,
            writer=writer,
            title="Assignment",
            subject="English",
            description="Write an assignment.",
            academic_level="College",
            deadline=timezone.now() + timedelta(days=2),
            budget="100.00",
            status="assigned",
        )

    def create_submission(self, order, writer, approved=False):
        return OrderSubmission.objects.create(
            order=order,
            writer=writer,
            file=SimpleUploadedFile(
                "assignment.pdf",
                PDF_CONTENT,
                content_type="application/pdf",
            ),
            approved=approved,
        )

    def upload_url(self, order):
        return reverse("writer_order_detail", args=[order.pk])

    def download_url(self, submission):
        return reverse("download_submission", args=[submission.pk])

    def test_valid_pdf_upload_is_saved(self):
        self.client.force_login(self.writer)

        response = self.client.post(
            self.upload_url(self.order),
            {
                "action": "submit",
                "file": SimpleUploadedFile(
                    "assignment.pdf",
                    PDF_CONTENT,
                    content_type="application/pdf",
                ),
                "note": "Completed assignment",
            },
        )

        self.assertRedirects(response, self.upload_url(self.order))
        submission = OrderSubmission.objects.get(order=self.order)
        self.assertEqual(submission.writer, self.writer)
        self.assertEqual(submission.note, "Completed assignment")
        self.assertEqual(
            Order.objects.get(pk=self.order.pk).status,
            "submitted",
        )
        with submission.file.open("rb") as uploaded:
            self.assertEqual(uploaded.read(), PDF_CONTENT)

    def test_invalid_file_content_is_rejected_even_with_pdf_extension(self):
        self.client.force_login(self.writer)

        response = self.client.post(
            self.upload_url(self.order),
            {
                "action": "submit",
                "file": SimpleUploadedFile(
                    "not-a-pdf.pdf",
                    b"<html>not a PDF</html>",
                    content_type="application/pdf",
                ),
                "note": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertFalse(OrderSubmission.objects.exists())

    def test_all_supported_document_formats_are_accepted(self):
        docx_buffer = BytesIO()
        with ZipFile(docx_buffer, "w", ZIP_STORED) as document:
            document.writestr("[Content_Types].xml", "<Types/>")
            document.writestr("word/document.xml", "<document/>")

        odt_buffer = BytesIO()
        with ZipFile(odt_buffer, "w", ZIP_STORED) as document:
            document.writestr(
                "mimetype",
                b"application/vnd.oasis.opendocument.text",
            )

        examples = (
            ("assignment.pdf", PDF_CONTENT),
            ("assignment.docx", docx_buffer.getvalue()),
            ("assignment.odt", odt_buffer.getvalue()),
            ("assignment.rtf", b"{\\rtf1 Assignment}"),
            ("assignment.txt", "Plain text assignment".encode("utf-8")),
        )
        for name, content in examples:
            with self.subTest(extension=name.rsplit(".", 1)[-1]):
                form = SubmissionForm(
                    data={"note": ""},
                    files={"file": SimpleUploadedFile(name, content)},
                )
                self.assertTrue(form.is_valid(), form.errors)

    def test_unsupported_extension_is_rejected(self):
        self.client.force_login(self.writer)

        response = self.client.post(
            self.upload_url(self.order),
            {
                "action": "submit",
                "file": SimpleUploadedFile("program.exe", b"MZ"),
                "note": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertFalse(OrderSubmission.objects.exists())

    def test_oversized_upload_is_rejected(self):
        self.client.force_login(self.writer)

        response = self.client.post(
            self.upload_url(self.order),
            {
                "action": "submit",
                "file": SimpleUploadedFile(
                    "oversized.pdf",
                    b"%PDF-1.4\n"
                    + b"x" * MAX_SUBMISSION_FILE_SIZE
                    + b"\n%%EOF",
                ),
                "note": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertFalse(OrderSubmission.objects.exists())

    def test_unauthenticated_download_is_denied(self):
        submission = self.create_submission(self.order, self.writer, approved=True)

        response = self.client.get(self.download_url(submission))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_client_can_download_own_approved_submission(self):
        submission = self.create_submission(self.order, self.writer, approved=True)
        self.client.force_login(self.client_user)

        response = self.client.get(self.download_url(submission))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="assignment.pdf"',
        )
        self.assertEqual(b"".join(response.streaming_content), PDF_CONTENT)
        response.close()

    def test_client_cannot_download_another_clients_submission(self):
        submission = self.create_submission(
            self.other_order,
            self.other_writer,
            approved=True,
        )
        self.client.force_login(self.client_user)

        response = self.client.get(self.download_url(submission))

        self.assertEqual(response.status_code, 404)

    def test_writer_can_download_submission_for_assigned_order(self):
        submission = self.create_submission(self.order, self.writer)
        self.client.force_login(self.writer)

        response = self.client.get(self.download_url(submission))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), PDF_CONTENT)
        response.close()

    def test_writer_cannot_download_unrelated_order_submission(self):
        submission = self.create_submission(
            self.other_order,
            self.other_writer,
        )
        self.client.force_login(self.writer)

        response = self.client.get(self.download_url(submission))

        self.assertEqual(response.status_code, 404)

    def test_client_cannot_download_unapproved_submission(self):
        submission = self.create_submission(self.order, self.writer)
        self.client.force_login(self.client_user)

        response = self.client.get(self.download_url(submission))

        self.assertEqual(response.status_code, 404)

    def test_staff_can_download_submission_pending_review(self):
        staff = User.objects.create_user(
            username="staff",
            password="test-password",
            is_staff=True,
        )
        submission = self.create_submission(self.order, self.writer)
        self.client.force_login(staff)

        response = self.client.get(self.download_url(submission))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), PDF_CONTENT)
        response.close()

    def test_submission_media_url_is_not_served_directly(self):
        submission = self.create_submission(self.order, self.writer, approved=True)

        response = self.client.get(f"/media/{submission.file.name}")

        self.assertEqual(response.status_code, 404)

    def test_unknown_role_cannot_download_submission(self):
        submission = self.create_submission(self.order, self.writer, approved=True)
        invalid_user = User.objects.create_user(
            username="invalid-download-role",
            password="test-password",
            role="unexpected",
        )
        self.client.force_login(invalid_user)

        response = self.client.get(self.download_url(submission))

        self.assertEqual(response.status_code, 404)

    def test_missing_submission_download_returns_404(self):
        self.client.force_login(self.client_user)

        response = self.client.get(reverse("download_submission", args=[99999]))

        self.assertEqual(response.status_code, 404)


class OrderWorkflowTests(TestCase):
    def setUp(self):
        self.media_directory = TemporaryDirectory()
        self.settings_override = override_settings(
            MEDIA_ROOT=self.media_directory.name
        )
        self.settings_override.enable()
        self.client_user = User.objects.create_user(
            username="workflow-client",
            password="test-password",
            role="client",
        )
        self.other_client = User.objects.create_user(
            username="other-workflow-client",
            password="test-password",
            role="client",
        )
        self.writer = User.objects.create_user(
            username="workflow-writer",
            password="test-password",
            role="writer",
        )
        self.other_writer = User.objects.create_user(
            username="other-workflow-writer",
            password="test-password",
            role="writer",
        )
        self.staff = User.objects.create_user(
            username="workflow-staff",
            password="test-password",
            is_staff=True,
        )
        self.order = self.create_order()

    def tearDown(self):
        self.settings_override.disable()
        self.media_directory.cleanup()

    def order_form_data(self, *, budget="125.00", deadline=None):
        deadline = deadline or timezone.localtime(
            timezone.now() + timedelta(days=2)
        )
        return {
            "title": "Workflow order",
            "subject": "English",
            "description": "Write an assignment.",
            "academic_level": "College",
            "deadline": deadline.strftime("%Y-%m-%dT%H:%M"),
            "budget": budget,
        }

    def create_order(self, status="pending"):
        return Order.objects.create(
            client=self.client_user,
            title="Workflow order",
            subject="English",
            description="Write an assignment.",
            academic_level="College",
            deadline=timezone.now() + timedelta(days=2),
            budget="125.00",
            status=status,
        )

    def valid_pdf(self):
        return SimpleUploadedFile(
            "assignment.pdf",
            PDF_CONTENT,
            content_type="application/pdf",
        )

    def submit(self, actor=None, order=None, filename="assignment.pdf"):
        return submit_order_work(
            actor or self.writer,
            (order or self.order).pk,
            file=SimpleUploadedFile(filename, PDF_CONTENT),
            note="Submitted work",
        )

    def test_invalid_budget_is_rejected(self):
        form = OrderForm(data=self.order_form_data(budget="0.00"))

        self.assertFalse(form.is_valid())
        self.assertIn("budget", form.errors)

    def test_negative_budget_is_rejected(self):
        form = OrderForm(data=self.order_form_data(budget="-0.01"))

        self.assertFalse(form.is_valid())
        self.assertIn("budget", form.errors)

    def test_model_validation_rejects_nonpositive_budget(self):
        self.order.budget = 0

        with self.assertRaises(ValidationError) as error:
            self.order.full_clean()

        self.assertIn("budget", error.exception.message_dict)

    def test_invalid_deadline_is_rejected(self):
        form = OrderForm(
            data=self.order_form_data(
                deadline=timezone.localtime(timezone.now() - timedelta(days=1))
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn("deadline", form.errors)

    def test_model_validation_rejects_past_deadline(self):
        self.order.deadline = timezone.now() - timedelta(seconds=1)

        with self.assertRaises(ValidationError) as error:
            self.order.full_clean()

        self.assertIn("deadline", error.exception.message_dict)

    def test_model_validation_rejects_unknown_status(self):
        self.order.status = "waiting"

        with self.assertRaises(ValidationError) as error:
            self.order.full_clean()

        self.assertIn("status", error.exception.message_dict)

    def test_valid_future_deadline_is_accepted(self):
        form = OrderForm(
            data=self.order_form_data(
                deadline=timezone.localtime(timezone.now() + timedelta(days=1))
            )
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_valid_order_creation(self):
        self.client.force_login(self.client_user)

        response = self.client.post(
            reverse("create_order"),
            self.order_form_data(),
        )

        self.assertRedirects(response, reverse("client_dashboard"))
        created = Order.objects.get(title="Workflow order", pk__gt=self.order.pk)
        self.assertEqual(created.client, self.client_user)
        self.assertEqual(created.status, "pending")
        self.assertGreater(created.budget, 0)

    def test_staff_can_assign_writer_and_unassign_back_to_pending(self):
        assigned = assign_writer(self.staff, self.order.pk, self.writer)

        self.assertEqual(assigned.writer, self.writer)
        self.assertEqual(assigned.status, "assigned")

        unassigned = assign_writer(self.staff, self.order.pk, None)

        self.assertIsNone(unassigned.writer)
        self.assertEqual(unassigned.status, "pending")

    def test_assignment_rejects_non_writer_account(self):
        with self.assertRaises(ValidationError):
            assign_writer(self.staff, self.order.pk, self.client_user)

    def test_non_staff_cannot_assign_writer(self):
        with self.assertRaises(PermissionDenied):
            assign_writer(self.client_user, self.order.pk, self.writer)

    def test_assignment_route_requires_staff_and_supports_unassignment(self):
        url = reverse("assign_writer", args=[self.order.pk])
        self.client.force_login(self.client_user)

        denied = self.client.post(url, {"writer": self.writer.pk})
        self.assertEqual(denied.status_code, 302)
        self.assertIsNone(Order.objects.get(pk=self.order.pk).writer)

        self.client.force_login(self.staff)
        assigned = self.client.post(url, {"writer": self.writer.pk})
        self.assertRedirects(assigned, reverse("admin_dashboard"))
        self.order.refresh_from_db()
        self.assertEqual(self.order.writer, self.writer)
        self.assertEqual(self.order.status, "assigned")

        unassigned = self.client.post(url, {"writer": ""})
        self.assertRedirects(unassigned, reverse("admin_dashboard"))
        self.order.refresh_from_db()
        self.assertIsNone(self.order.writer)
        self.assertEqual(self.order.status, "pending")

    def test_assignment_rejects_completed_order(self):
        self.order.status = "completed"
        self.order.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            assign_writer(self.staff, self.order.pk, self.writer)

    def test_assignment_rejects_cancelled_order(self):
        self.order.status = "cancelled"
        self.order.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            assign_writer(self.staff, self.order.pk, self.writer)

    def test_writer_cannot_submit_an_unassigned_order(self):
        with self.assertRaises(PermissionDenied):
            self.submit()

    def test_anonymous_writer_submission_is_rejected(self):
        with self.assertRaises(PermissionDenied):
            submit_order_work(
                AnonymousUser(),
                self.order.pk,
                file=self.valid_pdf(),
            )

    def test_assigned_writer_can_submit_work(self):
        assign_writer(self.staff, self.order.pk, self.writer)

        submission = self.submit()

        self.assertEqual(submission.order_id, self.order.pk)
        self.assertFalse(submission.approved)
        self.assertEqual(Order.objects.get(pk=self.order.pk).status, "submitted")

    def test_writer_can_submit_after_starting_work(self):
        assign_writer(self.staff, self.order.pk, self.writer)
        start_order_work(self.writer, self.order.pk)

        submission = self.submit()

        self.assertEqual(submission.order_id, self.order.pk)
        self.assertEqual(Order.objects.get(pk=self.order.pk).status, "submitted")

    def test_writer_cannot_submit_after_completion(self):
        self.order.writer = self.writer
        self.order.status = "completed"
        self.order.save(update_fields=["writer", "status"])

        with self.assertRaises(ValidationError):
            self.submit()

    def test_writer_cannot_submit_after_cancellation(self):
        assign_writer(self.staff, self.order.pk, self.writer)
        cancel_order(self.staff, self.order.pk)

        with self.assertRaises(ValidationError):
            self.submit()

    def test_repeated_submission_requires_a_revision(self):
        assign_writer(self.staff, self.order.pk, self.writer)
        self.submit()

        with self.assertRaises(ValidationError):
            self.submit(filename="duplicate.pdf")

    def test_writer_cannot_start_order_in_invalid_state(self):
        assign_writer(self.staff, self.order.pk, self.writer)
        self.submit()

        with self.assertRaises(ValidationError):
            start_order_work(self.writer, self.order.pk)

    def test_only_order_owner_or_staff_can_approve(self):
        assign_writer(self.staff, self.order.pk, self.writer)
        submission = self.submit()

        with self.assertRaises(PermissionDenied):
            approve_submission(self.other_client, submission.pk)

    def test_writer_cannot_approve_submission(self):
        assign_writer(self.staff, self.order.pk, self.writer)
        submission = self.submit()

        with self.assertRaises(PermissionDenied):
            approve_submission(self.writer, submission.pk)

    def test_client_approval_completes_order_and_is_final(self):
        assign_writer(self.staff, self.order.pk, self.writer)
        submission = self.submit()

        approved = approve_submission(self.client_user, submission.pk)
        self.order.refresh_from_db()

        self.assertTrue(approved.approved)
        self.assertEqual(self.order.status, "completed")
        with self.assertRaises(ValidationError):
            request_order_revision(self.client_user, self.order.pk)
        with self.assertRaises(ValidationError):
            cancel_order(self.staff, self.order.pk)

    def test_staff_can_approve_submission(self):
        assign_writer(self.staff, self.order.pk, self.writer)
        submission = self.submit()

        approve_submission(self.staff, submission.pk)
        self.order.refresh_from_db()

        self.assertEqual(self.order.status, "completed")

    def test_only_latest_submission_can_be_approved(self):
        assign_writer(self.staff, self.order.pk, self.writer)
        first_submission = self.submit()
        request_order_revision(self.client_user, self.order.pk)
        second_submission = self.submit(filename="revision.pdf")

        with self.assertRaises(ValidationError):
            approve_submission(self.client_user, first_submission.pk)

        approve_submission(self.client_user, second_submission.pk)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "completed")

    def test_a_second_submission_cannot_be_approved_after_an_approval(self):
        assign_writer(self.staff, self.order.pk, self.writer)
        first_submission = self.submit()
        approve_submission(self.client_user, first_submission.pk)

        second_submission = OrderSubmission.objects.create(
            order=self.order,
            writer=self.writer,
            file=self.valid_pdf(),
        )
        Order.objects.filter(pk=self.order.pk).update(status="submitted")

        with self.assertRaises(ValidationError):
            approve_submission(self.client_user, second_submission.pk)

    def test_unrelated_user_cannot_request_revision(self):
        assign_writer(self.staff, self.order.pk, self.writer)
        self.submit()

        with self.assertRaises(PermissionDenied):
            request_order_revision(self.other_client, self.order.pk)

    def test_revision_can_only_be_requested_for_submitted_order(self):
        with self.assertRaises(ValidationError):
            request_order_revision(self.client_user, self.order.pk)

        assign_writer(self.staff, self.order.pk, self.writer)
        self.submit()
        request_order_revision(self.client_user, self.order.pk)
        with self.assertRaises(ValidationError):
            request_order_revision(self.client_user, self.order.pk)

    def test_revision_allows_re_submission_by_assigned_writer(self):
        assign_writer(self.staff, self.order.pk, self.writer)
        first_submission = self.submit()

        revision_order = request_order_revision(
            self.client_user,
            self.order.pk,
        )
        self.assertEqual(revision_order.status, "revision")

        second_submission = self.submit(filename="revision.pdf")
        self.assertNotEqual(first_submission.pk, second_submission.pk)
        self.assertEqual(
            Order.objects.get(pk=self.order.pk).status,
            "submitted",
        )

    def test_starting_work_requires_assigned_state_and_writer(self):
        with self.assertRaises(PermissionDenied):
            start_order_work(self.writer, self.order.pk)

        assign_writer(self.staff, self.order.pk, self.writer)
        with self.assertRaises(PermissionDenied):
            start_order_work(self.other_writer, self.order.pk)

        started = start_order_work(self.writer, self.order.pk)
        self.assertEqual(started.status, "in_progress")

    def test_anonymous_user_cannot_start_work(self):
        assign_writer(self.staff, self.order.pk, self.writer)

        with self.assertRaises(PermissionDenied):
            start_order_work(AnonymousUser(), self.order.pk)

    def test_staff_can_cancel_and_cancelled_order_is_terminal(self):
        cancelled = cancel_order(self.staff, self.order.pk)

        self.assertEqual(cancelled.status, "cancelled")
        with self.assertRaises(ValidationError):
            assign_writer(self.staff, self.order.pk, self.writer)
        with self.assertRaises(ValidationError):
            cancel_order(self.staff, self.order.pk)

    def test_only_staff_can_cancel_orders(self):
        with self.assertRaises(PermissionDenied):
            cancel_order(self.client_user, self.order.pk)

        with self.assertRaises(PermissionDenied):
            cancel_order(self.writer, self.order.pk)

    def test_cannot_cancel_order_with_approved_submission(self):
        assign_writer(self.staff, self.order.pk, self.writer)
        submission = self.submit()
        approve_submission(self.client_user, submission.pk)

        with self.assertRaises(ValidationError):
            cancel_order(self.staff, self.order.pk)

    def test_order_views_enforce_anonymous_and_role_access(self):
        create_url = reverse("create_order")
        writer_orders_url = reverse("writer_orders")
        detail_url = reverse("writer_order_detail", args=[self.order.pk])

        anonymous_response = self.client.get(create_url)
        self.assertEqual(anonymous_response.status_code, 302)

        self.client.force_login(self.client_user)
        client_writer_list = self.client.get(writer_orders_url)
        self.assertRedirects(client_writer_list, reverse("client_dashboard"))

        self.client.force_login(self.writer)
        unassigned_detail = self.client.get(detail_url)
        self.assertEqual(unassigned_detail.status_code, 404)

        assign_writer(self.staff, self.order.pk, self.writer)
        self.client.force_login(self.other_writer)
        unrelated_detail = self.client.get(detail_url)
        self.assertEqual(unrelated_detail.status_code, 404)

    def test_anonymous_users_cannot_access_order_pages_or_actions(self):
        writer_orders_url = reverse("writer_orders")
        detail_url = reverse("writer_order_detail", args=[self.order.pk])
        assign_url = reverse("assign_writer", args=[self.order.pk])
        client_action_url = reverse(
            "client_order_action",
            args=[self.order.pk],
        )
        staff_action_url = reverse(
            "staff_order_action",
            args=[self.order.pk],
        )

        for response in (
            self.client.get(writer_orders_url),
            self.client.get(detail_url),
            self.client.get(assign_url),
            self.client.post(assign_url, {"writer": self.writer.pk}),
            self.client.post(client_action_url, {"action": "revision"}),
            self.client.post(staff_action_url, {"action": "cancel"}),
        ):
            with self.subTest(status=response.status_code, url=response.url):
                self.assertEqual(response.status_code, 302)

        self.assertEqual(Order.objects.get(pk=self.order.pk).status, "pending")

    def test_lifecycle_action_views_enforce_client_and_staff_roles(self):
        assign_writer(self.staff, self.order.pk, self.writer)
        submission = self.submit()
        client_action_url = reverse(
            "client_order_action",
            args=[self.order.pk],
        )
        staff_action_url = reverse(
            "staff_order_action",
            args=[self.order.pk],
        )

        self.client.force_login(self.other_client)
        denied_client = self.client.post(
            client_action_url,
            {"action": "approve"},
        )
        self.assertEqual(denied_client.status_code, 403)
        self.assertFalse(OrderSubmission.objects.get(pk=submission.pk).approved)

        self.client.force_login(self.writer)
        denied_staff = self.client.post(
            staff_action_url,
            {"action": "cancel"},
        )
        self.assertEqual(denied_staff.status_code, 302)
        self.assertEqual(Order.objects.get(pk=self.order.pk).status, "submitted")

        self.client.force_login(self.client_user)
        approved = self.client.post(
            client_action_url,
            {"action": "approve"},
        )
        self.assertRedirects(approved, reverse("client_dashboard"))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "completed")

    def test_client_can_request_revision_through_action_view(self):
        assign_writer(self.staff, self.order.pk, self.writer)
        self.submit()
        self.client.force_login(self.client_user)

        response = self.client.post(
            reverse("client_order_action", args=[self.order.pk]),
            {"action": "revision"},
        )

        self.assertRedirects(response, reverse("client_dashboard"))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "revision")

    def test_staff_can_cancel_through_staff_action_view(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("staff_order_action", args=[self.order.pk]),
            {"action": "cancel"},
        )

        self.assertRedirects(response, reverse("admin_dashboard"))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "cancelled")

    def test_action_views_reject_get_requests(self):
        client_action = reverse("client_order_action", args=[self.order.pk])
        staff_action = reverse("staff_order_action", args=[self.order.pk])
        self.client.force_login(self.client_user)
        self.assertEqual(self.client.get(client_action).status_code, 405)

        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(staff_action).status_code, 405)


class WriterOrdersPagePresentationTests(TestCase):
    def setUp(self):
        self.writer = User.objects.create_user(
            username="writer-ui",
            password="Secure-Test-Password-934!",
            first_name="Morgan",
            role="writer",
        )
        self.client.force_login(self.writer)

    def create_order(self, **overrides):
        values = {
            "client": User.objects.create_user(
                username=f"client-ui-{Order.objects.count()}",
                password="Secure-Test-Password-934!",
                role="client",
            ),
            "writer": self.writer,
            "title": "Research methods review",
            "subject": "Social Science",
            "description": "Review the supplied research methods brief.",
            "academic_level": "Undergraduate",
            "deadline": timezone.now() + timedelta(days=4),
            "budget": "125.00",
            "status": "in_progress",
        }
        values.update(overrides)
        return Order.objects.create(**values)

    def test_writer_orders_page_displays_real_order_details_and_actions(self):
        order = self.create_order()

        response = self.client.get(reverse("writer_orders"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Research methods review")
        self.assertContains(response, "Social Science")
        self.assertContains(response, "Undergraduate")
        self.assertContains(response, "Review the supplied research methods brief.")
        self.assertContains(response, "125.00")
        self.assertContains(response, "In Progress")
        self.assertContains(
            response,
            reverse("writer_order_detail", args=[order.pk]),
        )
        self.assertContains(response, "1")

    def test_writer_orders_page_preserves_post_csrf_logout_form(self):
        response = self.client.get(reverse("writer_orders"))

        self.assertContains(response, 'method="post"')
        self.assertContains(response, f'action="{reverse("logout")}"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')

    def test_writer_orders_page_shows_empty_state_without_orders(self):
        response = self.client.get(reverse("writer_orders"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No orders assigned yet")
        self.assertContains(response, "When an order is assigned to you")
        self.assertContains(response, "0")
