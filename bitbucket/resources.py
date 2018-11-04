import logging

import re
from six import iteritems

try:  # Python 2.7+
    from logging import NullHandler
except ImportError:
    class NullHandler(logging.Handler):

        def emit(self, record):
            pass

from bitbucket.utils import CaseInsensitiveDict, json_loads

logging.getLogger('bitbucket').addHandler(NullHandler())

__all__ = ('Repo',
           'Project')


def dict2resource(raw, top=None, options=None, session=None):
    if top is None:
        top = PropertyHolder(raw)

    seqs = tuple, list, set, frozenset
    for i, j in iteritems(raw):
        if isinstance(j, dict):
            if 'self' in j:
                resource = cls_for_resource(j['self'])(options, session, j)
                setattr(top, i, resource)
            # elif i == 'timetracking':
            #     setattr(top, 'timetracking', TimeTracking(options, session, j))
            else:
                setattr(
                    top, i, dict2resource(j, options=options, session=session))
        elif isinstance(j, seqs):
            seq_list = []
            for seq_elem in j:
                if isinstance(seq_elem, dict):
                    if 'self' in seq_elem:
                        resource = cls_for_resource(seq_elem['self'])(
                            options, session, seq_elem)
                        seq_list.append(resource)
                    else:
                        seq_list.append(
                            dict2resource(seq_elem, options=options, session=session))
                else:
                    seq_list.append(seq_elem)
            setattr(top, i, seq_list)
        else:
            setattr(top, i, j)
    return top


class Resource(object):
    BITBUCKET_BASE_URL = '{server}/rest/{rest_path}/{rest_api_version}/{path}'

    def __init__(self, resource, options, session, base_url=BITBUCKET_BASE_URL):

        self._resource = resource
        self._options = options
        self._session = session
        self._base_url = base_url

        self.raw = None

    def __getattr__(self, item):

        print "Item: %s" % item
        try:
            return self[item]
        except Exception as e:
            if item == '__getnewargs__':
                raise KeyError(item)

            if hasattr(self, 'raw') and item in self.raw:
                return self.raw[item]
            else:
                raise AttributeError('%r object has no attribute %r (%s)' % (self.__class__, item, e))

    def _get_url(self, path):
        options = self._options.copy()
        options.update({'path': path})
        return self._base_url.format(**options)

    def _load(self,
              url,
              headers=CaseInsensitiveDict(),
              params=None,
              path=None):
        r = self._session.get(url, headers=headers, params=params)
        try:
            j = json_loads(r)
        except ValueError as e:
            logging.error("%s:\n%s" % (e, r.text))
            raise e

        if path:
            j = j[path]
        self._parse_raw(j)

    def find(self,
             id,
             params=None,
             ):

        if params is None:
            params = {}

       # print self._resource
        if isinstance(id, tuple):
            path = self._resource.format(*id)
        else:
            path = self._resource.format(id)
        url = self._get_url(path)
        # print 'URL: %s' % url
        self._load(url, params=params)


    def _parse_raw(self, raw):
        self.raw = raw
        if not raw:
            raise NotImplementedError("We cannot instantiate empty resources: %s" % raw)
        dict2resource(raw, self, self._options, self._session)

    def _default_headers(self, user_headers):
        return CaseInsensitiveDict(self._options['headers'].items() + user_headers.items())


class Repo(Resource):

    def __init__(self, options, session, raw=None):
        Resource.__init__(self, 'projects/{}/repos', options, session)
        if raw:
            self._parse_raw(raw)



class Project(Resource):

    def __init__(self, options, session, raw=None):
        Resource.__init__(self, 'projects/{}', options, session)

        if raw:
            self._parse_raw(raw)

    def repos(self):
        url = self._options['server'] + '/rest/api/1.0/projects/{}/repos'.format(self.name)
        r_json = json_loads(self._session.get(url))
        repos = [Repo(self._options, self._session, raw_repo_json)
                    for raw_repo_json in r_json['values']]

        return repos



class UnknownResource(Resource):
    def __init__(self, options, session, raw=None):
        Resource.__init__(self, 'unknown{0}', options, session)
        if raw:
            self._parse_raw(raw)


resource_class_map = {
    # JIRA specific resources
    r'projects/[^/]+$': Project,
    # r'component/[^/]+$': Component,
    # r'customFieldOption/[^/]+$': CustomFieldOption,
    # r'dashboard/[^/]+$': Dashboard,
    # r'filter/[^/]$': Filter,
    # r'issue/[^/]+$': Issue,
    r'projects/[^/]+/repos/[^/]+/browse$': Repo,
    # r'issue/[^/]+/votes$': Votes,
    # r'issue/[^/]+/watchers$': Watchers,
    # r'issue/[^/]+/worklog/[^/]+$': Worklog,
    # r'issueLink/[^/]+$': IssueLink,
    # r'issueLinkType/[^/]+$': IssueLinkType,
    # r'issuetype/[^/]+$': IssueType,
    # r'priority/[^/]+$': Priority,
    # r'project/[^/]+$': Project,
    # r'project/[^/]+/role/[^/]+$': Role,
    # r'resolution/[^/]+$': Resolution,
    # r'securitylevel/[^/]+$': SecurityLevel,
    # r'status/[^/]+$': Status,
    # r'statuscategory/[^/]+$': StatusCategory,
    # r'user\?(username|accountId).+$': User,
    # r'group\?groupname.+$': Group,
    # r'version/[^/]+$': Version,
    # # GreenHopper specific resources
    # r'sprints/[^/]+$': Sprint,
    # r'views/[^/]+$': Board
}


def cls_for_resource(resource):
    resource_literal = resource[0]['href']
    for resource in resource_class_map:
        if re.search(resource, resource_literal):
            return resource_class_map[resource]
    else:
        # Generic Resource cannot directly be used b/c of different constructor signature
        return UnknownResource


class PropertyHolder(object):
    def __init__(self, raw):
        __bases__ = raw  # noqa
