import copy
import sys
from urlparse import urlparse

from bitbucket.exceptions import BitbucketError
from bitbucket.resilientsession import ResilientSession
from bitbucket.resources import Resource, Project
from bitbucket.utils import json_loads


class Bitbucket(object):
    DEFAULT_OPTIONS = {
        "server": "http://localhost:7990",
        "context_path": "/",
        "rest_path": "api",
        "rest_api_version": "1.0",
        "agile_rest_api_version": "1.0",
        "verify": True,
        "resilient": True,
        "async": False,
        "async_workers": 5,
        "client_cert": None,
        "check_update": False,
        "delay_reload": 0,
        "headers": {
            'Cache-Control': 'no-cache',
            'Content-Type': 'application/json',  # ;charset=UTF-8',
            'X-Atlassian-Token': 'no-check'}}


    BITBUCKET_BASE_URL = Resource.BITBUCKET_BASE_URL

    def __init__(self,
                 server=None,
                 options=None,
                 basic_auth=None,
                 async_=False,
                 async_workers=5,
                 logging=True,
                 max_retries=3,
                 proxies=None,
                 timeout=None,
                 ):
        self.sys_version_info = tuple([i for i in sys.version_info])

        if options is None:
            options = {}

        if server:
            options['server'] = server
        if async_:
            options['async'] = async_
            options['async_workers'] = async_workers

        self.logging = logging

        self._options = copy.copy(Bitbucket.DEFAULT_OPTIONS)

        self._options.update(options)

        self._rank = None

        if self._options['server'].endswith('/'):
            self._options['server'] = self._options['server'][:-1]

        context_path = urlparse(self._options['server']).path
        if len(context_path) > 0:
            self._options['context_path'] = context_path

        if basic_auth:
            self._create_http_basic_session(*basic_auth, timeout=timeout)
            self._session.headers.update(self._options['headers'])
        self._session.headers.update(self._options['headers'])

        self._session.max_retries = max_retries

        if proxies:
            self._session.proxies = proxies

    def _create_http_basic_session(self, username, password, timeout=None):
        verify = self._options['verify']
        self._session = ResilientSession(timeout=timeout)
        self._session.verify = verify
        self._session.auth = (username, password)
        self._session.cert = self._options['client_cert']

    def find(self, resource_format, ids=None):
        resource = Resource(resource_format, self._options, self._session)
        resource.find(ids)
        return resource

    def _find_for_resource(self, resource_cls, ids, expand=None):
        resource = resource_cls(self._options, self._session)
        params = {}
        if expand is not None:
            params['expand'] = expand
        resource.find(id=ids, params=params)
        if not resource:
            raise BitbucketError("Unable to find resource %s(%s)", resource_cls, ids)
        return resource

    def project(self, id):
        return self._find_for_resource(Project, id)

    def projects(self):
        url = self._options['server'] + '/rest/api/1.0/projects'
        r_json = json_loads(self._session.get(url))
        projects = [Project(self._options, self._session, raw_project_json)
                    for raw_project_json in r_json['values']]

        return projects
