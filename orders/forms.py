from django import forms
from django.utils import timezone
from .models import Order, OrderSubmission, validate_submission_file


class OrderForm(forms.ModelForm):

    class Meta:
        model = Order

        fields = [
            "title",
            "subject",
            "description",
            "academic_level",
            "deadline",
            "budget",
        ]

        widgets = {
            "deadline": forms.DateTimeInput(
                attrs={"type": "datetime-local"}
            ),
            "description": forms.Textarea(
                attrs={"rows": 6}
            ),
        }

    def clean_budget(self):
        budget = self.cleaned_data["budget"]
        if budget <= 0:
            raise forms.ValidationError("Budget must be greater than zero.")
        return budget

    def clean_deadline(self):
        deadline = self.cleaned_data["deadline"]
        if deadline <= timezone.now():
            raise forms.ValidationError("Deadline must be in the future.")
        return deadline


class AssignWriterForm(forms.ModelForm):

    class Meta:
        model = Order

        fields = [
            "writer",
        ]

        widgets = {
            "writer": forms.Select(
                attrs={
                    "class": "form-select"
                }
            )
        }


class SubmissionForm(forms.ModelForm):
    file = forms.FileField(validators=[validate_submission_file])

    class Meta:
        model = OrderSubmission
        fields = ["file", "note"]