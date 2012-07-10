import urllib
import json

from oauth2 import (
    Consumer as OAuthConsumer, 
    Token, 
    Request as OAuthRequest,
    SignatureMethod_HMAC_SHA1,
)

import requests
from requests.exceptions import HTTPError


# Status code for an Http permanent redirect
REDIRECT = 301

# Auth constants for an API call. 
NOT_REQUIRED = 0
REQUIRED = 1
OPTIONAL = 2


class PhotobucketError(Exception):
    """
        Represents a Photobucket Error.
        E.g. Http 400
    """
    response = None


class PhotobucketAPIError(Exception):
    """
        Represents a Photobucket API Error.
        E.g. Making a request with an invalid HTTP method.
    """
    pass


class Base(object):
    """
        Base class for all Photobucket APIs.
    """

    # Photobucket API main endpoint
    DOMAIN = 'api.photobucket.com'

    # Used per API to define the main URI for that specific API.
    # E.g URI = /album/! - Will send a request to self.DOMAIN + /album/!
    # The ! is a special character used by Photobucket to indicate an identifier.
    # Ex. /album/!?id=identifier
    # All the APIs use an identifier for about 98% of all their methods, that's why
    # its already in the URI to save me the burden of putting it in almost every call :).
    URI = '/'
    
    # Url for user authentication.
    LOGIN = 'http://photobucket.com/apilogin/login'

    def __init__(self, key, secret, token=None, token_secret=None, subdomain=None):
        """
            Base API Class. All Photobucket APIs need to subclass.

            @key: Your photobucket API Key.
            @secret: Your photobucket API secret.
            @token: Can be a request or access token.
            @token_secret: Can be a request or access secret.
            @subdomain: The subdomain or "silo" to use when required by API. 
                        See http://bit.ly/Nla3WD
        """

        self.key = key
        self.secret = secret
        self.token = token
        self.token_secret = token_secret
        self.subdomain = subdomain or self.DOMAIN

    def get_timestamp(self):
        return self.make_request('time', base_uri=Base.URI)

    # These four methods send pass Base.URI as base_uri to allow access
    # from any Photobucket API ( Album.ping ) since they are essential.

    def ping(self, method="GET"):
        return self.make_request('ping', base_uri=Base.URI, method=method)

    def login_request(self):
        """ 
            Get a login request token to use during web authentication.
        """
        return self.make_request('login/request', base_uri=Base.URI, method='POST')

    def get_access_token(self):
        return self.make_request('login/access', base_uri=Base.URI, method='POST')

    def get_login_url(self, token=None, extra=None):
        """
            Returns the login url for the provided token.
            This assumes that token or self.token is a Request Token.
        """
        if self.token is None and token is None:
            raise PhotobucketAPIError("token needs to be set on instance or provided.")
        params = {}
        if extra:
            params['extra'] = extra
        params.update(dict(oauth_token=token or self.token))
        return "%s?%s" % (self.LOGIN, urllib.urlencode(params))

    def make_request(self, url, base_uri=None, params=None, auth=REQUIRED, method="GET", silo=False, **kwargs):
        """
            Makes a request to Photobucket API.
            @url: The REST path to be requested after the [identifier]. By default this
                  value is appended to self.URI.
                  E.g. 
                    self.URI = /album/!
                    url = /share/all
                    The uri to request will be /album/!/share/all
            @base_uri: Allows for a quick override of self.URI per call.
            @params: A dictionary of parameters to send with the request.
            @auth: An Integer that determines whether this request needs to be authenticated.
            @method: The HTTP method to be used.
            @silo: Boolean. If True then this request will be sent to a specific silo/subdomain.

        """

        params = params or dict()
        body = kwargs.get('body', '')
        headers = {'User-Agent': 'python-photobucket/0.2 (Language=Python)', 'Content-type':'application/x-www-form-urlencoded'}
        headers.update(kwargs.get('extra_headers', {}))
        # Unless explicitly provided, set the default response format to json.
        params.setdefault('format', 'json')
        if 'id' in params:
            params['id'] = self.clean_identifier(params['id'])
        # Remove all params with a value of "None"
        params = remove_empty(params)

        # Begin auth stuff...
        token =  None
        consumer = OAuthConsumer(key=self.key, secret=self.secret)
        if auth in (REQUIRED, OPTIONAL):
            # Setup the oauth token
            try:
                token = Token(key=self.token, secret=self.token_secret)
            except ValueError, e:
                if auth == REQUIRED:
                    # Only raise the exception if auth is required.
                    raise PhotobucketAPIError("Token and Token secret must be set.")

        # Give priority to base_uri since its a quick override of class.URI
        req_uri = "%s%s" % (base_uri or self.URI, url)

        if silo:
            # This request has to be sent to a specific "silo" or "subdomain".
            uri = "http://%s%s" % (self.subdomain, req_uri)
            # Don't allow redirects if this is to be sent to a specific silo.
            # For in photobucket's own words..
            # "Photobucket ultimately prefers that you use the information given, rather than relying on the redirects"
            allow_redirects = False
        else:
            uri = "http://%s%s" % (self.DOMAIN, req_uri)
            allow_redirects = True
        req = OAuthRequest.from_consumer_and_token(consumer, token, method, uri, parameters=params, body=body)

        # Make sure to ALWAYS pass the main domain to the signature instead of the actual url to be requested.
        req.normalized_url = "http://%s%s" % (self.DOMAIN, req_uri)
        req.sign_request(SignatureMethod_HMAC_SHA1(), consumer, token)

        try:
            # I do this to take advantage of the already defined requests and their default values.
            response = getattr(requests, method.lower())(req.to_url(), headers=headers, allow_redirects=allow_redirects)
            response.raise_for_status(allow_redirects=allow_redirects)
        except AttributeError:
            raise PhotobucketAPIError('Invalid Http method')
        except HTTPError, e:
            # This whole handling is still in Beta. 
            # Because I'm still deciding on whether to keep it 
            # or use "safe_mode" for all "POST" requests. To take advantage of Photobucket's redirect.
            # Suggestions are more than welcome...
            if e.response.status_code == REDIRECT:
                # Need to catch a redirect error because that means that user sent a request
                # without a "silo" so it needs to be stored.
                content = self.parse_response(e.response.content, params['format'])
                # Not too sure about this...
                self.subdomain = content['content']['subdomain'].split('//')[1]
                return self.make_request(url, base_uri, params, auth, method, silo, **kwargs)
            error = PhotobucketError(e.message)
            error.response = e.response
            raise error
        return response

    def clean_identifier(self, identifier):
        """
            Takes a string or list 
            and returns the properly formatted Photobucket identifier.
        """
        if isinstance(identifier, list):
            return '%2F'.join(identifier)
        else:
            return identifier

    def parse_response(self, resp, format):
        """
            Parses a response.
        """
        # To-Do: Add support for all Photobucket supported responses.
        if format == 'json':
            return json.loads(resp)
        else:
            return resp


class AlbumAndGroupBase(object):
    """
        This class defines common calls used in both
        the Album and GroupAlbums APIs.
    """

    def get_url(self, album):
        url = '/url'
        params = dict(id=album)
        return self.make_request(url, params=params)

    def follow(self, album, feed=None, email=None):
        url = '/follow/!'
        params = dict(id=album, aid=feed, email=email)
        return self.make_request(url, params=params, method='POST', silo=True)

    def stop_following(self, album, subscription_id, feed=None):
        url = '/follow/!'
        params = dict(id=album, 
                      aid=feed, 
                      user_subscription_id=subscription_id, )
        return self.make_request(url, params=params, method='DELETE')

    def get_following_status(self, album, feed=None, email=None):
        url = '/follow/!'
        params = dict(id=album, aid=feed, email=email)
        return self.make_request(url, params=params)

    def get_privacy_settings(self, album):
        url = '/privacy'
        params = dict(id=album)
        return self.make_request(url, params=params)

    def update_privacy_settings(self, album, privacy, password=None):
        url = '/privacy'
        params = dict(id=album, privacy=privacy, password=password)
        return self.make_request(url, params=params, method='POST', silo=True)

    def get_vanity_url(self, album):
        url = '/vanity'
        params = dict(id=album)
        return self.make_request(url, params=params, auth=NOT_REQUIRED)

    def get_theme(self, album):
        url = '/theme'
        params = dict(id=album)
        return self.make_request(url, params=params)

    def share(self, album, services, message=None):
        url = '/share/!'
        params = dict(id=album, aid=services, message=message)
        return self.make_request(url, params=params, method='POST', silo=True)


class Album(Base, AlbumAndGroupBase):
    """
        Photobucket Album API.
    """

    URI = '/album/!'

    def upload_media(self):
        pass

    def get(self):
        pass

    def create_new(self, album, name):
        params = dict(id=album, name=name)
        return self.make_request('', params=params, method='POST', silo=True)

    def rename(self, album, name):
        params = dict(id=album, name=name)
        return self.make_request('', params=params, method='PUT')

    def delete(self, album):
        params = dict(id=album)
        return self.make_request('', params=params, method='DELETE', silo=True)

    def get_organization(self, album):
        url = '/organize'
        params = dict(id=album)
        return self.make_request(url, params=params)

    def set_organization(self, album, order_type, order=None):
        url = '/organize'
        params = dict(id=album, order_type=order_type, order=order)
        return self.make_request(url, params=params, method='POST', silo=True)


class GroupAlbums(Base, AlbumAndGroupBase):
    URI = '/group/!'

    def upload_media(self):
        pass

    def create_new(self, name, url=None, uploads=None, comments=None, 
                    view=None, password=None, users=None, description=None):
        params = dict(name=name, vanity=url,
                      uploads=uploads, comments=comments,
                      view=view, password=password,
                      add=users, descriptions=description,)
        return self.make_request('', params=params, method='POST', silo=True)

    def get_media(self, album, mtype=None, paginated=None, page=None, perpage=None, sortby=None):
        params = dict(id=album, media=mtype, 
                      paginated=paginated, page=page, 
                      perpage=perpage, sortorder=sortby, )
        return self.make_request('', params=params, auth=OPTIONAL)

    def get_contributors(self, album, username=None):
        url = '/contributor/!'
        params = dict(id=album, aid=username)
        return self.make_request(url, params=params, auth=OPTIONAL)

    def get_information(self, album):
        url = '/info'
        params = dict(id=album)
        return self.make_request(url, params=params)

    def set_information(self, album, title=None, description=None, thumbnail_url=None):
        url = '/info'
        params = dict(id=album,
                      title=title,
                      description=description,
                      url=thumbnail_url,)
        return self.make_request(url, params=params, method='POST', silo=True)

    def get_media_tags(self, album, tagname=None, separate=None, page=None, perpage=None):
        url = '/tag'
        params = dict(id=album,
                      separate=separate,
                      page=page,
                      perpage=perpage,)
        if tagname:
            url = '%s/%s' % (url, tagname)
        return self.make_request(url, params=params, auth=NOT_REQUIRED, method='GET')


class Media(Base):
    URI = '/media/!'


class Search(Base):
    URI = '/search/!'


class Users(Base):
    URI = '/user/!'


def remove_empty(d):
    """
        Helper function that removes all keys from a dictionary (d),
        that have a None value.
        @d: Dictionary to remove keys with empty values from.
    """
    for key in d.keys():
        if d[key] is None:
            del d[key]
    return d
