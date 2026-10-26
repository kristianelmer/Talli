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


def _compile_packaged_schema(raw,resources):
    """Resolve only explicitly packaged XSD imports; never a file or network.

    Keys are exact import locations from the integrity-checked upstream schema.
    There is no basename fallback, URI normalization or caller XML resolution.
    """
    class PackagedResources(etree.Resolver):
        def resolve(self,url,public_id,context):
            if url not in resources:raise ValueError('Unpackaged Tax schema import is forbidden.')
            return self.resolve_string(resources[url],context)
    parser=etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True,
        huge_tree=False,recover=False)
    parser.resolvers.add(PackagedResources())
    root=etree.fromstring(raw,parser)
    if root.getroottree().docinfo.doctype:raise ValueError('Schema document types are forbidden.')
    return etree.XMLSchema(root)
