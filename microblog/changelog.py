import yaml
import os.path
from pkg_resources import parse_version as V


def load():
    changes = yaml.load(
        open(
            os.path.join(
                os.path.dirname(__file__),
                'changelog.yml'
            )
        )
    )
    changes = [(V(key), key, value) for key,value in changes.iteritems()]
    return sorted(changes, key=lambda x: x[0], reverse=True)


def current_version():
    changes = load()
    return changes[0][1]

