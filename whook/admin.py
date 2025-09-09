from django import forms
from django.contrib import admin

from . import config, models, services


@admin.register(models.WebHookLog)
class WebHookLogAdmin(admin.ModelAdmin):
    list_display = ("event", "url", "created_at")
    search_fields = ("event", "url")
    list_filter = ("status",)


class WebHookAppChangeFormMixin(forms.ModelForm):
    events = forms.MultipleChoiceField(choices=config.EVENTS, widget=forms.CheckboxSelectMultiple, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["events"].choices = config.EVENTS


class WebhookAddAppForm(WebHookAppChangeFormMixin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Только если создаётся новый объект
        if self.instance.pk is None:
            self.fields["secret_key"].initial = services.generate_secret_key()

    class Meta:
        model = models.WebHookApp
        fields = "__all__"


class WebhookChangeAppForm(WebHookAppChangeFormMixin):
    class Meta:
        model = models.WebHookApp
        exclude = ("secret_key",)


@admin.register(models.WebHookApp)
class WebHookAppAdmin(admin.ModelAdmin):
    list_display = ("title", "url")
    search_fields = ("title", "url")

    def get_form(self, request, obj, **kwargs):
        if obj is None:
            kwargs["form"] = WebhookAddAppForm
        else:
            kwargs["form"] = WebhookChangeAppForm
        return super().get_form(request, obj, **kwargs)
