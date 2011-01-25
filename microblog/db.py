import logging

from functools import wraps
from pdb import set_trace
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.interfaces import PoolListener
from sqlalchemy.orm import sessionmaker

Session = sessionmaker()


class DebugListener(PoolListener):
    def __init__(self):
        self._log = logging.getLogger('pool-status')

    def connect(self, dbapi_con, con_record):
        self._log.debug('connect: ' + con_record._ConnectionRecord__pool.status())

    def checkin(self, dbapi_con, con_record):
        self._log.debug('checkin: ' + con_record._ConnectionRecord__pool.status())

    def checkout(self, dbapi_con, con_record, con_proxy):
        self._log.debug('checkout: ' + con_record._ConnectionRecord__pool.status())



def init(cfg):
    """This function should be called before Session use.

    Input is a dict like object with databases settings from the config.
    """
    database_uri = 'mysql://%(username)s:%(password)s@%(host)s/%(dbname)s' % cfg

    opts = dict(
        pool_recycle = cfg.get('pool_recycle', 3600),
        pool_size = cfg.get('pool_size', 5),
        max_overflow = cfg.get('max_overflow', 0),
    )

    if cfg.get('debug', False):
        opts['echo'] = True
        opts['listeners'] = [DebugListener()]

    engine = create_engine(database_uri, **opts)
    Session.configure(bind=engine)


def db_session(func):
    """Decrator, passes db session object to the function."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if 'session' not in kwargs:
            session = Session()
            kwargs['session'] = session
            try:
                result = func(*args, **kwargs)
                session.commit()
                return result
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

    return wrapper

