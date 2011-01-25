#########################################################
# Title: Simple ElementTree accessor                    #
# Author: Alexander Artemenko <svetlyak.40wt@gmail.com> #
# Site: http://aartemenko.com                           #
# License: New BSD License                              #
#########################################################


class Accessor(object):
    """Easy to use ElementTree accessor."""

    def __init__(self, xml):
        self.xml = xml

    def __repr__(self):
        return '<Element %s>' % self.xml.tag

    def __unicode__(self):
        return self.xml.text or ''

    def __iter__(self):
        return iter(self.xml)

    def __getattribute__(self, name):
        """
>>> from xml.etree import ElementTree as ET
>>> xml = ET.fromstring('<a b="blah"><c id="1"/><c id="2"><d>Hello</d></c></a>')
>>> a = Accessor(xml)
>>> a.b
'blah'
>>> a.c
[<Element c>, <Element c>]
>>> a.c[1].d
<Element d>
>>> a.c[1].d.text
'Hello'
>>> ET.tostring(a)
'<a b="blah"><c id="1" /><c id="2"><d>Hello</d></c></a>'
"""
        if name == 'xml':
            return object.__getattribute__(self, name)

        self_tag = self.xml.tag
        if self_tag[0] == '{':
            el_name = self_tag[:self_tag.rfind('}') + 1] + name
        else:
            el_name = name

        elements = self.xml.findall(el_name)
        l = len(elements)
        if l == 1:
            return Accessor(elements[0])
        elif l > 1:
            return map(Accessor, elements)

        if self.xml.attrib.has_key(name):
            return self.xml.attrib[name]

        if hasattr(self.xml, name):
            return getattr(self.xml, name)
        return ''
