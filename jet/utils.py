import datetime
import json
import logging
from importlib import import_module

from django.apps.registry import apps
from django.contrib import admin, messages
from django.contrib.admin import AdminSite
from django.contrib.admin.options import IncorrectLookupParameters
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse
from django.template import Context
from django.urls import NoReverseMatch, resolve, reverse
from django.utils import translation
from django.utils.encoding import force_text, smart_str
from django.utils.functional import Promise
from django.utils.text import capfirst


logger = logging.getLogger(__name__)


class JsonResponse(HttpResponse):
    """
    An HTTP response class that consumes data to be serialized to JSON.
    :param data: Data to be dumped into json. By default only ``dict`` objects
      are allowed to be passed due to a security flaw before EcmaScript 5. See
      the ``safe`` parameter for more information.
    :param encoder: Should be an json encoder class. Defaults to
      ``django.core.serializers.json.DjangoJSONEncoder``.
    :param safe: Controls if only ``dict`` objects may be serialized. Defaults
      to ``True``.
    """

    def __init__(self, data, encoder=DjangoJSONEncoder, safe=True, **kwargs):
        if safe and not isinstance(data, dict):
            raise TypeError('In order to allow non-dict objects to be '
                            'serialized set the safe parameter to False')
        kwargs.setdefault('content_type', 'application/json')
        data = json.dumps(data, cls=encoder)
        super(JsonResponse, self).__init__(content=data, **kwargs)


def get_app_list(context, order=True):
    admin_site = get_admin_site(context)
    request = context['request']

    app_dict = {}
    for model, model_admin in admin_site._registry.items():
        app_label = model._meta.app_label
        has_module_perms = model_admin.has_module_permission(request)

        if has_module_perms:
            perms = model_admin.get_model_perms(request)

            # Check whether user has any perm for this module.
            # If so, add the module to the model_list.
            if True in perms.values():
                info = (app_label, model._meta.model_name)
                model_dict = {
                    'name': capfirst(model._meta.verbose_name_plural),
                    'object_name': model._meta.object_name,
                    'perms': perms,
                    'model_name': model._meta.model_name
                }
                if perms.get('view', False) or perms.get('change', False):
                    try:
                        model_dict['admin_url'] = reverse('admin:%s_%s_changelist' % info, current_app=admin_site.name)
                    except NoReverseMatch:
                        pass
                if perms.get('add', False):
                    try:
                        model_dict['add_url'] = reverse('admin:%s_%s_add' % info, current_app=admin_site.name)
                    except NoReverseMatch:
                        pass
                if app_label in app_dict:
                    app_dict[app_label]['models'].append(model_dict)
                else:
                    try:
                        name = apps.get_app_config(app_label).verbose_name
                    except NameError:
                        name = app_label.title()
                    app_dict[app_label] = {
                        'name': name,
                        'app_label': app_label,
                        'app_url': reverse(
                            'admin:app_list',
                            kwargs={'app_label': app_label},
                            current_app=admin_site.name,
                        ),
                        'has_module_perms': has_module_perms,
                        'models': [model_dict],
                    }

    # Sort the apps alphabetically.
    app_list = list(app_dict.values())

    if order:
        app_list.sort(key=lambda x: x['name'].lower())

        # Sort the models alphabetically within each app.
        for app in app_list:
            app['models'].sort(key=lambda x: x['name'])

    return app_list


def get_admin_site(context):
    try:
        current_resolver = resolve(context.get('request').path)
        index_resolver = resolve(reverse('%s:index' % current_resolver.namespaces[0]))

        if hasattr(index_resolver.func, 'admin_site'):
            return index_resolver.func.admin_site

        for func_closure in index_resolver.func.__closure__:
            if isinstance(func_closure.cell_contents, AdminSite):
                return func_closure.cell_contents
    except Exception as e:
        logger.debug(e)

    return admin.site


def get_admin_site_name(context):
    return get_admin_site(context).name


class LazyDateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime) or isinstance(obj, datetime.date):
            return obj.isoformat()
        elif isinstance(obj, Promise):
            return force_text(obj)
        return self.encode(obj)


def get_model_instance_label(instance):
    if getattr(instance, "related_label", None):
        return instance.related_label()
    return smart_str(instance)


class SuccessMessageMixin:
    """
    Adds a success message on successful form submission.
    """
    success_message = ''

    def form_valid(self, form):
        response = super().form_valid(form)
        success_message = self.get_success_message(form.cleaned_data)
        if success_message:
            messages.success(self.request, success_message)
        return response

    def get_success_message(self, cleaned_data):
        return self.success_message % cleaned_data


def get_model_queryset(admin_site, model, request, preserved_filters=None):
    model_admin = admin_site._registry.get(model)

    if model_admin is None:
        return

    try:
        changelist_url = reverse('%s:%s_%s_changelist' % (
            admin_site.name,
            model._meta.app_label,
            model._meta.model_name
        ))
    except NoReverseMatch:
        return

    changelist_filters = None

    if preserved_filters:
        changelist_filters = preserved_filters.get('_changelist_filters')

    if changelist_filters:
        changelist_url += '?' + changelist_filters

    if model_admin:
        queryset = model_admin.get_queryset(request)
    else:
        queryset = model.objects

    list_display = model_admin.get_list_display(request)
    list_display_links = model_admin.get_list_display_links(request, list_display)
    list_filter = model_admin.get_list_filter(request)
    search_fields = model_admin.get_search_fields(request) \
        if hasattr(model_admin, 'get_search_fields') else model_admin.search_fields
    list_select_related = model_admin.get_list_select_related(request) \
        if hasattr(model_admin, 'get_list_select_related') else model_admin.list_select_related

    actions = model_admin.get_actions(request)
    if actions:
        list_display = ['action_checkbox'] + list(list_display)

    ChangeList = model_admin.get_changelist(request)

    change_list_args = [
        request, model, list_display, list_display_links, list_filter,
        model_admin.date_hierarchy, search_fields, list_select_related,
        model_admin.list_per_page, model_admin.list_max_show_all,
        model_admin.list_editable, model_admin]

    try:
        sortable_by = model_admin.get_sortable_by(request)
        change_list_args.append(sortable_by)
    except AttributeError:
        # django version < 2.1
        pass

    try:
        cl = ChangeList(*change_list_args)
        queryset = cl.get_queryset(request)
    except IncorrectLookupParameters:
        pass

    return queryset


def get_possible_language_codes():
    language_code = translation.get_language()

    language_code = language_code.replace('_', '-').lower()
    language_codes = []

    # making dialect part uppercase
    split = language_code.split('-', 2)
    if len(split) == 2:
        language_code = '%s-%s' % (split[0].lower(), split[1].upper()) if split[0] != split[1] else split[0]

    language_codes.append(language_code)

    # adding language code without dialect part
    if len(split) == 2:
        language_codes.append(split[0].lower())

    return language_codes


def context_to_dict(context):
    if isinstance(context, Context):
        flat = {}
        for d in context.dicts:
            flat.update(d)
        context = flat

    return context


def user_is_authenticated(user):
    if callable(user.is_authenticated):
        return user.is_authenticated()
    else:
        return user.is_authenticated


def format_widget_data(data: dict):
    res = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, bool):
            value = str(value).lower()
        key = key.replace('_', '-')
        key = f'data-{key}'
        res[key] = value
    return res


def import_value(path: str):
    module, name = path.rsplit('.', 1)
    try:
        module = import_module(module)
        value = getattr(module, name)
    except (ImportError, AttributeError) as e:
        raise ImportError(e)
    return value
