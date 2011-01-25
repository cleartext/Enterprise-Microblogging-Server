import copy
import threading
import logging
import itertools

from Queue import Queue
from collections import defaultdict
from microblog.db import db_session
from microblog.db_helpers import \
    get_user_by_jid, \
    get_user_by_username
from microblog.models import SearchTerm
from sqlalchemy.orm.exc import NoResultFound


class Sentinel(object): pass


class SearchCache(object):
    """This class holds all search terms and usernames which are waiting results."""

    def __init__(self):
        self._terms = {}

    def __getitem__(self, phrase):
        """ Each phrase splitted and saved along with usernames.
        """
        if phrase not in self._terms:
            self._terms[phrase] = (
                tuple(
                    filter(
                        None,
                        (word.strip() for word in phrase.split())
                    )
                ),
                set()
            )
        return self._terms[phrase]

    def items(self):
        return self._terms.itervalues()


_searches = SearchCache()
_queue = Queue()


@db_session
def add_search(word, username, max_neightbours=20, session=None):
    """Adds a new search for user.

    Returns no more than 'max_neightbours' users who search same terms.
    """
    word = word.lower()

    log = logging.getLogger('search')
    log.debug('New search term "%s" for username "%s"' % (word, username))
    neightbours = list(itertools.islice(_searches[word][1], max_neightbours))
    _searches[word][1].add(username)

    session.add(SearchTerm(word, username))
    return neightbours


@db_session
def remove_search(word, username, session=None):
    word = word.lower()

    log = logging.getLogger('search')
    log.debug('Removing search term "%s" for username "%s"' % (word, username))
    _searches[word][1].discard(username)

    try:
        term = session.query(SearchTerm).filter(SearchTerm.term == word).filter(
            SearchTerm.username == username
        ).one()
    except NoResultFound:
        return

    session.delete(term)


def process_message(event):
    if event.getType() == 'chat':
        log = logging.getLogger('search')
        log.debug('Adding text to the queue: "%s"' % event['body'])
        _queue.put(event)


def stop():
    log = logging.getLogger('search')
    log.debug('Trying to stop search thread')
    _queue.put(Sentinel)


@db_session
def start(bot, session=None):
    log = logging.getLogger('search')

    log.debug('Loading search terms.')

    count = 0
    for term in session.query(SearchTerm).all():
        _searches[term.term][1].add(term.username)
        count += 1
    log.debug('%d terms were loaded' % count)

    @db_session
    def _process_event(event, session=None):
        log.debug('Processing word "%s"' % event['body'])

        text = event['body']
        from_user = get_user_by_jid(event['from'].jid, session)

        body = 'Search: @%s says "%s"' % (from_user.username, text)

        num_recipients = 0

        text = text.lower()
        receivers = set()
        terms = {} # user to terms hash

        def all_in_text(words, text):
            return all(map(lambda word: word in text, words))

        for words, users in _searches.items():
            if all_in_text(words, text):
                receivers.update(users)
                for user in users:
                    terms[user] = words

        for username in receivers:
            user = get_user_by_username(username, session)
            if user not in from_user.subscribers and \
                    user != from_user:
                payload = copy.deepcopy(event.payload)

                for term in terms[username]:
                    payload.add_node('searchTerm', term)

                num_recipients += 1
                bot.send_message(user.jid, body, mfrom=bot.jid, mtype='chat', payload=payload)

        log.debug('This message was received by %s recipients.' % num_recipients)


    def _worker():
        log.debug('Starting search thread.')
        while True:
            event = _queue.get()

            if event is Sentinel:
                log.debug('Stopping search thread.')
                break

            try:
                _process_event(event)
            except:
                log.exception('Error during _process_event')


    thread = threading.Thread(target = _worker)
    thread.start()

