import logging
import base64
from urllib import quote
import os.path
import tornado.httpserver
import tornado.ioloop
import tornado.web
from tornado.web import url
from tornado import escape
from collections import defaultdict

from microblog.db import Session
from microblog.db_helpers import \
    get_user_by_username, \
    get_all_users
from microblog.exceptions import UserNotFound
from microblog.models import User
from microblog.queue import QUEUE
from pdb import set_trace


class Handler(tornado.web.RequestHandler):
    need_db_session = True

    def __init__(self, *args, **kwargs):
        super(Handler, self).__init__(*args, **kwargs)
        self._session = Session()

    def get_template_path(self):
        path = self.application.settings.get('template_path')
        if path[0] != '/':
            path = os.path.join(
                os.path.dirname(__file__),
                path
            )
        return path

    def render(self, template, **kwargs):
        def _escape(value):
            return escape.xhtml_escape(unicode(value))
        kwargs['escape'] = _escape
        kwargs['quote'] = quote
        return super(Handler, self).render(template, **kwargs)

    def get_current_user(self):
        username = self.get_secure_cookie('session')
        if username:
            return get_user_by_username(username, self._session)
        return None

    def finish(self, *args, **kwargs):
        super(Handler, self).finish(*args, **kwargs)
        if self._session is not None:
            self._session.commit()
            self._session.close()

    def send_error(self, *args, **kwargs):
        if self._session is not None:
            self._session.rollback()
            self._session.close()
            self._session = None
        super(Handler, self).send_error(*args, **kwargs)


class FrontPage(Handler):
    def get(self):
        self.render(
            'index.html',
            users = get_all_users(self._session)
        )


class User(Handler):
    def get(self, username):
        user = get_user_by_username(username, self._session)
        self.render(
            'user.html',
            user = user,
            vcard = user.vcard,
            mypage = user == self.current_user,
        )


class Follow(Handler):
    @tornado.web.authenticated
    def get(self, username):
        user = get_user_by_username(username, self._session)
        next = self.get_argument('next', '/')
        self.render('follow.html', user=user, next=next)


    @tornado.web.authenticated
    def post(self, username):
        if self.get_argument('choice') == 'YES':
            user = get_user_by_username(username, self._session)
            user.subscribers.append(self.current_user)
        next = self.get_argument('next', '/')
        self.redirect(next)


class Unfollow(Handler):
    @tornado.web.authenticated
    def get(self, username):
        user = get_user_by_username(username, self._session)
        next = self.get_argument('next', '/')
        self.render('unfollow.html', user=user, next=next)

    @tornado.web.authenticated
    def post(self, username):
        if self.get_argument('choice') == 'YES':
            user = get_user_by_username(username, self._session)
            user.subscribers.remove(self.current_user)
        next = self.get_argument('next', '/')
        self.redirect(next)


class Avatar(Handler):
    def get(self, username):
        user = get_user_by_username(username, self._session)
        vc = user.vcard
        if vc is None or vc.PHOTO is None:
            raise tornado.web.HTTPError(404)
        else:
            message = base64.standard_b64decode(vc.PHOTO.BINVAL.text)
            self.set_header('Content-Type', vc.PHOTO.TYPE or 'image/jpeg')

        self.write(message)


class Login(Handler):
    def get(self):
        next = self.get_argument('next', '/')
        self.render('login.html', next=next, errors=defaultdict(unicode))

    def post(self):
        username = self.get_argument('username')
        password = self.get_argument('password')
        next = self.get_argument('next', '/')

        errors = defaultdict(unicode)
        try:
            user = get_user_by_username(username, self._session)
        except UserNotFound:
            errors['username'] = 'User not found.'
        else:
            if user.password == password:
                self.set_secure_cookie('session', username)
                self.redirect(next)
                return
            else:
                errors['password'] = 'Password mismatch.'

        self.render('login.html', next=next, errors=errors)


class Logout(Handler):
    def get(self):
        next = self.get_argument('next', '/')
        self.render('logout.html', next=next)

    def post(self):
        next = self.get_argument('next', '/')
        self.clear_cookie('session')
        self.redirect(next)


class Post(Handler):
    @tornado.web.authenticated
    def post(self):
        text = self.get_argument('text')
        text = escape.xhtml_escape(text)
        user = self.get_current_user()

        QUEUE.add('post', text=text, user=user)

        next = self.get_argument('next', '/')
        self.redirect(next)


class Frontend(object):
    def __init__(self, port=8888, **tornado_settings):
        self.port = port
        self.tornado_settings = tornado_settings
        self.log = logging.getLogger('frontend')

    def start(self):
        self.log.debug('Starting frontend on port %s.' % self.port)

        application = tornado.web.Application(
            [
                url(r'/', FrontPage, name='front-page'),
                url(r'/user/(\w+)/', User, name='user'),
                url(r'/user/(\w+)/avatar/', Avatar, name='avatar'),
                url(r'/user/(\w+)/follow/', Follow, name='follow'),
                url(r'/user/(\w+)/unfollow/', Unfollow, name='unfollow'),
                url(r'/login/', Login, name='login'),
                url(r'/logout/', Logout, name='logout'),
                url(r'/post/', Post, name='post'),
            ],
            static_path = os.path.join(os.path.dirname(__file__), 'media'),
            **self.tornado_settings
        )

        http_server = tornado.httpserver.HTTPServer(application)
        http_server.listen(self.port)
        tornado.ioloop.IOLoop.instance().start()

