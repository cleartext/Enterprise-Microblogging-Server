import hashlib
from sleekxmpp.stanza.message import Message, ET


class TaskQueue(object):
    """Inprocess task queue.

    It is not a real queue yet, just an
    imitation, because http frontend and
    jabber backend work in the same process.
    """

    def __init__(self):
        self.bot = None

    def set_bot(self, bot):
        self.bot = bot

    def add(self, name, *args, **kwargs):
        """ Accepts new task in form (name, args, kwargs) """
        func = getattr(self, 'do_' + name, None)
        if func is not None:
            func(*args, **kwargs)

    def do_post(self, text=None, user=None):
        if self.bot:
            if user.vcard and user.vcard.PHOTO:
                avatar_hash = hashlib.sha1(user.vcard.PHOTO.BINVAL.text).hexdigest()
            else:
                avatar_hash = ''

            event = Message(
                stream = self.bot.xmpp, xml=ET.fromstring("""
<message to="%(bot_jid)s" from="%(user_jid)s" id="1" type="chat" xmlns="jabber:component:accept">
    <body>%(text)s</body>
</message>""" % dict(
    bot_jid = self.bot.jid,
    user_jid = user.jid,
    username = user.username,
    text = text,
    avatar_hash = avatar_hash,
)))
            self.bot._handle_message(event)


QUEUE = TaskQueue()
