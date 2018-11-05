import logging

import re
from six import iteritems

from bitbucket.exceptions import BitbucketError

try:  # Python 2.7+
    from logging import NullHandler
except ImportError:
    class NullHandler(logging.Handler):

        def emit(self, record):
            pass

from bitbucket.utils import CaseInsensitiveDict, json_loads

logging.getLogger('bitbucket').addHandler(NullHandler())

__all__ = ('Repo',
           'Project',
           'Resource',
           'PullRequest',
           'User')


def dict2resource(raw, top=None, options=None, session=None):
    if top is None:
        top = PropertyHolder(raw)

    seqs = tuple, list, set, frozenset
    for i, j in iteritems(raw):
        if isinstance(j, dict):
            if 'self' in j:
                resource = cls_for_resource(j['self'])(options, session, j)
                setattr(top, i, resource)
            elif j.has_key('links') and j['links'].has_key('self'):
                resource = cls_for_resource(j['links']['self'])(options, session, j)
                setattr(top, i, resource)
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
                    elif seq_elem.has_key('links') and seq_elem['links'].has_key('self'):
                        resource = cls_for_resource(seq_elem['links']['self'])(
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

    def _find_for_resource(self, resource_cls, ids, expand=None):
        # print ids
        resource = resource_cls(self._options, self._session)
        params = {}
        if expand is not None:
            params['expand'] = expand
        resource.find(id=ids, params=params)
        if not resource:
            raise BitbucketError("Unable to find resource %s(%s)", resource_cls, ids)
        return resource

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
        self._load(url, params=params)

    def _parse_raw(self, raw):
        self.raw = raw
        if not raw:
            raise NotImplementedError("We cannot instantiate empty resources: %s" % raw)
        dict2resource(raw, self, self._options, self._session)

    def _default_headers(self, user_headers):
        return CaseInsensitiveDict(self._options['headers'].items() + user_headers.items())


class PullRequest(Resource):
    def __init__(self, options, session, raw=None):
        Resource.__init__(self, 'projects/{}/repos/{}/pull-requests/{}', options, session)
        if raw:
            self._parse_raw(raw)

    def can_merge(self, **params):

        if self.state == 'MERGED':
            commit = self.get_merge_commit()
            if isinstance(commit, Commit):
                commit_id = commit.displayId
            else:
                commit_id = 'Failed to fetch commitID'
            return {'canMerge': False, 'reason': 'Already merged', 'commit': commit_id}

        unapproved = True
        for self.reviewer in self.reviewers:
            if self.reviewer.status == 'APPROVED':
                unapproved = False

        if unapproved:
            return {'canMerge': False, 'reason': 'Review incomplete'}

        uri = 'projects/{}/repos/{}/pull-requests/{}/merge'.format(self.fromRef.repository.project.name,
                                                                   self.fromRef.repository.slug,
                                                                   self.id)
        url = self._get_url(uri)
        r_json = json_loads(self._session.get(url, params=params))

        if r_json.has_key('canMerge') and r_json['canMerge'] is False \
                and r_json.has_key('outcome') and r_json['outcome'] == 'CONFLICTED':
            return {'canMerge': False, 'reason': 'Merge conflicts'}

        if r_json.has_key('errors'):
            return {'canMerge': False, 'reason': r_json['errors']}

        return {'canMerge': True, 'reason': ''}

    def get_merge_commit(self, **params):
        target_commit = None
        uri = 'projects/{0}/repos/{1}/commits'.format(self.fromRef.repository.project.name,
                                                      self.fromRef.repository.name)
        url = self._get_url(uri)

        if not params:
            params['merges'] = 'only'
            params['limit'] = 1000

        r_json = json_loads(self._session.get(url, params=params))
        # print r_json
        commits = [Commit(self._options, self._session, raw_commit_json)
                         for raw_commit_json in r_json['values']]

        msg = 'Merge pull request #{0} '.format(self.id)
        for commit in commits:
            if commit.message.startswith(msg):
                target_commit = commit
                break
        return target_commit

    def merge(self):
        uri = 'projects/{}/repos/{}/pull-requests/{}/merge'.format(self.fromRef.repository.project.name,
                                                                   self.fromRef.repository.slug,
                                                                   self.id)
        url = self._get_url(uri)
        params = {'version': self.version}
        r_json = json_loads(self._session.post(url, params=params))
        commit = Commit(self._options, self._session, r_json)
        return commit


class Repo(Resource):

    def __init__(self, options, session, raw=None):
        Resource.__init__(self, 'projects/{0}/repos/{1}', options, session)
        if raw:
            self._parse_raw(raw)

    def pull_requests(self, **params):
        uri = 'projects/{}/repos/{}/pull-requests'.format(self.project.name, self.name)
        url = self._get_url(uri)
        if not params:
            params = {'state': 'merged', 'limit': 1000}
        r_json = json_loads(self._session.get(url, params=params))
        # print r_json
        pull_requests = [PullRequest(self._options, self._session, raw_repo_json)
                         for raw_repo_json in r_json['values']]

        return pull_requests

    def latest_merge_commit(self, **params):
        uri = 'projects/{0}/repos/{1}/commits'.format(self.project.name,
                                                      self.name)
        url = self._get_url(uri)

        if not params:
            params['merges'] = 'only'
            params['limit'] = 1000

        r_json = json_loads(self._session.get(url, params=params))
        # print r_json
        commits = [Commit(self._options, self._session, raw_commit_json)
                         for raw_commit_json in r_json['values']]

        if commits:
            target_commit = commits[0]
        else:
            target_commit = {'status': 'Failed', 'reason': 'No merges so far'}

        return target_commit

    def pull_request(self, id):
        _id = (self.project.name, self.name, id)
        return self._find_for_resource(PullRequest, _id)


class Commit(Resource):

    def __init__(self, options, session, raw=None):
        Resource.__init__(self, 'commits/{}', options, session)

        if raw:
            self._parse_raw(raw)


class User(Resource):
    def __init__(self, options, session, raw=None):
        Resource.__init__(self, 'users/{}', options, session)

        if raw:
            self._parse_raw(raw)


class Project(Resource):

    def __init__(self, options, session, raw=None):
        Resource.__init__(self, 'projects/{}', options, session)

        if raw:
            self._parse_raw(raw)

    def repos(self, **params):
        url = self._options['server'] + '/rest/api/1.0/projects/{}/repos'.format(self.name)
        if not params:
            params = {'limit': 1000}
        r_json = json_loads(self._session.get(url, params=params))
        repos = [Repo(self._options, self._session, raw_repo_json)
                 for raw_repo_json in r_json['values']]

        return repos

    def repo(self, id):
        # self._resource = 'projects/{}/repos/{}'.format(self.name, id)
        _id = (self.name, id)
        return self._find_for_resource(Repo, _id)


class UnknownResource(Resource):
    def __init__(self, options, session, raw=None):
        Resource.__init__(self, 'unknown{0}', options, session)
        if raw:
            self._parse_raw(raw)


resource_class_map = {
    r'projects/[^/]+$': Project,
    r'users/[^/]+$': User,
    r'projects/[^/]+/repos/[^/]+/browse$': Repo,
    r'projects/[^/]+/repos/[^/]+/pull-requests/[^/]+$': PullRequest,
}


def cls_for_resource(resource):
    resource_literal = resource[0]['href']
    for resource in resource_class_map:
        if re.search(resource, resource_literal):
            return resource_class_map[resource]
    else:
        return UnknownResource


class PropertyHolder(object):
    def __init__(self, raw):
        __bases__ = raw
