import json
import os
from urllib.parse import parse_qsl

from django import template
from django.contrib.admin.widgets import RelatedFieldWidgetWrapper
from django.forms import (
    BoundField, CheckboxInput, Field, ModelChoiceField, ModelMultipleChoiceField, Select,
    SelectMultiple,
)
from django.urls import reverse
from django.utils.encoding import smart_str
from django.utils.formats import get_format
from django.utils.safestring import mark_safe

from jet import __version__, settings
from jet.models import Bookmark
from jet.sidebar import Sidebar, get_menu_items
from jet.utils import (
    format_widget_data, get_admin_site, get_model_instance_label,
    get_model_queryset, get_possible_language_codes, import_value,
)


register = template.Library()
assignment_tag = register.assignment_tag if hasattr(register, 'assignment_tag') else register.simple_tag
Sidebar = import_value(settings.JET_SIDE_MENU_CLS)


@assignment_tag
def jet_get_date_format():
    return get_format('DATE_INPUT_FORMATS')[0]


@assignment_tag
def jet_get_time_format():
    return get_format('TIME_INPUT_FORMATS')[0]


@assignment_tag
def jet_get_datetime_format():
    return get_format('DATETIME_INPUT_FORMATS')[0]


@assignment_tag(takes_context=True)
def jet_get_menu(context):
    return get_menu_items(context)


@assignment_tag
def jet_get_bookmarks(user):
    if user is None:
        return None
    return Bookmark.objects.filter(user=user.pk)


@register.filter
def jet_is_checkbox(field):
    return field.field.widget.__class__.__name__ == CheckboxInput().__class__.__name__


@register.filter
def jet_select2_lookups(field: BoundField):
    form_field: Field = getattr(field, 'field', None)
    if not (
        form_field and
        (isinstance(form_field, ModelChoiceField) or
         isinstance(form_field, ModelMultipleChoiceField))
    ):
        return field

    qs = form_field.queryset
    model = qs.model

    if not (
        getattr(model, 'autocomplete_search_fields', None) and
        getattr(form_field, 'autocomplete', True)
    ):
        return field

    choices = []
    app_label = model._meta.app_label
    model_name = model._meta.object_name
    url = getattr(form_field, 'url', reverse('jet:model_lookup'))

    data = getattr(form_field.widget, 'data', {})
    data['blank'] = not form_field.required

    attrs = {
        'class': 'ajax',
        'data-app-label': app_label,
        'data-model': model_name,
        'data-ajax--url': url,
        **format_widget_data(data),
    }

    initial_value = field.value()

    if isinstance(form_field, ModelMultipleChoiceField):
        if initial_value:
            initial_objects = model.objects.filter(pk__in=initial_value)
            choices.extend(
                [(initial_object.pk, get_model_instance_label(initial_object))
                 for initial_object in initial_objects]
            )

        if isinstance(form_field.widget, RelatedFieldWidgetWrapper):
            form_field.widget.widget = SelectMultiple(attrs)
        else:
            form_field.widget = SelectMultiple(attrs)
        form_field.choices = choices
    elif isinstance(form_field, ModelChoiceField):
        if initial_value:
            try:
                initial_object = model.objects.get(pk=initial_value)
                attrs['data-object-id'] = initial_value
                choices.append((initial_object.pk, get_model_instance_label(initial_object)))
            except model.DoesNotExist:
                pass

        if isinstance(form_field.widget, RelatedFieldWidgetWrapper):
            form_field.widget.widget = Select(attrs)
        else:
            form_field.widget = Select(attrs)
        form_field.choices = choices

    return field


@assignment_tag(takes_context=True)
def jet_get_current_theme(context):
    if 'request' in context and 'JET_THEME' in context['request'].COOKIES:
        theme = context['request'].COOKIES['JET_THEME']
        if isinstance(settings.JET_THEMES, list) and len(settings.JET_THEMES) > 0:
            for conf_theme in settings.JET_THEMES:
                if isinstance(conf_theme, dict) and conf_theme.get('theme') == theme:
                    return theme
    return settings.JET_DEFAULT_THEME


@assignment_tag
def jet_get_themes():
    return settings.JET_THEMES


@assignment_tag
def jet_get_current_version():
    return __version__


@register.filter
def jet_append_version(url):
    if '?' in url:
        return '%s&v=%s' % (url, __version__)
    else:
        return '%s?v=%s' % (url, __version__)


@assignment_tag
def jet_get_side_menu_compact():
    return settings.JET_SIDE_MENU_COMPACT


@assignment_tag
def jet_change_form_sibling_links_enabled():
    return settings.JET_CHANGE_FORM_SIBLING_LINKS


def jet_sibling_object(context, next):
    original = context.get('original')

    if not original:
        return

    model = type(original)
    preserved_filters_plain = context.get('preserved_filters', '')
    preserved_filters = dict(parse_qsl(preserved_filters_plain))
    admin_site = get_admin_site(context)

    if admin_site is None:
        return

    request = context.get('request')
    queryset = get_model_queryset(admin_site, model, request, preserved_filters=preserved_filters)

    if queryset is None:
        return

    sibling_object = None
    object_pks = list(queryset.values_list('pk', flat=True))

    try:
        index = object_pks.index(original.pk)
        sibling_index = index + 1 if next else index - 1
        exists = sibling_index < len(object_pks) if next else sibling_index >= 0
        sibling_object = queryset.get(pk=object_pks[sibling_index]) if exists else None
    except ValueError:
        pass

    if sibling_object is None:
        return

    url = reverse('%s:%s_%s_change' % (
        admin_site.name,
        model._meta.app_label,
        model._meta.model_name
    ), args=(sibling_object.pk,))

    if preserved_filters_plain != '':
        url += '?' + preserved_filters_plain

    return {
        'label': smart_str(sibling_object),
        'url': url
    }


@assignment_tag(takes_context=True)
def jet_previous_object(context):
    return jet_sibling_object(context, False)


@assignment_tag(takes_context=True)
def jet_next_object(context):
    return jet_sibling_object(context, True)


@assignment_tag(takes_context=True)
def jet_popup_response_data(context):
    if context.get('popup_response_data'):
        return context['popup_response_data']

    return json.dumps({
        'action': context.get('action'),
        'value': context.get('value') or context.get('pk_value'),
        'obj': smart_str(context.get('obj')),
        'new_value': context.get('new_value')
    })


@assignment_tag(takes_context=True)
def jet_delete_confirmation_context(context):
    if context.get('deletable_objects') is None and context.get('deleted_objects') is None:
        return ''
    return mark_safe('<div class="delete-confirmation-marker"></div>')


@assignment_tag
def jet_static_translation_urls():
    language_codes = get_possible_language_codes()

    urls = []
    url_templates = [
        'jet/js/i18n/jquery-ui/datepicker-__LANGUAGE_CODE__.js',
        'jet/js/i18n/jquery-ui-timepicker/jquery.ui.timepicker-__LANGUAGE_CODE__.js',
        'jet/js/i18n/select2/__LANGUAGE_CODE__.js'
    ]

    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static')

    for tpl in url_templates:
        for language_code in language_codes:
            url = tpl.replace('__LANGUAGE_CODE__', language_code)
            path = os.path.join(static_dir, url)

            if os.path.exists(path):
                urls.append(url)
                break

    return urls


@register.simple_tag(takes_context=True)
def jet_render_sidebar(context):
    return Sidebar().render(context)
