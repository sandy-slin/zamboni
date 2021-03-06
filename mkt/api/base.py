from collections import defaultdict
import json

from django.core.exceptions import ObjectDoesNotExist

from tastypie import http
from tastypie.bundle import Bundle
from tastypie.exceptions import ImmediateHttpResponse
from tastypie.resources import Resource, ModelResource

import commonware.log
from translations.fields import PurifiedField, TranslatedField

log = commonware.log.getLogger('z.api')


def list_url(name):
    return ('api_dispatch_list', {'resource_name': name})


def get_url(name, pk):
    return ('api_dispatch_detail', {'resource_name': name, 'pk': pk})


class Marketplace(object):
    """
    A mixin with some general Marketplace stuff.
    """

    def dispatch(self, request_type, request, **kwargs):
        # OAuth authentication uses the method in the signature. So we need
        # to store the original method used to sign the request.
        request.signed_method = request.method
        if 'HTTP_X_HTTP_METHOD_OVERRIDE' in request.META:
            request.method = request.META['HTTP_X_HTTP_METHOD_OVERRIDE']

        return (super(Marketplace, self)
                .dispatch(request_type, request, **kwargs))

    def non_form_errors(self, error_list):
        """
        Raises passed field errors as an immediate HttpBadRequest response.
        Similar to Marketplace.form_errors, except that it allows you to raise
        form field errors outside of form validation.

        Accepts a list of two-tuples, consisting of a field name and error
        message.

        Example usage:

        errors = []

        if 'app' in bundle.data:
            errors.append(('app', 'Cannot update the app of a rating.'))

        if 'user' in bundle.data:
            errors.append(('user', 'Cannot update the author of a rating.'))

        if errors:
            raise self.non_form_errors(errors)
        """
        errors = defaultdict(list)
        for e in error_list:
            errors[e[0]].append(e[1])
        response = http.HttpBadRequest(json.dumps({'error_message': errors}),
                                       content_type='application/json')
        return ImmediateHttpResponse(response=response)

    def form_errors(self, forms):
        errors = {}
        if not isinstance(forms, list):
            forms = [forms]
        for f in forms:
            if isinstance(f.errors, list):  # Cope with formsets.
                for e in f.errors:
                    errors.update(e)
                continue
            errors.update(dict(f.errors.items()))

        response = http.HttpBadRequest(json.dumps({'error_message': errors}),
                                       content_type='application/json')
        return ImmediateHttpResponse(response=response)

    def _auths(self):
        auths = self._meta.authentication
        if not isinstance(auths, (list, tuple)):
            auths = [self._meta.authentication]
        return auths

    def is_authenticated(self, request):
        """
        An override of the tastypie Authentication to accept an iterator
        of Authentication methods. If so it will go through in order, when one
        passes, it will use that.

        Any authentication method can still return a HttpResponse to break out
        of the loop if they desire.
        """
        for auth in self._auths():
            auth_result = auth.is_authenticated(request)

            if isinstance(auth_result, http.HttpResponse):
                raise ImmediateHttpResponse(response=auth_result)

            if auth_result:
                log.info('Logged in using %s' % auth.__class__.__name__)
                return

        raise ImmediateHttpResponse(response=http.HttpUnauthorized())

    def throttle_check(self, request):
        """
        Handles checking if the user should be throttled.

        Mostly a hook, this uses class assigned to ``throttle`` from
        ``Resource._meta``.
        """
        identifiers = [a.get_identifier(request) for a in self._auths()]

        # Check to see if they should be throttled.
        if any(self._meta.throttle.should_be_throttled(identifier)
               for identifier in identifiers):
            # Throttle limit exceeded.
            raise ImmediateHttpResponse(response=http.HttpForbidden())

    def log_throttled_access(self, request):
        """
        Handles the recording of the user's access for throttling purposes.

        Mostly a hook, this uses class assigned to ``throttle`` from
        ``Resource._meta``.
        """
        request_method = request.method.lower()
        identifiers = [a.get_identifier(request) for a in self._auths()]
        for identifier in identifiers:
            self._meta.throttle.accessed(identifier,
                                         url=request.get_full_path(),
                                         request_method=request_method)

    def cached_obj_get_list(self, request=None, **kwargs):
        """Do not interfere with cache machine caching."""
        return self.obj_get_list(request=request, **kwargs)

    def cached_obj_get(self, request=None, **kwargs):
        """Do not interfere with cache machine caching."""
        return self.obj_get(request, **kwargs)


class MarketplaceResource(Marketplace, Resource):
    """
    Use this if you would like to expose something that is *not* a Django
    model as an API.
    """
    pass


class MarketplaceModelResource(Marketplace, ModelResource):
    """Use this if you would like to expose a Django model as an API."""

    def get_resource_uri(self, bundle_or_obj):
        # Fix until my pull request gets pulled into tastypie.
        # https://github.com/toastdriven/django-tastypie/pull/490
        kwargs = {
            'resource_name': self._meta.resource_name,
        }

        if isinstance(bundle_or_obj, Bundle):
            kwargs['pk'] = bundle_or_obj.obj.pk
        else:
            kwargs['pk'] = bundle_or_obj.pk

        if self._meta.api_name is not None:
            kwargs['api_name'] = self._meta.api_name

        return self._build_reverse_url("api_dispatch_detail", kwargs=kwargs)

    @classmethod
    def should_skip_field(cls, field):
        # We don't want to skip translated fields.
        if isinstance(field, (PurifiedField, TranslatedField)):
            return False

        return True if getattr(field, 'rel') else False

    def get_object_or_404(self, cls, **filters):
        """
        A wrapper around our more familiar get_object_or_404, for when we need
        to get access to an object that isn't covered by get_obj.
        """
        if not filters:
            raise ImmediateHttpResponse(response=http.HttpNotFound())
        try:
            return cls.objects.get(**filters)
        except (cls.DoesNotExist, cls.MultipleObjectsReturned):
            raise ImmediateHttpResponse(response=http.HttpNotFound())

    def get_by_resource_or_404(self, request, **kwargs):
        """
        A wrapper around the obj_get to just get the object.
        """
        try:
            obj = self.obj_get(request, **kwargs)
        except ObjectDoesNotExist:
            raise ImmediateHttpResponse(response=http.HttpNotFound())
        return obj


class CORSResource(object):
    """
    A mixin to provide CORS support to your API.
    """

    def method_check(self, request, allowed=None):
        """
        This is the first entry point from dispatch and a place to check CORS.

        It will set a value on the request for the middleware to pick up on
        the response and add in the headers, so that any immediate http
        responses (which are usually errors) get the headers.
        """
        request.CORS = allowed
        return super(CORSResource, self).method_check(request, allowed=allowed)
