# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import webob

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api import xmlutil
from cinder import db
from cinder.db.sqlalchemy import api as sqlalchemy_api
from cinder import exception
from cinder.openstack.common import strutils
from cinder import quota


QUOTAS = quota.QUOTAS


authorize_update = extensions.extension_authorizer('volume', 'quotas:update')
authorize_show = extensions.extension_authorizer('volume', 'quotas:show')


class QuotaTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('quota_set', selector='quota_set')
        root.set('id')

        for resource in QUOTAS.resources:
            elem = xmlutil.SubTemplateElement(root, resource)
            elem.text = resource

        return xmlutil.MasterTemplate(root, 1)


class QuotaSetsController(object):

    def _format_quota_set(self, project_id, quota_set):
        """Convert the quota object to a result dict"""

        quota_set['id'] = str(project_id)

        return dict(quota_set=quota_set)

    def _validate_quota_limit(self, limit):
        if not isinstance(limit, int):
            msg = _("Quota limit must be specified as an integer value.")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        # NOTE: -1 is a flag value for unlimited
        if limit < -1:
            msg = _("Quota limit must be -1 or greater.")
            raise webob.exc.HTTPBadRequest(explanation=msg)

    def _get_quotas(self, context, id, usages=False):
        values = QUOTAS.get_project_quotas(context, id, usages=usages)

        if usages:
            return values
        else:
            return dict((k, v['limit']) for k, v in values.items())

    @wsgi.serializers(xml=QuotaTemplate)
    def show(self, req, id):
        context = req.environ['cinder.context']
        authorize_show(context)

        params = req.params
        if not hasattr(params, '__call__') and 'usage' in params:
            usage = strutils.bool_from_string(params['usage'])
        else:
            usage = False

        try:
            sqlalchemy_api.authorize_project_context(context, id)
        except exception.NotAuthorized:
            raise webob.exc.HTTPForbidden()

        return self._format_quota_set(id, self._get_quotas(context, id, usage))

    @wsgi.serializers(xml=QuotaTemplate)
    def update(self, req, id, body):
        context = req.environ['cinder.context']
        authorize_update(context)
        project_id = id
        for key in body['quota_set'].keys():
            if key in QUOTAS:
                self._validate_quota_limit(body['quota_set'][key])
                value = int(body['quota_set'][key])
                try:
                    db.quota_update(context, project_id, key, value)
                except exception.ProjectQuotaNotFound:
                    db.quota_create(context, project_id, key, value)
                except exception.AdminRequired:
                    raise webob.exc.HTTPForbidden()
        return {'quota_set': self._get_quotas(context, id)}

    @wsgi.serializers(xml=QuotaTemplate)
    def defaults(self, req, id):
        context = req.environ['cinder.context']
        authorize_show(context)
        return self._format_quota_set(id, QUOTAS.get_defaults(context))


class Quotas(extensions.ExtensionDescriptor):
    """Quotas management support"""

    name = "Quotas"
    alias = "os-quota-sets"
    namespace = "http://docs.openstack.org/volume/ext/quotas-sets/api/v1.1"
    updated = "2011-08-08T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-quota-sets',
                                           QuotaSetsController(),
                                           member_actions={'defaults': 'GET'})
        resources.append(res)

        return resources
