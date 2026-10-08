from pathlib import Path
import zipfile

from django.core.exceptions import ValidationError
from django.db import models
from django.conf import settings
from django.utils import timezone


MAX_SUBMISSION_FILE_SIZE = 10 * 1024 * 1024
ALLOWED_SUBMISSION_EXTENSIONS = {".pdf", ".docx", ".odt", ".rtf", ".txt"}


def validate_submission_file(uploaded_file):
    if uploaded_file.size > MAX_SUBMISSION_FILE_SIZE:
        raise ValidationError("Submission files must be no larger than 10 MB.")

    extension = Path(uploaded_file.name).suffix.lower()
    if extension not in ALLOWED_SUBMISSION_EXTENSIONS:
        raise ValidationError(
            "Upload a PDF, DOCX, ODT, RTF, or plain-text document."
        )

    try:
        uploaded_file.seek(0)
        header = uploaded_file.read(8)

        if extension == ".pdf":
            uploaded_file.seek(max(0, uploaded_file.size - 1024))
            valid_format = (
                header.startswith(b"%PDF-")
                and b"%%EOF" in uploaded_file.read(1024)
            )
        elif extension in {".docx", ".odt"}:
            uploaded_file.seek(0)
            with zipfile.ZipFile(uploaded_file) as archive:
                names = set(archive.namelist())
                if extension == ".docx":
                    valid_format = {
                        "[Content_Types].xml",
                        "word/document.xml",
                    }.issubset(names)
                else:
                    mimetype_info = archive.getinfo("mimetype")
                    valid_format = (
                        mimetype_info.file_size
                        == len(b"application/vnd.oasis.opendocument.text")
                    )
                    if valid_format:
                        with archive.open(mimetype_info) as mimetype_file:
                            valid_format = (
                                mimetype_file.read(mimetype_info.file_size + 1)
                                == b"application/vnd.oasis.opendocument.text"
                            )
        elif extension == ".rtf":
            valid_format = header.lstrip().startswith(b"{\\rtf")
        else:
            uploaded_file.seek(0)
            contents = uploaded_file.read(MAX_SUBMISSION_FILE_SIZE + 1)
            try:
                contents.decode("utf-8-sig")
                valid_format = b"\x00" not in contents and not any(
                    byte < 32 and byte not in {9, 10, 12, 13}
                    for byte in contents
                )
            except UnicodeDecodeError:
                valid_format = False
    except (
        OSError,
        zipfile.BadZipFile,
        KeyError,
        RuntimeError,
        NotImplementedError,
    ):
        valid_format = False
    finally:
        uploaded_file.seek(0)

    if not valid_format:
        raise ValidationError(
            "The uploaded file does not match its supported document format."
        )


class Order(models.Model):

    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("assigned", "Assigned"),
        ("in_progress", "In Progress"),
        ("submitted", "Submitted"),
        ("revision", "Revision"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    )

    client = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="client_orders",
        limit_choices_to={"role": "client"},
    )

    writer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="writer_orders",
        limit_choices_to={"role": "writer"},
    )

    title = models.CharField(max_length=200)
    subject = models.CharField(max_length=100)
    description = models.TextField()
    academic_level = models.CharField(max_length=100)
    deadline = models.DateTimeField()
    budget = models.DecimalField(max_digits=10, decimal_places=2)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        errors = {}

        if self.budget is not None and self.budget <= 0:
            errors["budget"] = "Budget must be greater than zero."

        if self.deadline is not None and self.deadline <= timezone.now():
            errors["deadline"] = "Deadline must be in the future."

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.title


class OrderSubmission(models.Model):

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="submissions"
    )

    writer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="submissions"
    )

    file = models.FileField(
        upload_to="submissions/",
    )

    note = models.TextField(
        blank=True
    )
    approved = models.BooleanField(
        default=False
        )

    submitted_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"{self.order.title} - {self.writer.username}"