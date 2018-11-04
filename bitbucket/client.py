import copy
import json
import sys
from urlparse import urlparse

import warnings
from requests.auth import AuthBase

from bitbucket.exceptions import BitbucketError
from bitbucket.resilientsession import ResilientSession
from bitbucket.resources import Resource, Repo, Project
from bitbucket.utils import json_loads


class BitbucketCookieAuth(AuthBase):
    """Jira Cookie Authentication

    Allows using cookie authentication as described by
    https://developer.atlassian.com/jiradev/jira-apis/jira-rest-apis/jira-rest-api-tutorials/jira-rest-api-example-cookie-based-authentication

    """

    def __init__(self, session, _get_session, auth):
        self._session = session
        self._get_session = _get_session
        self.__auth = auth

    def handle_401(self, response, **kwargs):
        if response.status_code != 401:
            return response
        self.init_session()
        response = self.process_original_request(response.request.copy())
        return response

    def process_original_request(self, original_request):
        self.update_cookies(original_request)
        return self.send_request(original_request)

    def update_cookies(self, original_request):
        # Cookie header needs first to be deleted for the header to be updated using
        # the prepare_cookies method. See request.PrepareRequest.prepare_cookies
        if 'Cookie' in original_request.headers:
            del original_request.headers['Cookie']
        original_request.prepare_cookies(self.cookies)

    def init_session(self):
        self.start_session()

    def __call__(self, request):
        request.register_hook('response', self.handle_401)
        return request

    def send_request(self, request):
        return self._session.send(request)

    @property
    def cookies(self):
        return self._session.cookies

    def start_session(self):
        self._get_session(self.__auth)


class Bitbucket(object):
    DEFAULT_OPTIONS = {
        #        "server": "http://localhost:2990/jira",
        "server": "http://localhost:7990",
        "auth_url": '/rest/auth/1/session',
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

    checked_version = False

    BITBUCKET_BASE_URL = Resource.BITBUCKET_BASE_URL

    def __init__(self,
                 server=None,
                 options=None,
                 basic_auth=None,
                 # oauth=None,
                 # jwt=None,
                 # kerberos=False,
                 # kerberos_options=None,
                 # validate=False,
                 async_=False,
                 async_workers=5,
                 logging=True,
                 max_retries=3,
                 proxies=None,
                 timeout=None,
                 auth=None,
                 ):
        self.sys_version_info = tuple([i for i in sys.version_info])

        if options is None:
            options = {}
            if server and hasattr(server, 'keys'):
                warnings.warn(
                    "Old API usage, use Bitbucket(url) or Bitbucket(options={'server': url}, when using dictionary always use named parameters.",
                    DeprecationWarning)
                options = server
                server = None

        if server:
            options['server'] = server
        if async_:
            options['async'] = async_
            options['async_workers'] = async_workers

        self.logging = logging

        self._options = copy.copy(Bitbucket.DEFAULT_OPTIONS)

        self._options.update(options)

        self._rank = None

        # Rip off trailing slash since all urls depend on that
        if self._options['server'].endswith('/'):
            self._options['server'] = self._options['server'][:-1]

        context_path = urlparse(self._options['server']).path
        if len(context_path) > 0:
            self._options['context_path'] = context_path

        if basic_auth:
            self._create_http_basic_session(*basic_auth, timeout=timeout)
            self._session.headers.update(self._options['headers'])
        #elif jwt:
        #     self._create_jwt_session(jwt, timeout)
        # elif kerberos:
        #     self._create_kerberos_session(timeout, kerberos_options=kerberos_options)
        if auth:
            self._create_cookie_auth(auth, timeout)
            # validate = True  # always log in for cookie based auth, as we need a first request to be logged in
        # else:
        #     verify = self._options['verify']
        #     self._session = ResilientSession(timeout=timeout)
        #     self._session.verify = verify
        self._session.headers.update(self._options['headers'])

        if 'cookies' in self._options:
            self._session.cookies.update(self._options['cookies'])

        self._session.max_retries = max_retries

        if proxies:
            self._session.proxies = proxies

        # if validate:
        #     # This will raise an Exception if you are not allowed to login.
        #     # It's better to fail faster than later.
        #     user = self.session(auth)
        #     if user.raw is None:
        #         auth_method = (
        #             oauth or basic_auth or jwt or kerberos or auth or "anonymous"
        #         )
        #         raise BitbucketError("Can not log in with %s" % str(auth_method))

    #        self.deploymentType = None
    # if get_server_info:
    #     # We need version in order to know what API calls are available or not
    #     si = self.server_info()
    #     try:
    #         self._version = tuple(si['versionNumbers'])
    #     except Exception as e:
    #         logging.error("invalid server_info: %s", si)
    #         raise e
    #     self.deploymentType = si.get('deploymentType')
    # else:
    #     self._version = (0, 0, 0)
    #
    # if self._options['check_update'] and not JIRA.checked_version:
    #     self._check_update_()
    #     JIRA.checked_version = True
    #
    # self._fields = {}
    # for f in self.fields():
    #     if 'clauseNames' in f:
    #         for name in f['clauseNames']:
    #             self._fields[name] = f['id']

    def session(self, auth=None):
        """Get a dict of the current authenticated user's session information.

        :param auth: Tuple of username and password.
        :type auth: Optional[Tuple[str,str]]

        :rtype: User

        """
        url = '{server}{auth_url}'.format(**self._options)

        if isinstance(self._session.auth, tuple) or auth:
            if not auth:
                auth = self._session.auth
            username, password = auth
            authentication_data = {'username': username, 'password': password}
            r = self._session.post(url, data=json.dumps(authentication_data))
        else:
            r = self._session.get(url)

    def _create_cookie_auth(self, auth, timeout):
        self._session = ResilientSession(timeout=timeout)
        self._session.auth = BitbucketCookieAuth(self._session, self.session, auth)
        self._session.verify = self._options['verify']
        self._session.cert = self._options['client_cert']

    def _create_http_basic_session(self, username, password, timeout=None):
        verify = self._options['verify']
        self._session = ResilientSession(timeout=timeout)
        self._session.verify = verify
        self._session.auth = (username, password)
        self._session.cert = self._options['client_cert']

    def find(self, resource_format, ids=None):
        """Find Resource object for any addressable resource on the server.

        This method is a universal resource locator for any REST-ful resource in JIRA. The
        argument ``resource_format`` is a string of the form ``resource``, ``resource/{0}``,
        ``resource/{0}/sub``, ``resource/{0}/sub/{1}``, etc. The format placeholders will be
        populated from the ``ids`` argument if present. The existing authentication session
        will be used.

        The return value is an untyped Resource object, which will not support specialized
        :py:meth:`.Resource.update` or :py:meth:`.Resource.delete` behavior. Moreover, it will
        not know to return an issue Resource if the client uses the resource issue path. For this
        reason, it is intended to support resources that are not included in the standard
        Atlassian REST API.

        :param resource_format: the subpath to the resource string
        :type resource_format: str
        :param ids: values to substitute in the ``resource_format`` string
        :type ids: tuple or None
        :rtype: Resource
        """
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
