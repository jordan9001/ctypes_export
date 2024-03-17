from binaryninja import *
import enum

header_template = """# generated from ctypes_export plugin
# report issues to https://github.com/jordan9001/ctypes_export/issues
import enum
import ctypes

"""

structunion_declaration_template = """class {prefix}{typename}({kind}):
    _pack_ = 1

"""

structunion_template = """class {prefix}{typename}({kind}):
    _pack_ = 1
    _fields_ = [
{items}    ]

"""

structunion_definition_template = """{prefix}{typename}._fields_ = [
{items}    ]

"""

structunion_line_template = """        ('{name}', {equiv}),
"""

enum_template = """class {prefix}{typename}_ENUM(enum.IntEnum):
{items}

{prefix}{typename} = ctypes.c_uint{intsz}
"""

enum_line_template = """    {name} = 0x{val:x}
"""

alias_declaration_template = """# Forward declaration for {prefix}{typename}
# {real}
{prefix}{typename} = {equiv}

"""

alias_template = """{prefix}{typename} = {equiv}

"""

markdown_template = """
```py
{report}
```
"""

class TypeKind(enum.Enum):
    STRUCT = 1
    UNION = 2
    ENUM = 3
    ALIAS = 4

    def baseclass(self):
        if self == TypeKind.STRUCT:
            return "ctypes.Structure"
        if self == TypeKind.UNION:
            return "ctypes.Union"
        if self == TypeKind.ENUM:
            return "enum.IntEnum"
        raise KeyError(f"No baseclass for {self}")

def get_type_kind(bv, tobj, tname):
    tobj_type = type(tobj)
    
    if tobj_type == EnumerationType:
        return TypeKind.ENUM

    if tobj_type == StructureType:
        if tobj.type == StructureVariant.UnionStructureType:
            return TypeKind.UNION
        return TypeKind.STRUCT

    if tobj_type == NamedTypeReferenceType:
        return TypeKind.ALIAS

    if tobj_type in [ArrayType, BoolType, CharType, FloatType, FunctionType, IntegerType, PointerType, VoidType, WideCharType]:
        return TypeKind.ALIAS
    
    raise NotImplementedError(f"Unimplemented export of type with tobj_type {tobj_type}")

def make_anon_name(structmem, parent):
    name = f'{parent}__0x{structmem.offset:x}'
    return name

def get_structunion_preitems(bv, tobj, tname, prefix):
    report = ""
    # define anonymous structures and unions for this type
    for m in tobj.members:
        if type(m.type) == StructureType:
            # this is not a NamedTypeReferenceType so it must be anonymous
            name = make_anon_name(m, tname)
            report += full_definition(bv, name, m.type, prefix)
        #TODO handle unnamed structures used in pointer, arrays, functions
    
    return report

def structunion_line(structmem, parent, prefix, comment=""):
    name = structmem.name
    if len(name) == 0:
        name = f"__0x{structmem.offset:x}"

    equiv = None
    mobj_type = type(structmem.type)

    # if it is a structure or enum or named type, we can use our name
    if mobj_type == NamedTypeReferenceType:
        # use the name
        equiv = f"{prefix}{structmem.type.name}"
    elif mobj_type == StructureType:
        equiv = prefix + make_anon_name(structmem, parent)
    elif mobj_type == EnumerationType:
        tref = structmem.type.registered_name
        if tref is None:
            raise NotImplementedError("Unhandled case, raw enumeration type in structure member with no registered name")
        equiv = f"{prefix}{tref.name}"
    else:
        # ArrayType, BoolType, CharType, FloatType, FunctionType, IntegerType, PointerType, VoidType, WideCharType
        equiv = get_ctypes_equiv(structmem.type, prefix)

    if len(comment) > 0:
        comment = '# ' + comment
    return structunion_line_template.format(name=name, equiv=equiv, comment=comment)

def get_union_items(tobj, tname, prefix):
    items = ""

    for m in tobj.members:
        items += structunion_line(m, tname, prefix)

    return items

def get_struct_items(tobj, tname, prefix):
    items = ""
    # define fields
    offset = 0
    for m in tobj.members:
        if offset > m.offset:
            raise RuntimeError(f"Offsets disagree in structure?\n{offset} {m.offset}\n{repr(tobj.members)}")
        while offset < m.offset:
            # add padding
            items += structunion_line_template.format(name=f"pad_0x{offset:x}", equiv="ctypes.c_uint8")
            offset += 1

        # add item
        items += structunion_line(m, tname, prefix, comment=f"0x{offset:x}")
        offset += m.type.width
        
    # pad at end
    while offset < tobj.width:
        items += structunion_line_template.format(name=f"pad_0x{offset:x}", equiv="ctypes.c_uint8")
        offset += 1

    return items

def get_enum_items(tobj):
    # define enum options
    items = ""
    for m in tobj.members:
        items += enum_line_template.format(name=m.name, val=m.value)

    return items

def equiv_basetype(tobj, prefix, declared, gt):
    # tobj should always be a NamedTypeReferenceType in this function
    # deref all the way and get the best fit
    while type(tobj) == NamedTypeReferenceType:
        if tobj.name in declared:
            return prefix + tobj.name
        tobj = gt(tobj.name)

    # now, depending on the type, we can set something up
    if type(tobj) == StructureType:
        # I guess just say it is an array of bytes of a certain size?
        return f"ctypes.c_uint8 * {tobj.width}"
    if type(tobj) == EnumerationType:
        if tobj.registered_name is None or tobj.registered_name.name not in declared:
            return f"ctypes.c_uint{tobj.width * 8}"
        else:
            return prefix + tobj.registered_name.name

    # otherwise drill down a bit more as possible
    return get_ctypes_equiv(tobj, prefix, declared, gt)

def get_ctypes_equiv(tobj, prefix, declared=None, gt=None):
    # get ctypes equivalent string
    # if declared is not None, it means we want to do our best, but fall back to base types

    tobj_type = type(tobj)
    if tobj_type == NamedTypeReferenceType:
        if declared is not None and tobj.name not in declared:
            return equiv_basetype(tobj, prefix, declared, gt)
        return f"{prefix}{tobj.name}"
    elif tobj_type == ArrayType:
        subtype = get_ctypes_equiv(tobj.element_type, prefix, declared, gt)
        return f"({subtype}) * {tobj.count}"
    elif tobj_type in [BoolType, CharType, IntegerType, WideCharType]:
        signed = False
        if tobj_type == IntegerType:
            signed = tobj.signed

        width = tobj.width
        if width not in [1,2,4,8]:
            raise NotImplementedError(f"got a int-like with a weird width: {width} {repr(tobj)}")

        return f"ctypes.c_{'u' if not signed else ''}int{width * 8}"
    elif tobj_type == PointerType:
        # check for void target
        targ = tobj.target
        if type(targ) == VoidType:
            return "ctypes.c_void_p"
        if declared is not None and type(targ) == NamedTypeReferenceType and targ.name not in declared:
            return "ctypes.c_void_p"

        subtype = get_ctypes_equiv(tobj.target, prefix, declared, gt)
        return f"ctypes.POINTER({subtype})"
    elif tobj_type == FloatType:
        floatsz = "float"
        if tobj.width == 4:
            floatsz = "float"
        elif tobj.width == 8:
            floatsz = "double"
        else:
            raise NotImplementedError(f"Unknown float with width {tobj.width} {repr(tobj)}")
        return f"ctypes.c_{floatsz}"
    elif tobj_type == FunctionType:
        restype = get_ctypes_equiv(tobj.return_value, prefix, declared, gt)
        argtypes = ','.join([get_ctypes_equiv(x.type, prefix, declared, gt) for x in tobj.parameters])
        #TODO calling convention information instead of just CFUNCTYPE
        return f"ctypes.CFUNCTYPE(({restype}), {argtypes})"
    elif tobj_type == VoidType:
        # probably a function return value
        # just use void* whatever
        return "ctypes.c_void_p"

    else:
        # not in NamedTypeReference, ArrayType, BoolType, CharType, FloatType, FunctionType, IntegerType, PointerType, WideCharType
        raise NotImplementedError(f"Unimplemented type type in get_ctypes_equiv: {repr(tobj)}")

def declaration(bv, typename, typeobj, prefix, declared, gt):
    kind = get_type_kind(bv, typeobj, typename)

    if kind == TypeKind.ENUM:
        return full_definition(bv, typename, typeobj, prefix), False

    if kind == TypeKind.ALIAS:
        real = full_definition(bv, typename, typeobj, prefix)
        # I can't forward declare aliases the way I am doing them
        # but I can't full define them, because they can have dependencies
        # so we alias to some equivalent type that is the same width
        fake_equiv = get_ctypes_equiv(typeobj, prefix, declared, gt)

        return alias_declaration_template.format(real=real, prefix=prefix, typename=typename, equiv=fake_equiv), True

    # STRUCT and UNION
    return structunion_declaration_template.format(prefix=prefix, typename=typename, kind=kind.baseclass()), True

def part_definition(bv, typename, typeobj, prefix):
    kind = get_type_kind(bv, typeobj, typename)

    if kind == TypeKind.ENUM:
        raise Exception(f"Unexpected type needing a partial definition? {kind}")

    if kind == TypeKind.ALIAS:
        # overwrite the stand in that has the equivalent sized types
        return full_definition(bv, typename, typeobj, prefix)

    preitems = get_structunion_preitems(bv, typeobj, typename, prefix)

    items = ""
    if kind == TypeKind.STRUCT:
        items = get_struct_items(typeobj, typename, prefix)
    elif kind == TypeKind.UNION:
        items = get_union_items(typeobj, typename, prefix)

    # this doesn't always work, if the type or an alias are used as a non-pointer before this
    return preitems + structunion_definition_template.format(prefix=prefix, typename=typename, items=items)

def full_definition(bv, typename, typeobj, prefix):
    kind = get_type_kind(bv, typeobj, typename)

    if kind in [TypeKind.STRUCT, TypeKind.UNION]:

        preitems = get_structunion_preitems(bv, typeobj, typename, prefix)

        items = ""
        if kind == TypeKind.STRUCT:
            items = get_struct_items(typeobj, typename, prefix)
        elif kind == TypeKind.UNION:
            items = get_union_items(typeobj, typename, prefix)

        return preitems + structunion_template.format(prefix=prefix, typename=typename, kind=kind.baseclass(), items=items)

    if kind == TypeKind.ENUM:
        items = get_enum_items(typeobj)
        return enum_template.format(prefix=prefix, typename=typename, items=items, intsz=(typeobj.width * 8))

    if kind == TypeKind.ALIAS:
        equiv = get_ctypes_equiv(typeobj, prefix)
        return alias_template.format(prefix=prefix, typename=typename, equiv=equiv)
    raise NotImplementedError(f"Unimplemented definition for kind {kind}")

def get_type_dbg(bv, typename):
    res = bv.debug_info.get_types_by_name(typename)
    if len(res) == 0:
        return None
    if len(res) > 1:
        print(f"Warning: type '{typename}' is provided by multiple debug parsers: {', '.join([x[0] for x in res])}")

    return res[0][1]

def get_type(bv, typename):
    # should we check and warn if there is a _1 variant?
    return bv.get_type_by_name(typename)

def get_type_deps(bv, tobj, tname):
    deps = set()
    tobj_type = type(tobj)

    #ArrayType, BoolType, CharType, EnumerationType, FloatType, FunctionType, IntegerType, NamedTypeReferenceType, PointerType, StructureType, VoidType, WideCharType

    if tobj_type in [ArrayType, FunctionType, PointerType, StructureType]:
        # go through children
        # do we need to be more specific? for example StructureType has .members ArrayType has .element_type, PointerType has .target, ...
        for d_tobj in tobj.children:
            if type(d_tobj) == NamedTypeReferenceType:
                # if this is a reference, add a dependency on the name
                deps.add(d_tobj.name)
                continue
            if d_tobj.registered_name != None:
                # if this is known by a name, we want to capture that 
                deps.add(d_tobj.registered_name.name)
                continue
            # ignore base type deps with no name
            if type(d_tobj) in [BoolType, CharType, EnumerationType, FloatType, IntegerType, VoidType, WideCharType]:
                continue

            # otherwise we need to recurse and get the sub-types for dependencies
            deps |= get_type_deps(bv, d_tobj, None)
    elif tobj_type == NamedTypeReferenceType:
        # depend on the next step by it's name
        deps.add(tobj.name)
    elif tobj_type in [BoolType, CharType, EnumerationType, FloatType, IntegerType, VoidType, WideCharType]:
        # base types, no dependencies
        pass
    else:
        raise NotImplementedError(f"Getting Dependancies not implemented for type type {str(tobj_type)}")

    return deps

def export_some(bv):
    types_f = MultilineTextField("Type Names (newline separated)")
    rec_f = ChoiceField("Include Dependant Types", ["Yes", "No"], 0)
    dbg_f = ChoiceField("Use Only Debug Types", ["Yes", "No"], 1)
    pre_f = TextLineField("Class Name Prefix", "")
    out_f = OpenFileNameField("Output File", ".py", "")
    get_form_input([types_f, rec_f, dbg_f, pre_f, out_f], "Type Export")

    if types_f.result is None or len(types_f.result) == 0:
        return False

    typenames = [x.strip() for x in types_f.result.split('\n')]

    gt_choice = get_type_dbg if dbg_f.result == 0 else get_type

    gt = lambda tname: gt_choice(bv, tname)

    types = {}
    # this is edges for the dependency graph
    # because the output has to be in order
    deps = {}
    for tname in typenames:
        tobj = gt(tname)
        if tobj is None:
            print(f"Error: Could not find type {tname}")
            continue
        types[tname] = tobj

        # get dependencies
        tdeps = get_type_deps(bv, tobj, tname)

        # recurse as needed
        if rec_f.result == 0:
            for d in tdeps:
                if d not in typenames:
                    typenames.append(d)
        else:
            # if not recursing, we still want good order for deps between included types
            tdeps = tdeps.intersection(set(typenames))

        deps[tname] = tdeps

    # now start generating our type definitions
    # we want to start with types that have no dependencies and continue until we have consumed all the types
    declared = set()
    report = header_template

    while len(deps) > 0:
        # find an item with no deps
        found = None
        least_amt = -1
        least = None
        for tname in deps:
            depcount = len(deps[tname])
            if least_amt == -1 or depcount < least_amt:
                least_amt = depcount
                least = tname
            if len(deps[tname]) == 0:
                found = tname
                break

        if found is None:
            if least is None:
                print("Found Dependency errors, trying anyways")
                least = deps.keys()[0]

            # still just generate the definitions
            # Circular type dependencies detected, adding forward declarations
            found = least

            print("DBG: Could not find, have to fwd declare for", found)
            for dname in list(deps[found]):
                print("DBG: FWD for", dname)
                # add the declaration (everything without the _fields_)
                piece, partial = declaration(bv, dname, types[dname], pre_f.result, declared, gt)
                report += piece
                declared.add(dname)
                if not partial:
                    del deps[dname]

                # remove all the dependencies, but not the entries
                for tname in deps:
                    if dname in deps[tname]:
                        deps[tname].remove(dname)
            
        # generate
        if found in declared:
            report += part_definition(bv, found, types[found], pre_f.result)
        else:
            report += full_definition(bv, found, types[found], pre_f.result)
            declared.add(found)

        # remove the dependencies on this one
        del deps[found]
        for tname in deps:
            if found in deps[tname]:
                deps[tname].remove(found)

        
    filename = out_f.result
    if len(filename) == 0:
        show_markdown_report("Type Definitions", markdown_template.format(report=report), report)
    else:
        with open(filename, "w") as fp:
            fp.write(report)
    
    print("ctypes export done")

    return True

#TODO
# - Option or command or blob pattern matching for exporting all types
# - Option to export a whole type archive

PluginCommand.register("Export types to ctypes", "Export one or more types to ctypes", export_some)

# we could use TypePrinter.register()
# but this isn't really for viewing, it is for harnesses
# so probably best to just output the definitions