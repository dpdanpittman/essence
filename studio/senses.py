"""The senses and sense verbs the engine may use, honouring every on/off key.

``providers(cfg)`` gives the enabled senses (``sky``, ``body``, ``house``,
``song``). ``verbs(cfg)`` gives the enabled sense verbs (``window``, ``sun``,
``temperature``, ``song``, ``read``). Engine verbs live in ``journal.py``.
"""

from . import body, house, reading, sky, song


def providers(cfg) -> list:
    out = []
    for module in (sky, body, house, song):
        s = module.sense(cfg)
        if s is not None:
            out.append(s)
    return out


def verbs(cfg) -> list:
    out = []
    out.extend(sky.verb_specs(cfg))
    out.extend(body.verb_specs(cfg))
    out.extend(song.verb_specs(cfg))
    out.extend(reading.verb_specs(cfg))
    return out
