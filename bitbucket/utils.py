import json
from bitbucket.exceptions import BitbucketError

class CaseInsensitiveDict(dict):

    def __init__(self, *args, **kw):
        super(CaseInsensitiveDict, self).__init__(*args, **kw)

        self.itemlist = {}
        for key, value in super(CaseInsensitiveDict, self).items():
            if key != key.lower():
                self[key.lower()] = value
                self.pop(key, None)

    def __setitem__(self, key, value):
        """Overwrite [] implementation."""
        super(CaseInsensitiveDict, self).__setitem__(key.lower(), value)

def raise_on_error(r, verb='???', **kwargs):
    request = kwargs.get('request', None)

    if r is None:
        raise BitbucketError(None, **kwargs)

    if r.status_code >= 400:
        error = ''
        if r.status_code == 403 and "x-authentication-denied-reason" in r.headers:
            error = r.headers["x-authentication-denied-reason"]
        elif r.text:
            try:
                response = json.loads(r.text)
                if 'message' in response:
                    error = response['message']
                elif 'errorMessages' in response and len(response['errorMessages']) > 0:
                    errorMessages = response['errorMessages']
                    if isinstance(errorMessages, (list, tuple)):
                        error = errorMessages[0]
                    else:
                        error = errorMessages
                elif 'errors' in response and len(response['errors']) > 0 and isinstance(response['errors'], dict):
                    error_list = response['errors'].values()
                    error = ", ".join(error_list)
                else:
                    error = r.text
            except ValueError:
                error = r.text
        raise BitbucketError(
            r.status_code, error, r.url, request=request, response=r, **kwargs)
    if r.status_code not in [200, 201, 202, 204]:
        raise BitbucketError(r.status_code, request=request, response=r, **kwargs)
    if r.status_code == 200 and len(r.content) == 0 \
            and 'X-Seraph-LoginReason' in r.headers \
            and 'AUTHENTICATED_FAILED' in r.headers['X-Seraph-LoginReason']:
        pass

def json_loads(r):
#    raise_on_error(r)
    try:
        return r.json()
    except ValueError:
        if not r.text:
            return {}
        raise
