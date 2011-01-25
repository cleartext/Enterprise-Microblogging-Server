"""
Different database helpers, to retrive
information about users.
"""
from microblog.models import User
from microblog.exceptions import UserNotFound

def get_user_by_jid(jid, session):
    jid = jid.split('/', 1)[0]
    user = session.query(User).filter(User.jid==jid).scalar()
    if user is None:
        raise UserNotFound('User with jid "%s" not found.' % jid)
    return user


def get_all_users(session):
    return session.query(User)


def get_user_by_username(username, session):
    user = session.query(User).filter(User.username==username).scalar()
    if user is None:
        raise UserNotFound('User with username "%s" not found.' % username)
    return user

