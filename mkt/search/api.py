import json

from tastypie import http
from tastypie.authorization import ReadOnlyAuthorization
from tower import ugettext as _

import amo
from access import acl
from amo.helpers import absolutify

import mkt
from mkt.api.authentication import OptionalOAuthAuthentication
from mkt.api.resources import AppResource
from mkt.search.views import _get_query, _filter_search
from mkt.search.forms import ApiSearchForm


class SearchResource(AppResource):

    class Meta(AppResource.Meta):
        resource_name = 'search'
        allowed_methods = []
        detail_allowed_methods = []
        list_allowed_methods = ['get']
        authorization = ReadOnlyAuthorization()
        authentication = OptionalOAuthAuthentication()

    def get_resource_uri(self, bundle):
        # At this time we don't have an API to the Webapp details.
        return None

    def get_list(self, request=None, **kwargs):
        form = ApiSearchForm(request.GET if request else None)
        if not form.is_valid():
            raise self.form_errors(form)

        is_admin = acl.action_allowed(request, 'Admin', '%')
        is_reviewer = acl.action_allowed(request, 'Apps', 'Review')

        # Pluck out status and addon type first since it forms part of the base
        # query, but only for privileged users.
        status = form.cleaned_data['status']
        addon_type = form.cleaned_data['type']

        base_filters = {
            'type': addon_type,
        }

        if status and (status == 'any' or status != amo.STATUS_PUBLIC):
            if is_admin or is_reviewer:
                base_filters['status'] = status
            else:
                return http.HttpUnauthorized(
                    content=json.dumps(
                        {'reason': _('Unauthorized to filter by status.')}))

        # Search specific processing of the results.
        region = getattr(request, 'REGION', mkt.regions.WORLDWIDE)
        qs = _get_query(region, gaia=request.GAIA, mobile=request.MOBILE,
                        tablet=request.TABLET, filters=base_filters)
        qs = _filter_search(request, qs, form.cleaned_data, region=region)
        paginator = self._meta.paginator_class(request.GET, qs,
            resource_uri=self.get_resource_list_uri(),
            limit=self._meta.limit)
        page = paginator.page()

        # Rehydrate the results as per tastypie.
        objs = [self.build_bundle(obj=obj, request=request)
                for obj in page['objects']]
        page['objects'] = [self.full_dehydrate(bundle) for bundle in objs]
        # This isn't as quite a full as a full TastyPie meta object,
        # but at least it's namespaced that way and ready to expand.
        return self.create_response(request, page)

    def dehydrate_slug(self, bundle):
        return bundle.obj.app_slug

    def dehydrate(self, bundle):
        bundle = super(SearchResource, self).dehydrate(bundle)
        for size in amo.ADDON_ICON_SIZES:
            bundle.data['icon_url_%s' % size] = bundle.obj.get_icon_url(size)
        bundle.data['absolute_url'] = absolutify(bundle.obj.get_detail_url())
        return bundle
