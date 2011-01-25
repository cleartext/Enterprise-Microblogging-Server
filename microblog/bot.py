import re
import base64
import logging
import hashlib
import datetime
import yaml
import os.path
import sleekxmpp.componentxmpp

from microblog import search
from microblog import changelog
from microblog.db import db_session, IntegrityError
from microblog.db_helpers import \
    get_user_by_jid, \
    get_user_by_username, \
    get_all_users
from microblog.exceptions import UserNotFound
from microblog.queue import QUEUE
from microblog.models import SearchTerm, Tweet
from microblog.utils import trace_methods
from pdb import set_trace
from xml.etree import cElementTree as ET
from collections import defaultdict
from pkg_resources import parse_version as V

__version__ = changelog.current_version()


class Payload(list):
    """This class helps to extend cleartext's stanzas."""

    def __init__(self, event, bot, session):
        super(Payload, self).__init__(
            filter(lambda x: x.tag.endswith('}x'), event.getPayload())
        )
        self._event = event
        self._bot = bot
        self._session = session
        self.text = event['body']

    def __getstate__(self):
        d = self.__dict__.copy()
        del d['_event']
        del d['_bot']
        del d['_session']

    def _find_buddy_node(self):
        for node in self:
            if node.tag == '{http://cleartext.net/mblog}x':
                return node.find('{http://cleartext.net/mblog}buddy')
        # node not found, create one
        ns = '{http://cleartext.net/mblog}'
        user = get_user_by_jid(self._event['from'].jid, self._session)
        avatar_hash = self._bot.users[user.username].get('photo', '')

        x_e = ET.Element(ns + 'x')
        buddy_e = ET.SubElement(x_e, 'buddy', type='sender')
        ET.SubElement(buddy_e, 'displayName').text = \
            user.vcard and unicode(user.vcard.NICKNAME) \
            or user.username
        ET.SubElement(buddy_e, 'userName').text = user.username
        ET.SubElement(buddy_e, 'jid').text = user.jid
        ET.SubElement(buddy_e, 'avatar', type='hash').text = avatar_hash
        ET.SubElement(buddy_e, 'serviceJid').text = self._bot.jid
        self.append(x_e)
        return buddy_e

    def _set_text(self, text):
        if getattr(self, '_text', None) is None:
            buddy = self._find_buddy_node()
            if buddy is not None:
                self._text = ET.SubElement(buddy, '{http://cleartext.net/mblog}text')
                self._text.text = text
        else:
            self._text.text = text

    def _get_text(self):
        _text = getattr(self, '_text', None)
        if _text is None:
            return None
        else:
            return _text.text

    text = property(_get_text, _set_text)

    def add_node(self, name, text=None):
        buddy = self._find_buddy_node()
        if buddy is not None:
            el = ET.SubElement(buddy, '{http://cleartext.net/mblog}' + name )
            if text is not None:
                el.text = text


class Commands(object):
    """Mixin with commands."""

    def _show_followers(self, event, session=None):
        user = get_user_by_jid(event['from'].jid, session)
        if user:
            followers = list(user.subscribers)
            if followers:
                body = 'Your followers are:\n' + '\n'.join(
                    f.username for f in followers
                )
            else:
                body = 'You have no followers.'
            self.xmpp.sendMessage(user.jid, body, mfrom=self.jid, mtype='chat')

    def _show_contacts(self, event, session=None):
        user = get_user_by_jid(event['from'].jid, session)
        if user:
            contacts = list(user.contacts)
            if contacts:
                body = 'Your contacts are:\n' + '\n'.join(
                    f.username for f in contacts
                )
            else:
                body = 'You have no contacts.'
            self.xmpp.sendMessage(user.jid, body, mfrom=self.jid, mtype='chat')

    def _unfollow(self, event, username, session=None):
        user = get_user_by_jid(event['from'].jid, session)
        contact = get_user_by_username(username, session)

        if not contact:
            body = 'User @%s not found.' % username
            self.xmpp.sendMessage(event['from'].jid, body, mfrom=self.jid, mtype='chat')
            return

        for idx, u in enumerate(user.contacts):
            if u.username == contact.username:
                user.contacts.pop(idx)
                session.commit()
                self.xmpp.sendMessage(
                    user.jid,
                    'You don\'t follow @%s anymore.' % username,
                    mfrom = self.jid,
                    mtype = 'chat'
                )
                self.xmpp.sendMessage(
                    contact.jid,
                    'You lost one of your followers: @%s.' % user.username,
                    mfrom = self.jid,
                    mtype = 'chat'
                )
                return

        self.xmpp.sendMessage(
            user.jid,
            'You don\'t folow @%s.' % username,
            mfrom = self.jid,
            mtype = 'chat'
        )

    def _follow(self, event, username, session=None):
        user = get_user_by_jid(event['from'].jid, session)
        contact = get_user_by_username(username, session)

        if not contact:
            body = 'User @%s not found.' % username
            self.xmpp.sendMessage(event['from'].jid, body, mfrom=self.jid, mtype='chat')
            return

        if user == contact:
            body = 'You can\'t follow youself.'
            self.xmpp.sendMessage(event['from'].jid, body, mfrom=self.jid, mtype='chat')
            return

        if contact in user.contacts:
            self.xmpp.sendMessage(
                user.jid,
                'You already follow @%s.' % username,
                mfrom = self.jid,
                mtype = 'chat'
            )
            return

        user.contacts.append(contact)
        session.commit()

        self.xmpp.sendMessage(
            user.jid,
            'Now you are following @%s.' % username,
            mfrom = self.jid,
            mtype = 'chat'
        )
        self.xmpp.sendMessage(
            contact.jid,
            'You have a new follower: @%s.' % user.username,
            mfrom = self.jid,
            mtype = 'chat'
        )

    def _whoami(self, event, session=None):
        user = get_user_by_jid(event['from'].jid, session)
        body = 'Username: %s\nJID: %s' % (user.username, user.jid)
        self.xmpp.sendMessage(user.jid, body, mfrom=self.jid, mtype='chat')

    def _direct_message(self, event, username, message, session=None):
        user = get_user_by_username(username, session)
        from_ = get_user_by_jid(event['from'].jid, session)

        event.payload.text = message

        if user:
            body = 'Direct message from @%s: %s' % (from_.username, message)
            self.send_message(user.jid, body, mfrom=self.jid, mtype='chat', payload=event.payload)
        else:
            body = 'User @%s not found.' % username
            self.send_message(from_.jid, body, mfrom=self.jid, mtype='chat', payload=event.payload)

    def _reply_message(self, event, username, message, session=None):
        user = get_user_by_username(username, session)
        from_ = get_user_by_jid(event['from'].jid, session)

        if user:
            body = 'Reply from @%s: %s' % (from_.username, message)
            self.send_message(user.jid, body, mfrom=self.jid, mtype='chat', payload=event.payload)
        else:
            body = 'User @%s not found.' % username
            self.send_message(from_.jid, body, mfrom=self.jid, mtype='chat', payload=event.payload)

    def _add_search(self, event, word, session=None):
        user = get_user_by_jid(event['from'].jid, session)
        try:
            neightbours = search.add_search(word, user.username, max_neightbours=21)
        except IntegrityError:
            message = 'You already watching for these terms.'
        else:
            message = 'Now you are looking for "%s" in all messages.' % word
            if neightbours:
                message += '\nThese users are watching for the same terms:\n@'
                message += '\n@'.join(neightbours[:20])
                if len(neightbours) == 21:
                    message += '\nand more...'

        self.xmpp.sendMessage(
            user.jid,
            message,
            mfrom = self.jid,
            mtype = 'chat'
        )

    def _remove_search(self, event, word, session=None):
        user = get_user_by_jid(event['from'].jid, session)
        search.remove_search(word, user.username)
        self.xmpp.sendMessage(user.jid, 'Search on "%s" was dropped' % word, mfrom=self.jid, mtype='chat')

    def _show_searches(self, event, session=None):
        user = get_user_by_jid(event['from'].jid, session)
        terms = session.query(SearchTerm).filter(SearchTerm.username == user.username)

        if terms.count() > 0:
            body = 'Your searches:\n' + '\n'.join(
                t.term for t in terms
            )
        else:
            body = 'You have no searches.'
        self.xmpp.sendMessage(user.jid, body, mfrom=self.jid, mtype='chat')

    def _show_help(self, event, session=None):
        user = get_user_by_jid(event['from'].jid, session)

        self.xmpp.sendMessage(user.jid, self._COMMANDS_HELP, mfrom=self.jid, mtype='chat')

    _COMMANDS = [
        (r'^me$', _whoami, '"me" - shows who you are, your username and jid (Jabber ID)'),
        (r'^ers$', _show_followers, '"ers" - shows your followers'),
        (r'^ing$', _show_contacts, '"ing" - shows who you follow'),
        (r'^f (?P<username>[-\w._]+)$', _follow, '"f username" - follow this user'),
        (r'^u (?P<username>[-\w._]+)$', _unfollow, '"u username" - unfollow this user'),
        (r'^d (?P<username>[-\w._]+) (?P<message>.*)$', _direct_message, '"d username message text" - send direct message to the user'),
        (r'^@(?P<username>[-\w._]+) (?P<message>.*)$', _reply_message, '"@username message text" - mention a user, a public message to a user'),
        (r'^s$', _show_searches, '"s" - show saved searches'),
        (r'^s (?P<word>.+)$', _add_search, '"s word" - save live search term'),
        (r'^us (?P<word>.+)$', _remove_search, '"us word" - delete live search term'),
        (r'^help$', _show_help, '"help" - show this help'),
    ]

    _COMMANDS_HELP = 'Cleartext microblog, version %s.\n\nCommands:\n  ' % __version__ \
        + '\n  '.join(help for regex, func, help in _COMMANDS) \
        + '\n\n Need more help? Go to the online help: http://www.cleartext.com/esm'

    _COMMANDS = [(re.compile(regex, re.IGNORECASE), func, help)
                 for regex, func, help in _COMMANDS]

    def _handle_commands(self, event, session):
        """Checks if event contains controls sequence.

        If it is, then True returned and command is processed,
        otherwise, method returns False.
        """
        message = event['body']

        for regex, func, help in self._COMMANDS:
            match = regex.match(message)
            if match is not None:
                func(self, event, session=session, **match.groupdict())
                return True

        return False


class ComponentXMPP(sleekxmpp.componentxmpp.ComponentXMPP):
    """Wrapper around sleekxmpp's component.

    This class used to stop all threads on disconnect.
    """

    def disconnect(self, reconnect=False):
        super(ComponentXMPP, self).disconnect(reconnect)
        if not reconnect:
            search.stop()


class Bot(Commands):
    def __init__(self, jid, password, server, port,
                 debug = False,
                 changelog_notifications = False,
                 nickname = 'Bot',
                 firstname = 'Cleartext Microblogging',
                 avatar = 'data/avatar.jpg',
                 max_tweet_length = None,
        ):
        QUEUE.set_bot(self)
        self.users = defaultdict(dict) # Cache for some user's info
        self._load_state()

        self.jid = jid
        self.domain = jid.split('.', 1)[1]

        self.xmpp = ComponentXMPP(jid, password, server, port)
        self.xmpp.add_event_handler("session_start", self.handle_xmpp_connected)
        self.xmpp.add_event_handler('presence_subscribe',
            self._handle_presence_subscribe)
        self.xmpp.add_event_handler('presence_probe',
            self._handle_presence_probe)
        self.xmpp.add_event_handler('presence_available',
            self._handle_presence_available)

        self.xmpp.add_event_handler('message', self._handle_message)

        for event in ['got_online', 'got_offline', 'changed_status']:
            self.xmpp.add_event_handler(event, self._handle_status_change)

        self.xmpp.add_event_handler('get_vcard', self._handle_get_vcard)

        ## BEGIN NEW
        self.xmpp.registerPlugin("xep_0030")
        self.xmpp.plugin['xep_0030'].identities['main'] = [
            dict(
                category = 'client',
                type = 'pc',
                name = firstname,
            )
        ]
        self.xmpp.registerPlugin("xep_0054")
        ## END NEW
        self.log = logging.getLogger('bot')
        self.debug = debug
        self.changelog_notifications = changelog_notifications

        self.nickname = nickname
        self.firstname = firstname
        self.avatar = avatar
        self.max_tweet_length = max_tweet_length

    def _load_state(self):
        state_filename = os.path.expanduser('~/.cleartext-bot.yml')

        self.state = None

        if os.path.exists(state_filename):
            with open(state_filename) as f:
                self.state = yaml.load(f)

        if not self.state:
            self.state = {'version': '0.0'}

    def _save_state(self):
        with open(os.path.expanduser('~/.cleartext-bot.yml'), 'w') as f:
            yaml.dump(self.state, f)

    def _send_changes(self, users):
        """Sends changes to users if bot have configured,

        Also, this method increments version number in the bot's state.
        """

        if self.changelog_notifications:
            changes = changelog.load()
            new_version = V(__version__)
            old_version = V(self.state['version'])

            if old_version < new_version:
                post = [
                    'Bot was upgraded to a new version %s.' % __version__,
                    'Compared with the previous version it has following changes:'
                ]
                for version, version_string, messages in changes:
                    if version <= old_version:
                        break

                    post.append('\nVersion %s:' % version_string)
                    for line in messages:
                        post.append('  * ' + line)

                for user in users:
                    self.send_message(
                        user.jid,
                        '\n'.join(post),
                        mfrom = self.jid,
                        mtype = 'chat'
                    )
        self.state['version'] = __version__

    def _handle_get_vcard(self, event):
        with open(self.avatar) as file:
            vcard = self.xmpp.plugin['xep_0054'].make_vcard(
                FN = self.firstname,
                NICKNAME = self.nickname,
                PHOTO = dict(
                    TYPE = 'image/jpeg',
                    BINVAL = base64.standard_b64encode(file.read()),
                )
            )
        self.xmpp.plugin['xep_0054'].return_vcard(event, vcard)

    def _send_presence(self, jid):
        """ Sends presence along with some extensions.
        """
        presence = self.xmpp.Presence(sfrom=self.jid, sto=jid)

        # vCard update
        vcard_update = ET.Element('{vcard-temp:x:update}x')
        photo = ET.SubElement(vcard_update, 'photo')
        photo.text = hashlib.sha1('random').hexdigest()

        presence.setPayload(vcard_update)

        # Chat status
        show = ET.Element('{%s}show' % self.xmpp.default_ns)
        show.text = 'chat'
        presence.setPayload(show)

        self.xmpp.send(presence)

    def _send_presence_probe(self, jid):
        self.xmpp.sendPresence(
            ptype = 'probe',
            pfrom = self.jid,
            pto = jid,
        )

    @db_session
    def handle_xmpp_connected(self, event, session=None):
        users = get_all_users(session)

        for user in users:
            self.log.debug('sending presence to jid "%s"' % user.jid)
            self._send_presence(user.jid)
            self._send_presence_probe(user.jid)

        self._send_changes(users)
        self._save_state()

    @db_session
    def _handle_message(self, event, session=None):
        try:
            if event['type'] == 'error':
                # Do nothing if this is error message from the server
                # or other client
                return

            payload = Payload(event, self, session)
            event.payload = payload

            if self._handle_commands(event, session) == False:
                self.handle_new_message(event, session)
        except Exception, e:
            self.log.exception('error during XMPP event processing')
            if self.debug:
                body = 'ERROR: %s' % e
                self.xmpp.sendMessage(event['from'].jid, body, mfrom=self.jid, mtype='chat')

    @db_session
    def _handle_status_change(self, event, session=None):
        # TODO think what to do on status change
        pass

    def _handle_presence_probe(self, event):
        self._send_presence(event['from'].jid)

    def _handle_presence_available(self, event):
        for part in event.getPayload():
            if part.tag == '{vcard-temp:x:update}x':
                el = part.find('{vcard-temp:x:update}photo')
                if el is not None:
                    self.users[event['from'].jid.split('@', 1)[0]]['photo'] = el.text

    def _handle_presence_subscribe(self, subscription):
        user_jid = subscription['from'].jid
        user_domain = user_jid.rsplit('@', 1)[1]

        if user_domain == self.domain:
            self.xmpp.sendPresenceSubscription(pto=user_jid, ptype='subscribed')
            self._send_presence(user_jid)
            self.xmpp.sendPresenceSubscription(pto=user_jid, ptype='subscribe')
        else:
            self.log.warning(
                'Access denied for user %s, because this bot service on the domain %s.' % \
                (user_jid, self.domain)
            )
            self.xmpp.sendPresenceSubscription(pto=user_jid, ptype='unsubscribed')

    def handle_new_message(self, event, session):
        text = event['body']
        from_user = get_user_by_jid(event['from'].jid, session)

        text_len = len(text)
        if self.max_tweet_length and text_len > self.max_tweet_length:
            self.send_message(
                from_user.jid,
                'Your message is longer than %s characters (%s chars). '
                'Your message has not been posted.' % (self.max_tweet_length, text_len),
                mfrom = self.jid,
                mtype = 'chat'
            )
            return

        try:
            tweet = Tweet(
                username = from_user.username,
                text = text,
            )
            session.add(tweet)
        except Exception:
            self.log.exception('can\'t save tweet')

        body = '@%s: %s' % (from_user.username, text)
        for subscriber in from_user.subscribers:
            self.send_message(subscriber.jid, body, mfrom=self.jid, mtype='chat', payload=event.payload)

        body = 'Mention by @%s: %s' % (from_user.username, text)
        for username in re.findall(r'\W@\w+', text):
            try:
                user = get_user_by_username(username[1:], session)
            except UserNotFound:
                continue
            if user not in from_user.subscribers:
                self.send_message(user.jid, body, mfrom=self.jid, mtype='chat', payload=event.payload)

        search.process_message(event)

    def send_message(self, mto, mbody,
            msubject=None, mtype=None, mhtml=None,
            mfrom=None, mnick=None, payload=[]):

        msg = self.xmpp.makeMessage(mto,mbody,msubject,mtype,mhtml,mfrom,mnick)
        for item in payload:
            msg.setPayload(item)
        self.xmpp.send(msg)

    def start(self):
        search.start(self)
        self.xmpp.connect()
        self.xmpp.process(threaded=False)

    def stop(self):
        search.stop()
        if self.xmpp.socket is not None:
            self.xmpp.disconnect()


trace_methods(Bot)
