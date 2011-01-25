import datetime

from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Unicode, UnicodeText, \
                       DateTime, Table, ForeignKey, Boolean, \
                       Integer
from sqlalchemy.orm import relationship
from pdb import set_trace

Base = declarative_base()

subscribers_t = Table('subscribers', Base.metadata,
    Column('user', Unicode, ForeignKey('users.username')),
    Column('subscriber', Unicode, ForeignKey('users.username'))
)


class VCard(Base):
    __tablename__ = 'vcard'

    username = Column(Unicode, primary_key=True)
    vcard = Column(UnicodeText)
    created_at = Column(DateTime)


class User(Base):
    __tablename__ = 'users'

    username = Column(Unicode, ForeignKey('vcard.username'), primary_key=True)
    password = Column(UnicodeText)
    created_at = Column(DateTime)
    jid = Column(Unicode, unique=True)
    presence = Column(Boolean)

    subscribers = relationship(
        'User',
        secondary = subscribers_t,
        backref = 'contacts',
        primaryjoin = 'User.username == subscribers.c.user',
        secondaryjoin = 'subscribers.c.subscriber == User.username',
    )

    friend_tweets = relationship(
        'Tweet',
        secondary = subscribers_t,
        order_by = 'desc(Tweet.id)',
        primaryjoin = 'User.username == subscribers.c.subscriber',
        secondaryjoin = 'subscribers.c.user == Tweet.username',
    )

    tweets = relationship(
        'Tweet',
        order_by = 'desc(Tweet.id)',
        backref = 'user',
    )

    _vcard = relationship('VCard', backref='user')

    @property
    def vcard(self):
        from microblog.et_accessor import Accessor
        from microblog.bot import ET
        if self._vcard:
            return Accessor(ET.fromstring(self._vcard.vcard))
        return None


class SearchTerm(Base):
    __tablename__ = 'search_terms'
    term = Column(Unicode, primary_key=True)
    username = Column(Unicode, primary_key=True)

    def __init__(self, term, username):
        self.term = term
        self.username = username


class Tweet(Base):
    __tablename__ = 'tweets'
    id = Column(Integer, primary_key=True)
    username = Column(Unicode, ForeignKey('users.username'), ForeignKey('subscribers.user'))
    text = Column(Unicode)
    created_at = Column(DateTime)

    def __init__(self, username, text):
        self.username = username
        self.text = text
        self.created_at = datetime.datetime.utcnow()
