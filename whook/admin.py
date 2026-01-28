from datetime import date, datetime, time, timedelta

from django import forms
from django.contrib import admin
from django.shortcuts import redirect
from django.utils import timezone
from django.forms import CheckboxSelectMultiple

from . import config, models, services


def week_start_for(d: date) -> date:
    # понедельник (iso Monday=1)
    return d - timedelta(days=d.isoweekday() - 1)


class WeekListFilter(admin.SimpleListFilter):
    title = "неделя"
    parameter_name = "week"

    def lookups(self, request, model_admin):
        # 1) один запрос: только самая поздняя created_at
        last_ts = model_admin.get_queryset(request).order_by("created_at").values_list("created_at", flat=True).first()
        if not last_ts:
            return []

        # 2) переводим в локальную дату
        last_date = timezone.localdate(last_ts)

        # 3) старт/финиш интервала по неделям
        ws_today = week_start_for(timezone.localdate())
        ws_last = week_start_for(last_date)

        # 4) строим непрерывные недели от сегодня до последней с данными
        items = []
        ws = ws_today
        while ws >= ws_last:
            we = ws + timedelta(days=6)
            label = f"{ws:%d.%m.%Y} – {we:%d.%m.%Y}"
            items.append((ws.isoformat(), label))
            ws -= timedelta(weeks=1)

        return items

    def queryset(self, request, queryset):
        if self.value():
            start = date.fromisoformat(self.value())
            end = start + timedelta(days=7)
            start_dt = timezone.make_aware(datetime.combine(start, time.min))
            end_dt = timezone.make_aware(datetime.combine(end, time.min))
            return queryset.filter(created_at__gte=start_dt, created_at__lt=end_dt)
        return queryset


class DateRedirectMixin:
    show_full_result_count = False

    def changelist_view(self, request, extra_context=None):
        if "week" not in request.GET:
            today = timezone.localdate()
            ws = week_start_for(today).isoformat()
            params = request.GET.copy()
            params["week"] = ws
            for k in list(params.keys()):
                if k.startswith("created_at__"):
                    params.pop(k, None)
            return redirect(f"{request.path}?{params.urlencode()}")

        return super().changelist_view(request, extra_context=extra_context)


@admin.register(models.WebHookLog)
class WebHookLogAdmin(DateRedirectMixin, admin.ModelAdmin):
    list_display = ("event", "url", "created_at")
    search_fields = ("event", "url")
    list_filter = (
        WeekListFilter,
        "status",
    )


class WebHookAppChangeFormMixin(forms.ModelForm):
    events = forms.MultipleChoiceField(choices=config.EVENTS, widget=forms.CheckboxSelectMultiple, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["events"].choices = config.EVENTS

        if self.instance and self.instance.pk:
            selected_events = self.instance.events or []
        else:
            selected_events = self.data.getlist('events') if self.data else []

        for event_code, event_title in config.EVENTS:
            if event_code in selected_events:
                available_fields = config.EVENT_AVAILABLE_FIELDS.get(event_code, [])
                if available_fields:
                    field_name = f"fields_for_{event_code}"

                    current_values = []
                    if self.instance and self.instance.pk and self.instance.selected_fields:
                        current_values = self.instance.selected_fields.get(event_code, [])

                    self.fields[field_name] = forms.MultipleChoiceField(
                        choices=available_fields,
                        widget=CheckboxSelectMultiple,
                        required=False,
                        label=f"Поля для события '{event_title}'",
                        initial=current_values,
                        help_text="Если не выбрано ни одно поле, будут отправляться все данные"
                    )

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Сохраняем выбранные поля для каждого события
        selected_fields = {}
        for event_code, event_title in config.EVENTS:
            field_name = f"fields_for_{event_code}"
            if field_name in self.cleaned_data:
                fields = self.cleaned_data[field_name]
                if fields:
                    selected_fields[event_code] = fields

        instance.selected_fields = selected_fields

        if commit:
            instance.save()

        return instance


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

    class Media:
        js = ('admin/js/webhook_app_fields_toggle.js',)
        css = {
            'all': ('admin/css/webhook_app_fields.css',)
        }
