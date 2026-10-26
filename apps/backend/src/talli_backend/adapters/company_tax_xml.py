"""Strict offline XML parsing shared by pinned Tax schema adapters."""
from lxml import etree


class _DenyExternalResources(etree.Resolver):
    def resolve(self,url,public_id,context):
        raise ValueError('External XML resources are forbidden.')


def _parse(raw):
    parser=etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True,
        huge_tree=False,recover=False,remove_comments=True,remove_pis=True)
    parser.resolvers.add(_DenyExternalResources())
    root=etree.fromstring(raw,parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError('Document type declarations are forbidden.')
    return root
