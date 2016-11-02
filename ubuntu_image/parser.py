"""gadget.yaml parsing and validation."""

import re
import attr

from enum import Enum
from io import StringIO
from operator import methodcaller
from ubuntu_image.helpers import GiB, MiB, as_size, transform
from uuid import UUID
from voluptuous import Any, Coerce, Invalid, Match, Optional, Required, Schema
from yaml import load
from yaml.loader import SafeLoader
from yaml.parser import ParserError


# By default PyYAML allows duplicate mapping keys, even though the YAML spec
# prohibits this.  We can't validate this after parsing because PyYAML just
# gives us a normal dictionary, which of course does not have duplicate keys.
# We use the basic YAML SafeLoader but override the mapping constructor to
# raise an exception if we see a key twice.

class StrictLoader(SafeLoader):
    def construct_mapping(self, node):
        pairs = self.construct_pairs(node)
        mapping = {}
        for key, value in pairs:
            if key in mapping:
                raise ValueError('Duplicate key: {}'.format(key))
            mapping[key] = value
        return mapping


StrictLoader.add_constructor(
    'tag:yaml.org,2002:map', StrictLoader.construct_mapping)


class BootLoader(Enum):
    uboot = 'u-boot'
    grub = 'grub'


class VolumeSchema(Enum):
    mbr = 'mbr'
    gpt = 'gpt'


class FileSystemType(Enum):
    none = 'none'
    ext4 = 'ext4'
    vfat = 'vfat'


class Enumify:
    def __init__(self, enum_class, msg=None, preprocessor=None):
        self.enum_class = enum_class
        self.preprocessor = preprocessor

    def __call__(self, v):
        # Voluptuous will catch any exceptions.
        return self.enum_class[
            v if self.preprocessor is None
            else self.preprocessor(v)
            ]


def Size32bit(v):
    """Coerce size to being a 32 bit integer."""
    return as_size(v, max=GiB(4))


def Id(v):
    """Coerce to either a hex UUID, a 2-digit hex value."""
    if isinstance(v, int):
        # Okay, here's the problem.  If the id value is something like '80' in
        # the yaml file, the yaml parser will turn that into the decimal
        # integer 80, but that's really not what we want!  We want it to be
        # the hex value 0x80.  So we have to turn it back into a string and
        # allow the 2-digit validation matcher to go from there.
        if v >= 100 or v < 0:
            raise ValueError(str(v))
        v = '{:02d}'.format(v)
    try:
        return UUID(hex=v)
    except ValueError:
        pass
    mo = re.match('^[a-fA-F0-9]{2}$', v)
    if mo is None:
        raise ValueError(v)
    return mo.group(0).upper()


def HybridId(v):
    """Like above, but allows for hybrid Ids."""
    if isinstance(v, str):
        code, comma, guid = v.partition(',')
        if comma == ',':
            # Two digit hex code must appear before GUID.
            if len(code) != 2 or len(guid) != 36:
                raise ValueError(v)
            hex_code = Id(code)
            guid_code = Id(guid)
            return hex_code, guid_code
    return Id(v)


def RelativeOffset(v):
    """From the spec:

    It may be specified relative to another structure item with the
    syntax ``label+1234``.
    """
    label, plus, offset = v.partition('+')
    if len(label) == 0 or plus != '+' or len(offset) == 0:
        raise ValueError(v)
    return label, Size32bit(offset)


GadgetYAML = Schema({
    Optional('device-tree-origin', default='gadget'): str,
    Optional('device-tree'): str,
    Required('volumes'): {
        Match('^[-a-zA-Z0-9]+$'): Schema({
            Optional('schema', default=VolumeSchema.gpt):
                Enumify(VolumeSchema),
            Optional('bootloader'): Enumify(
                BootLoader, preprocessor=methodcaller('replace', '-', '')),
            Optional('id'): Coerce(Id),
            Required('structure'): [Schema({
                Optional('name'): str,
                Optional('offset'): Coerce(as_size),
                Optional('offset-write'): Any(
                    Coerce(Size32bit), RelativeOffset),
                Required('size'): Coerce(as_size),
                Required('type'): Any('mbr', Coerce(HybridId)),
                Optional('id'): Coerce(UUID),
                Optional('filesystem', default=FileSystemType.none):
                    Enumify(FileSystemType),
                Optional('filesystem-label'): str,
                Optional('content'): Any(
                    [Schema({
                        Required('source'): str,
                        Required('target'): str,
                        })
                    ],                                  # noqa: E124
                    [Schema({
                        Required('image'): str,
                        Optional('offset'): Coerce(as_size),
                        Optional('offset-write'): Any(
                            Coerce(Size32bit), RelativeOffset),
                        Optional('size'): Coerce(as_size),
                        })
                    ],
                )
            })]
        })
    }
})


@attr.s
class ContentSpecA:
    source = attr.ib()
    target = attr.ib()

    @classmethod
    def from_yaml(cls, content):
        source = content['source']
        target = content['target']
        return cls(source, target)


@attr.s
class ContentSpecB:
    image = attr.ib()
    offset = attr.ib()
    offset_write = attr.ib()
    size = attr.ib()

    @classmethod
    def from_yaml(cls, content):
        image = content['image']
        offset = content.get('offset')
        offset_write = content.get('offset-write')
        size = content.get('size')
        return cls(image, offset, offset_write, size)


@attr.s
class StructureSpec:
    name = attr.ib()
    offset = attr.ib()
    offset_write = attr.ib()
    size = attr.ib()
    type = attr.ib()
    id = attr.ib()
    filesystem = attr.ib()
    filesystem_label = attr.ib()
    content = attr.ib()


@attr.s
class VolumeSpec:
    schema = attr.ib()
    bootloader = attr.ib()
    id = attr.ib()
    structures = attr.ib()


@attr.s
class GadgetSpec:
    device_tree_origin = attr.ib()
    device_tree = attr.ib()
    volumes = attr.ib()


@transform((KeyError, Invalid, ParserError), ValueError)
def parse(stream_or_string):
    """Parse the YAML read from the stream or string.

    The YAML is parsed and validated against the schema defined in
    docs/gadget-yaml.rst.

    :param stream_or_string: Either a string or a file-like object containing
        a gadget.yaml specification.  If stream is given, it must be open for
        reading with a UTF-8 encoding.
    :type stream_or_string: str or file-like object
    :return: A specification of the gadget.
    :rtype: GadgetSpec
    :raises ValueError: If the schema is violated.
    """
    # Do the basic schema validation steps.  There some interdependencies that
    # require post-validation.  E.g. you cannot define the fs-type if the role
    # is ESP.
    stream = (StringIO(stream_or_string)
              if isinstance(stream_or_string, str)
              else stream_or_string)
    yaml = load(stream, Loader=StrictLoader)
    validated = GadgetYAML(yaml)
    device_tree_origin = validated.get('device-tree-origin')
    device_tree = validated.get('device-tree')
    volume_specs = {}
    bootloader_seen = False
    # This item is a dictionary so it can't possibly have duplicate keys.
    # That's okay because our StrictLoader above will already raise an
    # exception if it sees a duplicate key.
    for image_name, image_spec in validated['volumes'].items():
        schema = image_spec['schema']
        bootloader = image_spec.get('bootloader')
        bootloader_seen |= (bootloader is not None)
        image_id = image_spec.get('id')
        structures = []
        last_offset = 0
        for structure in image_spec['structure']:
            name = structure.get('name')
            offset = structure.get('offset')
            offset_write = structure.get('offset-write')
            size = structure['size']
            structure_type = structure['type']
            # Validate structure types.  These can be either GUIDs, two hex
            # digits, hybrids, or the special 'mbr' type.  The basic syntactic
            # validation happens above in the Voluptuous schema, but here we
            # need to ensure cross-attribute constraints.  Specifically,
            # hybrids and 'mbr' are allowed for either schema, but GUID-only
            # is only allowed for GPT, while 2-digit-only is only allowed for
            # MBR.  Note too that 2-item tuples are also already ensured.
            if (isinstance(structure_type, UUID) and
                    schema is not VolumeSchema.gpt):
                raise ValueError('GUID structure type with non-GPT')
            elif (isinstance(structure_type, str) and
                    structure_type != 'mbr' and
                    schema is not VolumeSchema.mbr):
                raise ValueError('MBR structure type with non-MBR')
            # XXX: Ensure the special case of the 'mbr' type doesn't extend
            # beyond the confines of the mbr.
            if not offset and structure_type != 'mbr' and last_offset < MiB(1):
                offset = MiB(1)
            if not offset:
                offset = last_offset
            last_offset = offset + size
            # Extract the rest of the structure data.
            structure_id = structure.get('id')
            filesystem = structure['filesystem']
            if (structure_type == 'mbr' and
                    filesystem is not FileSystemType.none):
                raise ValueError('mbr type must not specify a file system')
            filesystem_label = structure.get('filesystem-label', name)
            content = structure.get('content')
            content_specs = []
            content_spec_class = (
                ContentSpecB if filesystem is FileSystemType.none
                else ContentSpecA)
            if content is not None:
                for item in content:
                    content_specs.append(content_spec_class.from_yaml(item))
            structures.append(StructureSpec(
                name, offset, offset_write, size,
                structure_type, structure_id, filesystem, filesystem_label,
                content_specs))
        volume_specs[image_name] = VolumeSpec(
            schema, bootloader, image_id, structures)
    if not bootloader_seen:
        raise ValueError('No bootloader volume named')
    return GadgetSpec(device_tree_origin, device_tree, volume_specs)
