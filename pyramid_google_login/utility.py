from collections import namedtuple
import logging
import urllib

from pyramid.settings import aslist
from requests.exceptions import RequestException
import requests

from pyramid_google_login import AuthFailed, SETTINGS_PREFIX

log = logging.getLogger(__name__)

ApiSettings = namedtuple(
    'ApiSettings',
    """
        access_type
        hosted_domain
        id
        scope_list
        secret
        signin_advice
        signin_banner
        user_id_field
    """
    )


class ApiClient(object):

    authorize_endpoint = 'https://accounts.google.com/o/oauth2/auth'
    token_endpoint = 'https://www.googleapis.com/oauth2/v3/token'
    userinfo_endpoint = 'https://www.googleapis.com/oauth2/v2/userinfo'

    def __init__(self, request):
        self.request = request

        settings = self.request.googleapi_settings
        self.id = settings.id
        self.secret = settings.secret
        self.hosted_domain = settings.hosted_domain
        self.access_type = settings.access_type
        self.scope_list = settings.scope_list
        self.user_id_field = settings.user_id_field

    def refresh_access_token(self, refresh_token):
        params = {
            'client_id': self.id,
            'client_secret': self.secret,
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token',
        }

        try:
            response = requests.get(self.token_endpoint, params=params)
            response.raise_for_status()
            oauth2_tokens = response.json()
        except RequestException as err:
            raise AuthFailed(err, 'Failed to get token from Google (%s)' % err)
        except Exception as err:
            log.warning('Unkown error while calling token endpoint',
                        exc_info=True)
            raise AuthFailed(err,
                             'Failed to get token from Google (unknown error)')

        if 'access_token' not in oauth2_tokens:
            raise AuthFailed('No access_token in response from Google')

        return oauth2_tokens

    def build_authorize_url(self, state, redirect_uri):
        params = {
            'response_type': 'code',
            'client_id': self.client_id,
            'redirect_uri': redirect_uri,
            'scope': ' '.join(self.scope_list),
            'state': state,
            'access_type': self.access_type,
        }

        if self.hosted_domain is not None:
            params['hd'] = self.hosted_domain

        authorize_url = '%s?%s' % (self.authorize_endpoint,
                                   urllib.urlencode(params))

        return authorize_url

    def exchange_token_from_code(self, redirect_uri):
        if 'error' in self.request.params:
            raise AuthFailed(
                'Error from Google (%s)' % self.request.params['error'])
        try:
            code = self.request.params['code']
        except KeyError as err:
            raise AuthFailed('No authorization code from Google')

        params = {
            'code': code,
            'client_id': self.id,
            'client_secret': self.secret,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code',
        }

        try:
            response = requests.post(self.token_endpoint, data=params)
            response.raise_for_status()
            oauth2_tokens = response.json()

        except RequestException as err:
            raise AuthFailed('Failed to get token from Google (%s)' % err)

        except Exception as err:
            log.warning('Unkown error while calling token endpoint',
                        exc_info=True)
            raise AuthFailed('Failed to get token from Google (unkown error)')

        if 'access_token' not in oauth2_tokens:
            raise AuthFailed('No access_token in response from Google')

        return oauth2_tokens

    def get_userinfo_from_token(self, oauth2_tokens):
        try:
            params = {'access_token': oauth2_tokens['access_token']}
            response = requests.get(self.userinfo_endpoint, params=params)
            response.raise_for_status()
            return response.json()
        except Exception:
            log.warning('Unkown error calling userinfo endpoint',
                        exc_info=True)
            raise AuthFailed('Failed to get userinfo from Google')

    def check_hosted_domain_user(self, userinfo):
        if self.hosted_domain is None:
            return

        try:
            user_hosted_domain = userinfo['hd']
        except KeyError:
            raise AuthFailed('Missing hd field from Google userinfo')

        if self.hosted_domain != user_hosted_domain:
            raise AuthFailed('You logged in with an unkown domain '
                             '(%s rather than %s)' % (user_hosted_domain,
                                                      self.hosted_domain))

    def get_user_id_from_userinfo(self, userinfo):
        try:
            user_id = userinfo[self.user_id_field]
        except:
            raise AuthFailed('Missing user id field from Google userinfo')

        return user_id


def includeme(config):
    settings = config.registry.settings
    prefix = SETTINGS_PREFIX

    scope_list = set(aslist(settings.get(prefix + 'scopes', '')))
    scope_list.add('email')

    try:
        api_settings = ApiSettings(
            id=settings[prefix + 'client_id'],
            secret=settings[prefix + 'client_secret'],
            hosted_domain=settings.get(prefix + 'hosted_domain'),
            access_type=settings.get(prefix + 'access_type', 'online'),
            scope_list=scope_list,
            user_id_field=settings.get(prefix + 'user_id_field'),
            signin_banner=settings.get(prefix + 'signin_banner'),
            signin_advice=settings.get(prefix + 'signin_advice'),
            )
    except KeyError:
        log.error('Missing configuration settings')
        raise

    config.add_request_method(lambda request: api_settings,
                              'googleapi_settings', property=True
                              )
    config.add_request_method(ApiClient, 'googleapi', reify=True)
