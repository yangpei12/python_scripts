import os

from django import forms
from django.forms import inlineformset_factory

from .models import Requirement, Ticket, TicketAttachment, TicketComment


ALLOWED_ATTACHMENT_EXT = {
    ".pdf", ".txt", ".csv", ".tsv", ".xlsx", ".xls", ".doc", ".docx",
    ".zip", ".gz", ".tar", ".7z",
    ".fq", ".fastq", ".fa", ".fasta", ".sam", ".bam", ".vcf", ".bed", ".gff",
    ".png", ".jpg", ".jpeg", ".gif", ".svg",
    ".md", ".html",
}
MAX_ATTACHMENT_BYTES = 100 * 1024 * 1024  # 100MB


_DATETIME_INPUT = forms.DateTimeInput(
    attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
)
_DATETIME_FORMATS = ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")


class TicketForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ["project_no", "project_name", "client_name", "description"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }


class RequirementForm(forms.ModelForm):
    class Meta:
        model = Requirement
        fields = ["title", "detail", "difficulty", "due_at", "order"]
        widgets = {
            "detail": forms.Textarea(attrs={"rows": 2}),
            "due_at": _DATETIME_INPUT,
            "order": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["due_at"].input_formats = _DATETIME_FORMATS
        self.fields["order"].required = False


class _BaseRequirementFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        valid = [
            f for f in self.forms
            if f.cleaned_data and not f.cleaned_data.get("DELETE")
        ]
        if not valid:
            raise forms.ValidationError("请至少填写一个需求条目。")


RequirementFormSet = inlineformset_factory(
    Ticket,
    Requirement,
    form=RequirementForm,
    formset=_BaseRequirementFormSet,
    extra=1,
    can_delete=True,
)


class CommentForm(forms.ModelForm):
    class Meta:
        model = TicketComment
        fields = ["body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 3, "placeholder": "发表评论…"})}


class RejectForm(forms.Form):
    reason = forms.CharField(
        label="打回原因",
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "请说明需要调整的点"}),
        min_length=2,
        max_length=1000,
    )


class AttachmentForm(forms.Form):
    kind = forms.ChoiceField(label="类型", choices=TicketAttachment.Kind.choices)
    file = forms.FileField(label="选择文件")

    def clean_file(self):
        f = self.cleaned_data["file"]
        name = getattr(f, "name", "") or ""
        ext = os.path.splitext(name)[1].lower()
        if ext and ext not in ALLOWED_ATTACHMENT_EXT:
            raise forms.ValidationError(
                f"不支持的文件类型：{ext}。允许：{', '.join(sorted(ALLOWED_ATTACHMENT_EXT))}"
            )
        if f.size > MAX_ATTACHMENT_BYTES:
            raise forms.ValidationError("单个文件不能超过 100MB")
        return f
