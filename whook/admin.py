from datetime import date, datetime, time, timedelta

from django import forms
from django.contrib import admin
from django.forms import CheckboxSelectMultiple
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.safestring import mark_safe

from . import config, models, services


class EventFieldsConfigWidget(forms.Widget):
    def render(self, name, value, attrs=None, renderer=None):
        value = value or {}
        attrs = attrs or {}

        html = []
        html.append(f'<div class="whook-fields-ui" data-root="{name}">')

        for event_code, event_title in config.EVENTS:
            choices = config.EVENT_AVAILABLE_FIELDS.get(event_code) or []
            if not choices:
                continue

            sub_name = f"{name}__{event_code}"
            selected = value.get(event_code, [])

            cb = CheckboxSelectMultiple(choices=choices)

            html.append(
                f"""
                <fieldset class="whook-event-block" data-event="{event_code}"
                          style="margin:12px 0; padding:10px; border:1px solid #ddd; border-radius:6px;">
                  <legend style="padding:0 6px;">
                    Поля для события «{event_title}» <span style="color:#888;">({event_code})</span>
                  </legend>
                  {cb.render(sub_name, selected, attrs=attrs, renderer=renderer)}
                </fieldset>
                """
            )

        html.append("</div>")
        html.append(
            f"""
<script>
(function() {{
  function sync() {{
    var root = document.querySelector('.whook-fields-ui[data-root="{name}"]');
    if (!root) return;

    var selected = new Set();
    document.querySelectorAll('input[name="events"]').forEach(function(el) {{
      if (el.checked) selected.add(el.value);
    }});

    root.querySelectorAll('.whook-event-block').forEach(function(block) {{
      var code = block.getAttribute('data-event');
      block.style.display = selected.has(code) ? '' : 'none';
    }});
  }}

  document.addEventListener('change', function(e) {{
    if (e.target && e.target.name === 'events') sync();
  }});

  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', sync);
  }} else {{
    sync();
  }}
}})();
</script>
            """
        )

        return mark_safe("".join(html))

    def value_from_datadict(self, data, files, name):
        result = {}
        for event_code, _ in config.EVENTS:
            key = f"{name}__{event_code}"
            vals = data.getlist(key)
            if vals:
                result[event_code] = vals
        return result


class EventFieldsConfigFormField(forms.Field):
    def __init__(self, **kwargs):
        super().__init__(required=False, widget=EventFieldsConfigWidget(), **kwargs)

    def clean(self, value):
        value = value or {}
        cleaned = {}

        for event_code, fields in value.items():
            allowed = {k for k, _ in (config.EVENT_AVAILABLE_FIELDS.get(event_code) or [])}
            filtered = [f for f in fields if f in allowed]
            if filtered:
                cleaned[event_code] = filtered

        return cleaned

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
    events = forms.MultipleChoiceField(
        choices=config.EVENTS,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    selected_fields_ui = EventFieldsConfigFormField(
        label="Выбор полей по событиям",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["events"].choices = config.EVENTS
        if self.instance and self.instance.pk:
            self.initial["selected_fields_ui"] = self.instance.selected_fields or {}
        else:
            self.initial["selected_fields_ui"] = {}

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.selected_fields = self.cleaned_data.get("selected_fields_ui") or {}
        if commit:
            instance.save()
            self.save_m2m()
        return instance

class WebhookAddAppForm(WebHookAppChangeFormMixin):
    class Meta:
        model = models.WebHookApp
        exclude = ("selected_fields",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Только если создаётся новый объект
        if self.instance.pk is None:
            self.fields["secret_key"].initial = services.generate_secret_key()

class WebhookChangeAppForm(WebHookAppChangeFormMixin):
    class Meta:
        model = models.WebHookApp
        exclude = ("secret_key", "selected_fields")


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
