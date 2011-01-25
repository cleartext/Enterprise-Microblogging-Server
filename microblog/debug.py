from microblog.db import Session
from microblog.models import *
from microblog.server import init

init()
s = Session()
