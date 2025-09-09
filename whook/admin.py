from datetime import timedelta, date, datetime, time

from django import forms
from django.apps import apps
from django.contrib import admin
from django.contrib import admin
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import escape

from . import config, models, services


def week_start_for(d: date) -> date:
    # понедельник (iso Monday=1)
    return d - timedelta(days=d.isoweekday() - 1)

class WeekListFilter(admin.SimpleListFilter):
    title = "неделя"
    parameter_name = "week"

    def lookups(self, request, model_admin):
        # 1) один запрос: только самая поздняя created_at
        last_ts = (
            model_admin.get_queryset(request)
            .order_by("created_at")
            .values_list("created_at", flat=True)
            .first()
        )
        if not last_ts:
            return []

        # 2) переводим в локальную дату
        last_date = timezone.localdate(last_ts)

        # 3) старт/финиш интервала по неделям
        ws_today = week_start_for(timezone.localdate())
        ws_last  = week_start_for(last_date)

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
            end_dt   = timezone.make_aware(datetime.combine(end,   time.min))
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
    list_filter = (WeekListFilter, "status",)


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
